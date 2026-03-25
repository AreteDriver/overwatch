"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from overwatch.api.routes import _get_session, router
from overwatch.database import get_engine, get_session_factory, init_db


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

    # Override the session dependency
    app.dependency_overrides[_get_session] = session_dep
    yield
    engine.dispose()


app = FastAPI(
    title="Overwatch",
    description=(
        "Tactical ISR Dashboard API — unifies YOLO detections, OSINT intel, and drone telemetry"
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")
