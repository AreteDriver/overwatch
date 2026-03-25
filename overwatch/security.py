"""Security layer — API key auth, rate limiting, security headers."""

from __future__ import annotations

import hashlib
import logging
import time
from collections import defaultdict
from typing import Any

from fastapi import HTTPException, Request, WebSocket
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


def verify_api_key(request: Request) -> None:
    """Verify API key from Authorization header.

    Raises HTTPException 401 if invalid.
    Does nothing if API_KEY is not configured (open mode).
    """
    if not API_KEY:
        return  # No key configured = open mode

    if _is_public(request.url.path):
        return

    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
    elif auth:
        token = auth
    else:
        # Also check X-API-Key header
        token = request.headers.get("X-API-Key", "")

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Missing API key. Use Authorization: Bearer <key> or X-API-Key header.",
        )

    # Constant-time comparison via hash
    if hashlib.sha256(token.encode()).hexdigest() != hashlib.sha256(API_KEY.encode()).hexdigest():
        raise HTTPException(status_code=401, detail="Invalid API key.")


def verify_ws_api_key(websocket: WebSocket) -> bool:
    """Verify API key for WebSocket from query param ?key=..."""
    if not API_KEY:
        return True

    token = websocket.query_params.get("key", "")
    if not token:
        return False
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    key_hash = hashlib.sha256(API_KEY.encode()).hexdigest()
    return token_hash == key_hash


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
