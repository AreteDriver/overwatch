"""Shared test fixtures."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from overwatch.api.routes import _get_session, router
from overwatch.models import Base


def create_test_app(
    *,
    rate_limit: int = 0,
    api_key: str = "",
    add_cors: bool = False,
) -> tuple[FastAPI, object]:
    """Create a fresh FastAPI app with in-memory SQLite for testing.

    Args:
        rate_limit: Max requests per window (0 = disabled).
        api_key: Master API key string (empty = open mode).  The caller must
            patch ``overwatch.security.API_KEY`` if non-empty.
        add_cors: Whether to mount CORSMiddleware.
    """
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

    if add_cors:
        test_app.add_middleware(
            CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
        )

    test_app.include_router(router, prefix="/api")

    @test_app.get("/health")
    def _health():
        return {"status": "ok"}

    def override_session():
        sess = factory()
        try:
            yield sess
        finally:
            sess.close()

    test_app.dependency_overrides[_get_session] = override_session

    # Optional security middleware
    if rate_limit > 0:
        from overwatch.security import RateLimitMiddleware
        test_app.add_middleware(RateLimitMiddleware)

    from overwatch.security import SecurityHeadersMiddleware
    test_app.add_middleware(SecurityHeadersMiddleware)

    if api_key:
        from fastapi.responses import JSONResponse

        from overwatch.security import verify_api_key

        @test_app.middleware("http")
        async def auth_mw(request, call_next):
            try:
                verify_api_key(request)
            except Exception as exc:
                return JSONResponse(
                    status_code=getattr(exc, "status_code", 401),
                    content={"detail": str(getattr(exc, "detail", "Unauthorized"))},
                )
            return await call_next(request)

    return test_app, engine


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
def session(engine):
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    sess = factory()
    yield sess
    sess.close()


@pytest.fixture()
def now():
    return datetime.now(UTC)


@pytest.fixture()
def client():
    test_app, eng = create_test_app(add_cors=True)
    with TestClient(test_app) as c:
        yield c
    eng.dispose()
