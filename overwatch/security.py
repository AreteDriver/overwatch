"""Security layer — API key auth, rate limiting, security headers."""

from __future__ import annotations

import hashlib
import logging
import time
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, Request, WebSocket
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from overwatch.config import (
    API_KEY,
    RATE_LIMIT_REQUESTS,
    RATE_LIMIT_WINDOW,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# API Key Authentication
# ---------------------------------------------------------------------------

# Public endpoints that don't require auth
PUBLIC_PATHS: set[str] = {
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
}


def _is_public(path: str) -> bool:
    """Check if a path is public (no auth required)."""
    return path in PUBLIC_PATHS or path.startswith("/docs") or path.startswith("/redoc")


def verify_api_key(request: Request, session_factory: object | None = None) -> None:
    """Verify API key from Authorization header.

    Checks master key first, then DB-stored keys if session_factory is provided.
    Raises HTTPException 401 if invalid.
    Does nothing if API_KEY is not configured (open mode).
    """
    if not API_KEY:
        return  # No key configured = open mode

    if _is_public(request.url.path):
        return

    token = _extract_token(request)

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Missing API key. Use Authorization: Bearer <key> or X-API-Key header.",
        )

    # Check master key first
    if _hash_key(token) == _hash_key(API_KEY):
        return

    # Check DB-stored keys (any active key passes gateway auth)
    if session_factory is not None:
        from overwatch.models import ApiKeyRow

        session = session_factory()
        try:
            row = (
                session.query(ApiKeyRow)
                .filter(ApiKeyRow.key_hash == _hash_key(token), ApiKeyRow.active == 1)
                .first()
            )
            if row is not None:
                return
        finally:
            session.close()

    raise HTTPException(status_code=401, detail="Invalid API key.")


def verify_ws_api_key(websocket: WebSocket, session_factory: object | None = None) -> bool:
    """Verify API key for WebSocket from query param ?key=...

    Accepts master key or any active DB-stored key.
    """
    if not API_KEY:
        return True

    token = websocket.query_params.get("key", "")
    if not token:
        return False

    # Check master key
    if _hash_key(token) == _hash_key(API_KEY):
        return True

    # Check DB keys
    if session_factory is not None:
        from overwatch.models import ApiKeyRow

        session = session_factory()
        try:
            row = (
                session.query(ApiKeyRow)
                .filter(ApiKeyRow.key_hash == _hash_key(token), ApiKeyRow.active == 1)
                .first()
            )
            if row is not None:
                return True
        finally:
            session.close()

    return False


# ---------------------------------------------------------------------------
# Scoped API Key Authentication
# ---------------------------------------------------------------------------


def _extract_token(request: Request) -> str:
    """Extract the bearer/API-key token from a request, or empty string."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    if auth:
        return auth
    return request.headers.get("X-API-Key", "")


def _hash_key(raw_key: str) -> str:
    """SHA-256 hex digest of a raw API key."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def verify_api_key_scoped(
    request: Request,
    session: Session,
    required_scope: str,
) -> None:
    """Verify that the request carries a valid API key with the required scope.

    Checks in order:
    1. If no master API_KEY is configured, allow (open mode).
    2. Master key (env var) — implicitly has all scopes.
    3. Database-stored scoped keys — must be active and carry the scope.

    Updates ``last_used_at`` on successful DB key match.

    Raises HTTPException 401/403 on failure.
    """
    from overwatch.models import ApiKeyRow

    if not API_KEY:
        return  # open mode

    if _is_public(request.url.path):
        return

    token = _extract_token(request)
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Missing API key. Use Authorization: Bearer <key> or X-API-Key header.",
        )

    # Check master key first (has all scopes)
    if _hash_key(token) == _hash_key(API_KEY):
        return

    # Check database-stored keys
    token_hash = _hash_key(token)
    row: ApiKeyRow | None = (
        session.query(ApiKeyRow)
        .filter(ApiKeyRow.key_hash == token_hash, ApiKeyRow.active == 1)
        .first()
    )

    if row is None:
        raise HTTPException(status_code=401, detail="Invalid API key.")

    if required_scope not in row.scopes:
        raise HTTPException(
            status_code=403,
            detail=f"API key lacks required scope: {required_scope}",
        )

    # Update last_used_at
    row.last_used_at = datetime.now(UTC)
    session.commit()


# ---------------------------------------------------------------------------
# Security Headers Middleware
# ---------------------------------------------------------------------------


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cache-Control"] = "no-store"

        # Strict-Transport-Security only if behind HTTPS (Fly.io)
        if request.url.scheme == "https" or request.headers.get("X-Forwarded-Proto") == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        return response


# ---------------------------------------------------------------------------
# Rate Limiting Middleware
# ---------------------------------------------------------------------------

# In-memory rate limit store (per-process, resets on restart)
_rate_store: dict[str, list[float]] = defaultdict(list)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple sliding-window rate limiter per client IP."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        if RATE_LIMIT_REQUESTS <= 0:
            return await call_next(request)

        if _is_public(request.url.path):
            return await call_next(request)

        client_ip = _get_client_ip(request)
        now = time.monotonic()
        window_start = now - RATE_LIMIT_WINDOW

        # Clean old entries
        _rate_store[client_ip] = [t for t in _rate_store[client_ip] if t > window_start]

        if len(_rate_store[client_ip]) >= RATE_LIMIT_REQUESTS:
            log.warning("Rate limit exceeded for %s", client_ip)
            return Response(
                content='{"detail":"Rate limit exceeded"}',
                status_code=429,
                media_type="application/json",
                headers={
                    "Retry-After": str(int(RATE_LIMIT_WINDOW)),
                    "X-RateLimit-Limit": str(RATE_LIMIT_REQUESTS),
                },
            )

        _rate_store[client_ip].append(now)
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(RATE_LIMIT_REQUESTS)
        response.headers["X-RateLimit-Remaining"] = str(
            max(0, RATE_LIMIT_REQUESTS - len(_rate_store[client_ip]))
        )
        return response


def _get_client_ip(request: Request) -> str:
    """Extract client IP, respecting X-Forwarded-For behind proxy."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------------------
# Utility: clear rate limit store (for testing)
# ---------------------------------------------------------------------------


def clear_rate_store() -> None:
    _rate_store.clear()
