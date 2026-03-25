"""WebSocket feed tests."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from overwatch.api.routes import _get_session, router
from overwatch.events import publish
from overwatch.models import Base


def _make_ws_app(api_key: str = ""):
    """Create a test app with the full WebSocket endpoint."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield

    test_app = FastAPI(lifespan=lifespan)
    test_app.include_router(router, prefix="/api")

    # Import and mount the websocket endpoint from app module
    from overwatch.app import health_check, websocket_feed

    test_app.add_api_websocket_route("/ws/feed", websocket_feed)
    test_app.add_api_route("/health", health_check)

    def override_session():
        sess = factory()
        try:
            yield sess
        finally:
            sess.close()

    test_app.dependency_overrides[_get_session] = override_session
    return test_app, engine


class TestWebSocketFeed:
    """Tests for the /ws/feed WebSocket endpoint."""

    def test_connect_and_receive_event(self):
        """WebSocket connects and receives published events."""
        with patch("overwatch.app.verify_ws_api_key", return_value=True):
            app, engine = _make_ws_app()
            with TestClient(app) as client:
                with client.websocket_connect("/ws/feed") as ws:
                    publish("detection", {"label": "person", "confidence": 0.95})
                    data = ws.receive_json()
                    assert data["event"] == "detection"
                    assert data["data"]["label"] == "person"
                    assert "timestamp" in data
            engine.dispose()

    def test_connect_receives_multiple_events(self):
        """WebSocket receives multiple sequential events."""
        with patch("overwatch.app.verify_ws_api_key", return_value=True):
            app, engine = _make_ws_app()
            with TestClient(app) as client:
                with client.websocket_connect("/ws/feed") as ws:
                    publish("detection", {"label": "car"})
                    publish("intel", {"title": "breaking news"})

                    ev1 = ws.receive_json()
                    ev2 = ws.receive_json()
                    assert ev1["event"] == "detection"
                    assert ev2["event"] == "intel"
            engine.dispose()

    def test_connect_rejected_without_key(self):
        """WebSocket rejects connection when API key is wrong."""
        with patch("overwatch.app.verify_ws_api_key", return_value=False):
            app, engine = _make_ws_app()
            with TestClient(app) as client:
                with pytest.raises(Exception):
                    with client.websocket_connect("/ws/feed") as ws:
                        ws.receive_json()
            engine.dispose()
