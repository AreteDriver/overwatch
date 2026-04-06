"""Tests for webhook subscriptions."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from overwatch.api.routes import _get_session
from overwatch.app import app
from overwatch.models import Base, WebhookRow


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


class TestWebhookCRUD:
    def test_create_webhook(self, client):
        c, _ = client
        resp = c.post(
            "/api/webhooks",
            json={
                "url": "https://example.com/hook",
                "event_types": ["detection", "alert"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["url"] == "https://example.com/hook"
        assert data["event_types"] == ["detection", "alert"]
        assert data["active"] is True

    def test_list_webhooks(self, client):
        c, _ = client
        c.post(
            "/api/webhooks",
            json={
                "url": "https://a.com/hook",
                "event_types": ["detection"],
            },
        )
        c.post(
            "/api/webhooks",
            json={
                "url": "https://b.com/hook",
                "event_types": ["intel"],
            },
        )
        resp = c.get("/api/webhooks")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_delete_webhook(self, client):
        c, _ = client
        create = c.post(
            "/api/webhooks",
            json={
                "url": "https://delete.com/hook",
                "event_types": ["detection"],
            },
        )
        wh_id = create.json()["id"]

        resp = c.delete(f"/api/webhooks/{wh_id}")
        assert resp.status_code == 200

        resp = c.delete(f"/api/webhooks/{wh_id}")
        assert resp.status_code == 404

    def test_create_with_secret(self, client):
        c, _ = client
        resp = c.post(
            "/api/webhooks",
            json={
                "url": "https://secure.com/hook",
                "event_types": ["detection"],
                "secret": "my-secret-key",
            },
        )
        assert resp.status_code == 200
        # Secret should not be exposed in response
        data = resp.json()
        assert "secret" not in data or data.get("secret") is None


class TestWebhookModel:
    def test_webhook_row_defaults(self):
        row = WebhookRow(
            url="https://test.com",
            event_types=json.dumps(["detection"]),
        )
        assert row.active is None or row.active == 1  # default
        assert row.failure_count is None or row.failure_count == 0
