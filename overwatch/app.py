"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from overwatch.api.routes import _get_session, router
from overwatch.config import CORS_ORIGINS
from overwatch.database import get_engine, get_session_factory, init_db
from overwatch.events import subscribe, unsubscribe
from overwatch.security import (
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    verify_api_key,
    verify_ws_api_key,
)


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
    """Enforce API key on all non-public routes."""
    try:
        verify_api_key(request)
    except Exception as exc:
        return JSONResponse(
            status_code=getattr(exc, "status_code", 401),
            content={"detail": str(getattr(exc, "detail", "Unauthorized"))},
        )
    return await call_next(request)


app.include_router(router, prefix="/api")


@app.get("/health", tags=["system"])
def health_check():
    """Public health check endpoint for monitoring."""
    return {"status": "ok", "version": "0.2.0"}


@app.websocket("/ws/feed")
async def websocket_feed(websocket: WebSocket):
    """Real-time event feed via WebSocket.

    Authenticate with ?key=<api_key> query param if API_KEY is set.
    """
    if not verify_ws_api_key(websocket):
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
