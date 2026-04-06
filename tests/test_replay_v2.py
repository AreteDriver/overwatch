"""Tests for replay improvements — filtering, speed, summary."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from overwatch.analysis.replay import get_replay_frame, get_replay_summary, parse_event_types
from overwatch.api.routes import _get_session
from overwatch.app import app
from overwatch.models import Base, DetectionRow, IntelReportRow, TelemetryRow


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
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_session():
        sess = factory()
        try:
            yield sess
        finally:
            sess.close()

    with TestClient(app) as c:
        app.dependency_overrides[_get_session] = override_session
        app.state.session_factory = factory
        app.state.engine = engine
        yield c, factory

    app.dependency_overrides.clear()
    engine.dispose()


def _seed(session):
    now = datetime.now(UTC)
    session.add(
        DetectionRow(
            source_id="d1",
            label="person",
            confidence=0.9,
            lat=46.0,
            lon=14.0,
            detected_at=now,
        )
    )
    session.add(
        TelemetryRow(
            source_id="t1",
            device_name="drone-1",
            lat=46.0,
            lon=14.0,
            recorded_at=now,
        )
    )
    session.add(
        IntelReportRow(
            source_id="i1",
            title="Report",
            summary="Summary",
            published_at=now,
        )
    )
    session.commit()
    return now


class TestParseEventTypes:
    def test_none_returns_all(self):
        result = parse_event_types(None)
        assert "detections" in result
        assert "telemetry" in result
        assert "intel" in result

    def test_single_type(self):
        result = parse_event_types("detections")
        assert result == {"detections"}

    def test_multiple_types(self):
        result = parse_event_types("detections,telemetry")
        assert result == {"detections", "telemetry"}

    def test_strips_whitespace(self):
        result = parse_event_types("detections , intel")
        assert result == {"detections", "intel"}


class TestReplayFrameFiltering:
    def test_all_types_returned(self, session):
        now = _seed(session)
        start = now - timedelta(hours=1)
        end = now + timedelta(hours=1)

        data = get_replay_frame(session, start, end)
        assert len(data["detections"]) == 1
        assert len(data["telemetry"]) == 1
        assert len(data["intel"]) == 1

    def test_filter_detections_only(self, session):
        now = _seed(session)
        start = now - timedelta(hours=1)
        end = now + timedelta(hours=1)

        data = get_replay_frame(session, start, end, event_types={"detections"})
        assert len(data["detections"]) == 1
        assert len(data["telemetry"]) == 0
        assert len(data["intel"]) == 0

    def test_filter_intel_only(self, session):
        now = _seed(session)
        start = now - timedelta(hours=1)
        end = now + timedelta(hours=1)

        data = get_replay_frame(session, start, end, event_types={"intel"})
        assert len(data["detections"]) == 0
        assert len(data["telemetry"]) == 0
        assert len(data["intel"]) == 1


class TestReplaySummary:
    def test_summary_counts(self, session):
        now = _seed(session)
        start = now - timedelta(hours=1)
        end = now + timedelta(hours=1)

        summary = get_replay_summary(session, start, end)
        assert summary["detections"] == 1
        assert summary["telemetry"] == 1
        assert summary["intel"] == 1

    def test_summary_empty(self, session):
        now = datetime.now(UTC)
        summary = get_replay_summary(session, now - timedelta(hours=1), now + timedelta(hours=1))
        assert summary["detections"] == 0
        assert summary["telemetry"] == 0
        assert summary["intel"] == 0


def _fmt(dt: datetime) -> str:
    """Format datetime for query params (no timezone to avoid +00:00 URL encoding issues)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


class TestReplayAPI:
    def test_frame_with_event_filter(self, client):
        c, factory = client
        sess = factory()
        now = _seed(sess)
        sess.close()

        start = _fmt(now - timedelta(hours=1))
        end = _fmt(now + timedelta(hours=1))

        resp = c.get(f"/api/replay/frame?start={start}&end={end}&event_types=detections")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["detections"]) == 1
        assert len(data["telemetry"]) == 0
        assert "speed" in data
        assert "event_types" in data

    def test_frame_speed_parameter(self, client):
        c, factory = client
        sess = factory()
        now = _seed(sess)
        sess.close()

        start = _fmt(now - timedelta(hours=1))
        end = _fmt(now + timedelta(hours=1))

        resp = c.get(f"/api/replay/frame?start={start}&end={end}&speed=4.0")
        assert resp.status_code == 200
        assert resp.json()["speed"] == 4.0

    def test_summary_endpoint(self, client):
        c, factory = client
        sess = factory()
        now = _seed(sess)
        sess.close()

        start = _fmt(now - timedelta(hours=1))
        end = _fmt(now + timedelta(hours=1))

        resp = c.get(f"/api/replay/summary?start={start}&end={end}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["detections"] == 1
        assert data["telemetry"] == 1
        assert data["intel"] == 1
