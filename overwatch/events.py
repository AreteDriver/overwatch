"""In-process event bus for real-time WebSocket broadcasting and alert dispatch."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

log = logging.getLogger(__name__)

MAX_FAILURES = 10
WEBHOOK_TIMEOUT = 5.0

# Global event subscribers (WebSocket connections + alert handlers)
_subscribers: list[asyncio.Queue] = []
_sync_handlers: list[Callable[[dict[str, Any]], None]] = []


def subscribe() -> asyncio.Queue:
    """Register a new WebSocket subscriber. Returns a queue to read from."""
    q: asyncio.Queue = asyncio.Queue(maxsize=256)
    _subscribers.append(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    """Remove a subscriber."""
    if q in _subscribers:
        _subscribers.remove(q)


def subscriber_count() -> int:
    """Return number of active WebSocket subscribers."""
    return len(_subscribers)


def register_sync_handler(handler: Callable[[dict[str, Any]], None]) -> None:
    """Register a synchronous event handler (e.g. alert dispatcher)."""
    _sync_handlers.append(handler)


def publish(event_type: str, data: dict[str, Any]) -> None:
    """Publish an event to all subscribers and sync handlers."""
    payload = {
        "event": event_type,
        "data": data,
        "timestamp": datetime.now().isoformat(),
    }
    # Broadcast to WebSocket subscribers
    for q in list(_subscribers):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            log.warning("Subscriber queue full, dropping event")

    # Fire sync handlers (alerts, webhooks, etc.)
    for handler in _sync_handlers:
        try:
            handler(payload)
        except Exception:
            log.exception("Event handler error")


def dispatch_webhooks(
    session_factory: Callable,
    event_type: str,
    payload: dict[str, Any],
) -> int:
    """POST event payload to all active webhooks matching the event_type.

    Returns the number of successfully delivered webhooks.
    """
    from overwatch.models import WebhookRow

    session = session_factory()
    delivered = 0
    try:
        webhooks = session.query(WebhookRow).filter(WebhookRow.active == 1).all()

        body_bytes = json.dumps(payload, default=str).encode()

        for wh in webhooks:
            event_types: list[str] = json.loads(wh.event_types or "[]")
            if event_type not in event_types:
                continue

            headers: dict[str, str] = {"Content-Type": "application/json"}
            if wh.secret:
                sig = hmac.new(wh.secret.encode(), body_bytes, hashlib.sha256).hexdigest()
                headers["X-Overwatch-Signature"] = sig

            try:
                with httpx.Client(timeout=WEBHOOK_TIMEOUT) as client:
                    resp = client.post(wh.url, content=body_bytes, headers=headers)
                    resp.raise_for_status()
                wh.failure_count = 0
                wh.last_delivered_at = datetime.now(UTC)
                delivered += 1
            except Exception:
                wh.failure_count = (wh.failure_count or 0) + 1
                log.warning(
                    "Webhook %s delivery failed (%d/%d): %s",
                    wh.id,
                    wh.failure_count,
                    MAX_FAILURES,
                    wh.url,
                )
                if wh.failure_count >= MAX_FAILURES:
                    wh.active = 0
                    log.warning("Webhook %s deactivated after %d failures", wh.id, MAX_FAILURES)

        session.commit()
    except Exception:
        log.exception("dispatch_webhooks error")
        session.rollback()
    finally:
        session.close()

    return delivered
