"""Shared test fixtures."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from overwatch.models import Base


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
