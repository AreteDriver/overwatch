"""Tests for overwatch.events — dispatch_webhooks, publish, subscriber_count."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from overwatch import events
from overwatch.events import (
    MAX_FAILURES,
    dispatch_webhooks,
    publish,
    register_sync_handler,
    subscribe,
    subscriber_count,
    unsubscribe,
)
from overwatch.models import Base, WebhookRow

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture()
def session(session_factory):
    sess = session_factory()
    yield sess
    sess.close()


@pytest.fixture(autouse=True)
def _clean_bus():
    """Reset global event bus state between tests."""
    old_subs = events._subscribers.copy()
    old_handlers = events._sync_handlers.copy()
    events._subscribers.clear()
    events._sync_handlers.clear()
    yield
    events._subscribers.clear()
    events._sync_handlers.clear()
    events._subscribers.extend(old_subs)
    events._sync_handlers.extend(old_handlers)


# ---------------------------------------------------------------------------
# dispatch_webhooks tests
# ---------------------------------------------------------------------------


def _make_webhook(session, *, url="https://hook.example.com/cb", event_types=None, secret=""):
    """Helper to insert a webhook row."""
    wh = WebhookRow(
        url=url,
        event_types=json.dumps(event_types or ["detection"]),
        secret=secret,
        active=True,
        failure_count=0,
    )
    session.add(wh)
    session.commit()
    return wh


class TestDispatchWebhooksMatching:
    """Test dispatch_webhooks delivers to matching webhooks."""

    def test_matching_webhook_delivers(self, session_factory, session):
        wh = _make_webhook(session)
        payload = {"label": "person", "confidence": 0.95}

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            delivered = dispatch_webhooks(session_factory, "detection", payload)

        assert delivered == 1
        # Verify failure_count reset to 0
        session.refresh(wh)
        assert wh.failure_count == 0
        assert wh.last_delivered_at is not None

    def test_non_matching_event_type_skipped(self, session_factory, session):
        _make_webhook(session, event_types=["detection"])
        payload = {"msg": "test"}

        delivered = dispatch_webhooks(session_factory, "telemetry", payload)
        assert delivered == 0


class TestHmacSignature:
    """Test HMAC-SHA256 signature generation when webhook has a secret."""

    def test_signature_header_present(self, session_factory, session):
        secret = "my-secret-key"
        _make_webhook(session, secret=secret)
        payload = {"label": "drone"}
        body_bytes = json.dumps(payload, default=str).encode()
        expected_sig = hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()

        captured_headers = {}

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()

        def capture_post(url, content, headers):
            captured_headers.update(headers)
            return mock_resp

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.side_effect = capture_post
            mock_client_cls.return_value = mock_client

            dispatch_webhooks(session_factory, "detection", payload)

        assert captured_headers.get("X-Overwatch-Signature") == expected_sig

    def test_no_signature_without_secret(self, session_factory, session):
        _make_webhook(session, secret="")
        payload = {"label": "vehicle"}

        captured_headers = {}

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()

        def capture_post(url, content, headers):
            captured_headers.update(headers)
            return mock_resp

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.side_effect = capture_post
            mock_client_cls.return_value = mock_client

            dispatch_webhooks(session_factory, "detection", payload)

        assert "X-Overwatch-Signature" not in captured_headers


class TestFailureCounting:
    """Test failure_count increments and auto-deactivation."""

    def test_failure_increments_on_http_error(self, session_factory, session):
        wh = _make_webhook(session)

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.side_effect = httpx.HTTPStatusError(
                "500", request=MagicMock(), response=MagicMock()
            )
            mock_client_cls.return_value = mock_client

            delivered = dispatch_webhooks(session_factory, "detection", {"x": 1})

        assert delivered == 0
        session.refresh(wh)
        assert wh.failure_count == 1
        assert wh.active is True  # still active after 1 failure

    def test_auto_deactivation_after_max_failures(self, session_factory, session):
        wh = _make_webhook(session)
        # Pre-set failure count to MAX_FAILURES - 1
        wh.failure_count = MAX_FAILURES - 1
        session.commit()

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.side_effect = Exception("connection refused")
            mock_client_cls.return_value = mock_client

            dispatch_webhooks(session_factory, "detection", {"x": 1})

        session.refresh(wh)
        assert wh.failure_count == MAX_FAILURES
        assert wh.active is False  # deactivated

    def test_success_resets_failure_count(self, session_factory, session):
        wh = _make_webhook(session)
        wh.failure_count = 5
        session.commit()

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            delivered = dispatch_webhooks(session_factory, "detection", {"x": 1})

        assert delivered == 1
        session.refresh(wh)
        assert wh.failure_count == 0


# ---------------------------------------------------------------------------
# subscriber_count / subscribe / unsubscribe tests
# ---------------------------------------------------------------------------


class TestSubscriberCount:
    def test_initial_count_zero(self):
        assert subscriber_count() == 0

    def test_subscribe_increments(self):
        q1 = subscribe()
        assert subscriber_count() == 1
        q2 = subscribe()
        assert subscriber_count() == 2
        unsubscribe(q1)
        unsubscribe(q2)

    def test_unsubscribe_decrements(self):
        q = subscribe()
        assert subscriber_count() == 1
        unsubscribe(q)
        assert subscriber_count() == 0

    def test_unsubscribe_nonexistent_is_noop(self):
        q = asyncio.Queue()
        unsubscribe(q)  # should not raise
        assert subscriber_count() == 0


# ---------------------------------------------------------------------------
# publish tests
# ---------------------------------------------------------------------------


class TestPublish:
    def test_publish_fires_sync_handlers(self):
        received = []
        handler = lambda payload: received.append(payload)  # noqa: E731
        register_sync_handler(handler)

        publish("detection", {"label": "person"})

        assert len(received) == 1
        assert received[0]["event"] == "detection"
        assert received[0]["data"]["label"] == "person"
        assert "timestamp" in received[0]

    def test_publish_enqueues_to_subscribers(self):
        q = subscribe()
        publish("telemetry", {"lat": 46.0})
        assert not q.empty()
        msg = q.get_nowait()
        assert msg["event"] == "telemetry"

    def test_publish_handles_queue_full_gracefully(self):
        q = asyncio.Queue(maxsize=1)
        events._subscribers.append(q)

        # Fill the queue
        q.put_nowait({"filler": True})

        # Should not raise — just logs a warning
        publish("detection", {"label": "overflow"})

        # Queue still has original item, second was dropped
        assert q.qsize() == 1
        msg = q.get_nowait()
        assert msg["filler"] is True

    def test_publish_handles_handler_exception(self):
        def bad_handler(payload):
            raise ValueError("boom")

        register_sync_handler(bad_handler)

        # Should not raise
        publish("detection", {"label": "safe"})
