"""In-process event bus for real-time WebSocket broadcasting and alert dispatch."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

log = logging.getLogger(__name__)

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

    # Fire sync handlers (alerts, etc.)
    for handler in _sync_handlers:
        try:
            handler(payload)
        except Exception:
            log.exception("Event handler error")
