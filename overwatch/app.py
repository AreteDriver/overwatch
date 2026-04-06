"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from overwatch.api.routes import _get_session, router
from overwatch.config import CORS_ORIGINS, RETENTION_DAYS, RETENTION_PURGE_INTERVAL_HOURS
from overwatch.database import get_engine, get_session_factory, init_db
from overwatch.events import (
    dispatch_webhooks,
    register_sync_handler,
    subscribe,
    subscriber_count,
    unsubscribe,
)
from overwatch.retention import purge_old_records
from overwatch.security import (
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    verify_api_key,
    verify_ws_api_key,
)

log = logging.getLogger(__name__)


async def _retention_loop(session_factory, interval_hours: int) -> None:
    """Background task that purges old records on a schedule."""
    while True:
        await asyncio.sleep(interval_hours * 3600)
        session = session_factory()
        try:
            purge_old_records(session)
        except Exception:
            log.exception("Retention purge failed")
        finally:
            session.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup."""
    engine = get_engine()
    init_db(engine)
    session_factory = get_session_factory(engine)

    def session_dep():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[_get_session] = session_dep

    # Start background retention purge if configured
    purge_task = None
    if RETENTION_DAYS > 0 and RETENTION_PURGE_INTERVAL_HOURS > 0:
        purge_task = asyncio.create_task(
            _retention_loop(session_factory, RETENTION_PURGE_INTERVAL_HOURS)
        )
        log.info(
            "Retention purge: every %dh, deleting records older than %d days",
            RETENTION_PURGE_INTERVAL_HOURS,
            RETENTION_DAYS,
        )

    # Register webhook dispatch as sync handler on the event bus
    def _webhook_handler(payload: dict) -> None:
        event_type = payload.get("event", "")
        dispatch_webhooks(session_factory, event_type, payload)

    register_sync_handler(_webhook_handler)

    # Store session_factory for health endpoint
    app.state.session_factory = session_factory
    app.state.engine = engine

    yield

    if purge_task:
        purge_task.cancel()
    engine.dispose()


app = FastAPI(
    title="Overwatch",
    description=(
        "Tactical ISR Dashboard API — unifies YOLO detections, OSINT intel, and drone telemetry"
    ),
    version="0.3.0",
    lifespan=lifespan,
)

# Security middleware (LIFO order — SecurityHeaders outermost, then Rate, then CORS)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Auth dependency on all API routes
@app.middleware("http")
async def auth_middleware(request, call_next):
    """Enforce API key on all non-public routes (master key or any active DB key)."""
    try:
        sf = getattr(app.state, "session_factory", None)
        verify_api_key(request, session_factory=sf)
    except Exception as exc:
        return JSONResponse(
            status_code=getattr(exc, "status_code", 401),
            content={"detail": str(getattr(exc, "detail", "Unauthorized"))},
        )
    return await call_next(request)


app.include_router(router, prefix="/api")


@app.get("/health", tags=["system"])
def health_check():
    """Public health check — enriched with DB size, counts, WS connections."""
    from sqlalchemy import func

    from overwatch.models import (
        AlertRow,
        DetectionRow,
        IntelReportRow,
        TelemetryRow,
    )

    result: dict = {"status": "ok", "version": "0.3.0", "service": "overwatch-isr"}

    try:
        session = app.state.session_factory()
        try:
            result["detections"] = session.query(DetectionRow).count()
            result["intel_reports"] = session.query(IntelReportRow).count()
            result["telemetry_points"] = session.query(TelemetryRow).count()
            result["alerts"] = session.query(AlertRow).count()
            result["last_detection"] = session.query(func.max(DetectionRow.detected_at)).scalar()
            result["last_telemetry"] = session.query(func.max(TelemetryRow.recorded_at)).scalar()
        finally:
            session.close()
    except Exception:
        pass  # health should not fail — return what we have

    # DB file size
    db_url = str(app.state.engine.url)
    if ":///" in db_url:
        db_path = db_url.split("///", 1)[1]
        try:
            result["db_size_mb"] = round(os.path.getsize(db_path) / (1024 * 1024), 2)
        except OSError:
            pass

    result["ws_connections"] = subscriber_count()
    result["retention_days"] = RETENTION_DAYS

    return result


@app.websocket("/ws/feed")
async def websocket_feed(websocket: WebSocket):
    """Real-time event feed via WebSocket.

    Authenticate with ?key=<api_key> query param if API_KEY is set.
    """
    sf = getattr(app.state, "session_factory", None)
    if not verify_ws_api_key(websocket, session_factory=sf):
        await websocket.close(code=4001, reason="Invalid API key")
        return

    await websocket.accept()
    queue = subscribe()
    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        unsubscribe(queue)
