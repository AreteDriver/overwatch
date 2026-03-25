"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from overwatch.api.routes import _get_session, router
from overwatch.database import get_engine, get_session_factory, init_db
from overwatch.events import subscribe, unsubscribe


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
    yield
    engine.dispose()


app = FastAPI(
    title="Overwatch",
    description=(
        "Tactical ISR Dashboard API — unifies YOLO detections, OSINT intel, and drone telemetry"
    ),
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


@app.websocket("/ws/feed")
async def websocket_feed(websocket: WebSocket):
    """Real-time event feed via WebSocket.

    Broadcasts all ingest events (detections, intel, telemetry, alerts)
    as they arrive.
    """
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
