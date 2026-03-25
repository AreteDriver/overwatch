"""Tests for security layer."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from overwatch.api.routes import _get_session, router
from overwatch.models import Base
from overwatch.security import clear_rate_store


def _make_app(api_key: str = "", rate_limit: int = 0, cors_origins: str = "*"):
    """Create test app with configurable security settings."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    # We need to patch config BEFORE importing security/app modules
    # Instead, build the app manually with security wired in
    from overwatch.security import (
        RateLimitMiddleware,
        SecurityHeadersMiddleware,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield

    test_app = FastAPI(lifespan=lifespan)
    test_app.include_router(router, prefix="/api")

    @test_app.get("/health")
    def health():
        return {"status": "ok"}

    def override_session():
        sess = factory()
        try:
            yield sess
        finally:
            sess.close()

    test_app.dependency_overrides[_get_session] = override_session

    # Add security middleware if configured
    if rate_limit > 0:
        test_app.add_middleware(RateLimitMiddleware)
    test_app.add_middleware(SecurityHeadersMiddleware)

    # Add auth middleware if key set
    if api_key:
        from fastapi.responses import JSONResponse

        @test_app.middleware("http")
        async def auth_mw(request, call_next):
            from overwatch.security import verify_api_key

            try:
                verify_api_key(request)
            except Exception as exc:
                return JSONResponse(
                    status_code=getattr(exc, "status_code", 401),
                    content={"detail": str(getattr(exc, "detail", "Unauthorized"))},
                )
            return await call_next(request)

    return test_app, engine


# ---------------------------------------------------------------------------
# Security Headers
# ---------------------------------------------------------------------------


class TestSecurityHeaders:
    def test_headers_present(self):
        app, engine = _make_app()
        with TestClient(app) as client:
            resp = client.get("/health")
            assert resp.status_code == 200
            assert resp.headers["X-Content-Type-Options"] == "nosniff"
            assert resp.headers["X-Frame-Options"] == "DENY"
            assert resp.headers["X-XSS-Protection"] == "1; mode=block"
            assert "no-store" in resp.headers["Cache-Control"]
        engine.dispose()


# ---------------------------------------------------------------------------
# API Key Auth
# ---------------------------------------------------------------------------


class TestAPIKeyAuth:
    def test_open_mode_no_key(self):
        """Without API_KEY configured, all endpoints are accessible."""
        app, engine = _make_app(api_key="")
        with TestClient(app) as client:
            resp = client.get("/api/dashboard/stats")
            assert resp.status_code == 200
        engine.dispose()

    def test_auth_required(self):
        """With API_KEY set, unauthenticated requests get 401."""
        with patch("overwatch.security.API_KEY", "test-secret-key"):
            app, engine = _make_app(api_key="test-secret-key")
            with TestClient(app) as client:
                resp = client.get("/api/dashboard/stats")
                assert resp.status_code == 401
            engine.dispose()

    def test_bearer_auth(self):
        """Bearer token auth works."""
        with patch("overwatch.security.API_KEY", "test-secret-key"):
            app, engine = _make_app(api_key="test-secret-key")
            with TestClient(app) as client:
                resp = client.get(
                    "/api/dashboard/stats",
                    headers={"Authorization": "Bearer test-secret-key"},
                )
                assert resp.status_code == 200
            engine.dispose()

    def test_x_api_key_header(self):
        """X-API-Key header auth works."""
        with patch("overwatch.security.API_KEY", "test-secret-key"):
            app, engine = _make_app(api_key="test-secret-key")
            with TestClient(app) as client:
                resp = client.get(
                    "/api/dashboard/stats",
                    headers={"X-API-Key": "test-secret-key"},
                )
                assert resp.status_code == 200
            engine.dispose()

    def test_wrong_key(self):
        """Wrong API key gets 401."""
        with patch("overwatch.security.API_KEY", "correct-key"):
            app, engine = _make_app(api_key="correct-key")
            with TestClient(app) as client:
                resp = client.get(
                    "/api/dashboard/stats",
                    headers={"Authorization": "Bearer wrong-key"},
                )
                assert resp.status_code == 401
            engine.dispose()

    def test_health_always_public(self):
        """Health endpoint is always accessible even with auth."""
        with patch("overwatch.security.API_KEY", "secret"):
            app, engine = _make_app(api_key="secret")
            with TestClient(app) as client:
                resp = client.get("/health")
                assert resp.status_code == 200
            engine.dispose()


# ---------------------------------------------------------------------------
# Rate Limiting
# ---------------------------------------------------------------------------


class TestRateLimiting:
    def test_rate_limit_enforced(self):
        """Requests beyond limit get 429."""
        with (
            patch("overwatch.security.RATE_LIMIT_REQUESTS", 3),
            patch("overwatch.security.RATE_LIMIT_WINDOW", 60),
        ):
            clear_rate_store()
            app, engine = _make_app(rate_limit=3)
            with TestClient(app) as client:
                for _ in range(3):
                    resp = client.get("/api/dashboard/stats")
                    assert resp.status_code == 200

                resp = client.get("/api/dashboard/stats")
                assert resp.status_code == 429
                assert "Rate limit" in resp.json()["detail"]
            engine.dispose()
            clear_rate_store()

    def test_rate_limit_headers(self):
        """Rate limit headers are present."""
        with (
            patch("overwatch.security.RATE_LIMIT_REQUESTS", 100),
            patch("overwatch.security.RATE_LIMIT_WINDOW", 60),
        ):
            clear_rate_store()
            app, engine = _make_app(rate_limit=100)
            with TestClient(app) as client:
                resp = client.get("/api/dashboard/stats")
                assert "X-RateLimit-Limit" in resp.headers
                assert "X-RateLimit-Remaining" in resp.headers
            engine.dispose()
            clear_rate_store()


# ---------------------------------------------------------------------------
# Crypto (field encryption)
# ---------------------------------------------------------------------------


class TestCrypto:
    def test_no_key_passthrough(self):
        """Without encryption key, encrypt/decrypt are no-ops."""
        with patch("overwatch.crypto.ENCRYPTION_KEY", ""), patch("overwatch.crypto._fernet", None):
            from overwatch.crypto import decrypt, encrypt

            assert encrypt("hello") == "hello"
            assert decrypt("hello") == "hello"

    def test_hash_deterministic(self):
        from overwatch.crypto import hash_value

        h1 = hash_value("test")
        h2 = hash_value("test")
        assert h1 == h2
        assert len(h1) == 16

    def test_hash_different_inputs(self):
        from overwatch.crypto import hash_value

        assert hash_value("a") != hash_value("b")


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    def test_health(self):
        app, engine = _make_app()
        with TestClient(app) as client:
            resp = client.get("/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
        engine.dispose()
