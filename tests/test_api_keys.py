"""Tests for multi-user scoped API key management."""

from __future__ import annotations

import hashlib
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from overwatch.api.routes import _get_session
from overwatch.app import app
from overwatch.models import ApiKeyRow, Base
from overwatch.security import _hash_key, verify_api_key_scoped


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_session():
        sess = factory()
        try:
            yield sess
        finally:
            sess.close()

    with TestClient(app) as c:
        app.dependency_overrides[_get_session] = override_session
        app.state.session_factory = factory
        app.state.engine = engine
        yield c, factory

    app.dependency_overrides.clear()
    engine.dispose()


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------


class TestApiKeyCRUD:
    def test_create_key(self, client):
        c, _ = client
        resp = c.post(
            "/api/admin/keys",
            json={"name": "watcher-node-1", "scopes": ["write"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "watcher-node-1"
        assert "key" in data  # raw key returned once
        assert data["scopes"] == ["write"]

    def test_list_keys_no_hash(self, client):
        c, _ = client
        c.post("/api/admin/keys", json={"name": "key-a", "scopes": ["read"]})
        c.post("/api/admin/keys", json={"name": "key-b", "scopes": ["read", "write"]})

        resp = c.get("/api/admin/keys")
        assert resp.status_code == 200
        keys = resp.json()
        assert len(keys) == 2
        for k in keys:
            assert "key_hash" not in k
            assert "key" not in k

    def test_deactivate_key(self, client):
        c, _ = client
        create = c.post("/api/admin/keys", json={"name": "temp", "scopes": ["read"]})
        key_id = create.json()["id"]

        resp = c.delete(f"/api/admin/keys/{key_id}")
        assert resp.status_code == 200

        # Verify deactivated
        resp = c.get("/api/admin/keys")
        keys = resp.json()
        deactivated = [k for k in keys if k["id"] == key_id]
        assert len(deactivated) == 1
        assert deactivated[0]["active"] is False

    def test_deactivate_nonexistent(self, client):
        c, _ = client
        resp = c.delete("/api/admin/keys/nonexistent")
        assert resp.status_code == 404

    def test_key_hash_stored_not_raw(self, client):
        c, factory = client
        create = c.post("/api/admin/keys", json={"name": "hash-test", "scopes": ["read"]})
        raw_key = create.json()["key"]
        key_id = create.json()["id"]

        sess = factory()
        row = sess.query(ApiKeyRow).filter(ApiKeyRow.id == key_id).first()
        assert row is not None
        assert row.key_hash == hashlib.sha256(raw_key.encode()).hexdigest()
        assert row.key_hash != raw_key
        sess.close()

    def test_default_scope_is_read(self, client):
        c, _ = client
        resp = c.post("/api/admin/keys", json={"name": "default-scope"})
        assert resp.status_code == 200
        assert resp.json()["scopes"] == ["read"]

    def test_invalid_scope_rejected(self, client):
        c, _ = client
        resp = c.post("/api/admin/keys", json={"name": "bad", "scopes": ["root"]})
        assert resp.status_code == 422

    def test_list_keys_ordered_newest_first(self, client):
        c, _ = client
        c.post("/api/admin/keys", json={"name": "first"})
        c.post("/api/admin/keys", json={"name": "second"})
        keys = c.get("/api/admin/keys").json()
        assert keys[0]["name"] == "second"
        assert keys[1]["name"] == "first"


# ---------------------------------------------------------------------------
# verify_api_key_scoped unit tests
# ---------------------------------------------------------------------------


class TestScopedAuth:
    def test_hash_key_deterministic(self):
        assert _hash_key("abc") == hashlib.sha256(b"abc").hexdigest()
        assert _hash_key("abc") == _hash_key("abc")

    def test_open_mode_passes(self):
        """No master key configured = open mode, all scopes pass."""
        with patch("overwatch.security.API_KEY", ""):
            verify_api_key_scoped(MagicMock(), MagicMock(), "admin")

    def test_master_key_has_all_scopes(self):
        with patch("overwatch.security.API_KEY", "master-secret"):
            request = MagicMock()
            request.url.path = "/api/something"
            request.headers = {"Authorization": "Bearer master-secret"}
            verify_api_key_scoped(request, MagicMock(), "admin")

    def test_db_key_valid_scope(self):
        """DB key with matching scope passes and updates last_used_at."""
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        sess = sessionmaker(bind=engine, expire_on_commit=False)()

        raw_key = "test-db-key-123"
        row = ApiKeyRow(
            id="k1",
            name="test",
            key_hash=_hash_key(raw_key),
            scopes_json='["read", "write"]',
            active=1,
        )
        sess.add(row)
        sess.commit()

        with patch("overwatch.security.API_KEY", "other-master"):
            request = MagicMock()
            request.url.path = "/api/data"
            request.headers = {"Authorization": f"Bearer {raw_key}"}
            verify_api_key_scoped(request, sess, "read")

            sess.refresh(row)
            assert row.last_used_at is not None

        sess.close()
        engine.dispose()

    def test_db_key_missing_scope_403(self):
        """DB key without required scope gets 403."""
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        sess = sessionmaker(bind=engine, expire_on_commit=False)()

        raw_key = "readonly-key"
        row = ApiKeyRow(
            id="k2",
            name="readonly",
            key_hash=_hash_key(raw_key),
            scopes_json='["read"]',
            active=1,
        )
        sess.add(row)
        sess.commit()

        with patch("overwatch.security.API_KEY", "master"):
            request = MagicMock()
            request.url.path = "/api/data"
            request.headers = {"Authorization": f"Bearer {raw_key}"}
            with pytest.raises(HTTPException) as exc_info:
                verify_api_key_scoped(request, sess, "admin")
            assert exc_info.value.status_code == 403

        sess.close()
        engine.dispose()

    def test_inactive_key_rejected_401(self):
        """Deactivated key gets 401."""
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        sess = sessionmaker(bind=engine, expire_on_commit=False)()

        raw_key = "inactive-key"
        row = ApiKeyRow(
            id="k3",
            name="dead",
            key_hash=_hash_key(raw_key),
            scopes_json='["read"]',
            active=0,
        )
        sess.add(row)
        sess.commit()

        with patch("overwatch.security.API_KEY", "master"):
            request = MagicMock()
            request.url.path = "/api/data"
            request.headers = {"Authorization": f"Bearer {raw_key}"}
            with pytest.raises(HTTPException) as exc_info:
                verify_api_key_scoped(request, sess, "read")
            assert exc_info.value.status_code == 401

        sess.close()
        engine.dispose()

    def test_no_token_401(self):
        """Missing token gets 401."""
        with patch("overwatch.security.API_KEY", "master"):
            request = MagicMock()
            request.url.path = "/api/data"
            request.headers = {}
            with pytest.raises(HTTPException) as exc_info:
                verify_api_key_scoped(request, MagicMock(), "read")
            assert exc_info.value.status_code == 401

    def test_unknown_token_401(self):
        """Unknown token gets 401."""
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        sess = sessionmaker(bind=engine, expire_on_commit=False)()

        with patch("overwatch.security.API_KEY", "master"):
            request = MagicMock()
            request.url.path = "/api/data"
            request.headers = {"Authorization": "Bearer wrong-key"}
            with pytest.raises(HTTPException) as exc_info:
                verify_api_key_scoped(request, sess, "read")
            assert exc_info.value.status_code == 401

        sess.close()
        engine.dispose()
