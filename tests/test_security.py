"""Tests for security layer."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from overwatch.security import clear_rate_store
from tests.conftest import create_test_app

# ---------------------------------------------------------------------------
# Security Headers
# ---------------------------------------------------------------------------


class TestSecurityHeaders:
    def test_headers_present(self):
        app, engine = create_test_app()
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
        app, engine = create_test_app(api_key="")
        with TestClient(app) as client:
            resp = client.get("/api/dashboard/stats")
            assert resp.status_code == 200
        engine.dispose()

    def test_auth_required(self):
        """With API_KEY set, unauthenticated requests get 401."""
        with patch("overwatch.security.API_KEY", "test-secret-key"):
            app, engine = create_test_app(api_key="test-secret-key")
            with TestClient(app) as client:
                resp = client.get("/api/dashboard/stats")
                assert resp.status_code == 401
            engine.dispose()

    def test_bearer_auth(self):
        """Bearer token auth works."""
        with patch("overwatch.security.API_KEY", "test-secret-key"):
            app, engine = create_test_app(api_key="test-secret-key")
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
            app, engine = create_test_app(api_key="test-secret-key")
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
            app, engine = create_test_app(api_key="correct-key")
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
            app, engine = create_test_app(api_key="secret")
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
            app, engine = create_test_app(rate_limit=3)
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
            app, engine = create_test_app(rate_limit=100)
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
        import overwatch.config
        from overwatch.crypto import _reset_fernet, decrypt, encrypt

        orig = overwatch.config.ENCRYPTION_KEY
        try:
            overwatch.config.ENCRYPTION_KEY = ""
            _reset_fernet()
            assert encrypt("hello") == "hello"
            assert decrypt("hello") == "hello"
        finally:
            overwatch.config.ENCRYPTION_KEY = orig
            _reset_fernet()

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
        app, engine = create_test_app()
        with TestClient(app) as client:
            resp = client.get("/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
        engine.dispose()
