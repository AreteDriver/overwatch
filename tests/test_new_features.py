"""Tests for all v0.2.0 features."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from overwatch.analysis.alerts import (
    _point_in_polygon,
    check_detection_alerts,
    check_geofence_alerts,
    check_telemetry_alerts,
)
from overwatch.analysis.geofence import (
    create_geofence,
    delete_geofence,
    geofence_row_to_out,
    list_geofences,
)
from overwatch.analysis.mesh_health import get_device_health
from overwatch.analysis.replay import get_replay_frame, get_time_range
from overwatch.api.routes import _get_session, router
from overwatch.events import publish, subscribe, unsubscribe
from overwatch.models import (
    Base,
    DetectionRow,
    GeofenceIn,
    TelemetryRow,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_test_app():
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
    test_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    test_app.include_router(router, prefix="/api")

    def override_session():
        sess = factory()
        try:
            yield sess
        finally:
            sess.close()

    test_app.dependency_overrides[_get_session] = override_session
    return test_app, engine


@pytest.fixture()
def client():
    test_app, engine = _make_test_app()
    with TestClient(test_app) as c:
        yield c
    engine.dispose()


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


# ---------------------------------------------------------------------------
# Geofence tests
# ---------------------------------------------------------------------------


class TestGeofence:
    def test_create(self, session):
        data = GeofenceIn(
            name="TestZone",
            coords=[[46.0, 14.0], [46.1, 14.0], [46.1, 14.1], [46.0, 14.1]],
        )
        row = create_geofence(session, data)
        assert row.name == "TestZone"
        assert row.id is not None

    def test_list(self, session):
        create_geofence(
            session,
            GeofenceIn(
                name="Z1",
                coords=[[0, 0], [1, 0], [1, 1]],
            ),
        )
        result = list_geofences(session)
        assert len(result) == 1
        assert result[0]["name"] == "Z1"

    def test_delete(self, session):
        row = create_geofence(
            session,
            GeofenceIn(
                name="Del",
                coords=[[0, 0], [1, 0], [1, 1]],
            ),
        )
        assert delete_geofence(session, row.id)
        assert not delete_geofence(session, "nonexistent")

    def test_to_out(self, session):
        row = create_geofence(
            session,
            GeofenceIn(
                name="Out",
                coords=[[10, 20], [11, 20], [11, 21]],
            ),
        )
        out = geofence_row_to_out(row)
        assert out.name == "Out"
        assert len(out.coords) == 3


class TestGeofenceAPI:
    def test_crud(self, client):
        # Create
        resp = client.post(
            "/api/geofences",
            json={
                "name": "APIZone",
                "coords": [[46.0, 14.0], [46.1, 14.0], [46.1, 14.1]],
            },
        )
        assert resp.status_code == 200
        gf_id = resp.json()["id"]

        # List
        resp = client.get("/api/geofences")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

        # Delete
        resp = client.delete(f"/api/geofences/{gf_id}")
        assert resp.status_code == 200

        # Verify deleted
        resp = client.get("/api/geofences")
        assert len(resp.json()) == 0

    def test_delete_404(self, client):
        resp = client.delete("/api/geofences/nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Alert tests
# ---------------------------------------------------------------------------


class TestAlerts:
    def test_point_in_polygon_inside(self):
        poly = [[0, 0], [0, 10], [10, 10], [10, 0]]
        assert _point_in_polygon(5, 5, poly)

    def test_point_in_polygon_outside(self):
        poly = [[0, 0], [0, 10], [10, 10], [10, 0]]
        assert not _point_in_polygon(15, 15, poly)

    def test_point_in_polygon_too_few(self):
        assert not _point_in_polygon(5, 5, [[0, 0], [1, 1]])

    def test_high_confidence_alert(self, session, now):
        data = {
            "source_id": "alert-d1",
            "label": "person",
            "confidence": 0.95,
            "lat": 46.0,
            "lon": 14.5,
        }
        alerts = check_detection_alerts(session, data)
        assert len(alerts) == 1
        assert alerts[0].alert_type == "high_confidence"

    def test_no_alert_low_confidence(self, session):
        data = {
            "source_id": "alert-d2",
            "label": "car",
            "confidence": 0.5,
        }
        alerts = check_detection_alerts(session, data)
        assert len(alerts) == 0

    def test_low_battery_alert(self, session):
        data = {
            "source_id": "alert-t1",
            "device_name": "drone-x",
            "battery_pct": 10.0,
            "lat": 46.0,
            "lon": 14.5,
        }
        alerts = check_telemetry_alerts(session, data)
        assert len(alerts) == 1
        assert alerts[0].alert_type == "low_battery"
        assert alerts[0].severity == "critical"

    def test_no_battery_alert(self, session):
        data = {
            "source_id": "alert-t2",
            "device_name": "drone-y",
            "battery_pct": 80.0,
        }
        alerts = check_telemetry_alerts(session, data)
        assert len(alerts) == 0

    def test_geofence_alert(self, session):
        gfs = [
            {
                "id": "gf1",
                "name": "Restricted",
                "coords": [[45, 14], [45, 15], [47, 15], [47, 14]],
                "alert_on_enter": True,
            }
        ]
        alerts = check_geofence_alerts(session, 46.0, 14.5, "person", "gf-src", gfs)
        assert len(alerts) == 1
        assert "Restricted" in alerts[0].title


class TestAlertAPI:
    def test_get_alerts(self, client):
        now = datetime.now(UTC).isoformat()
        # Trigger an alert via high-confidence detection
        client.post(
            "/api/ingest/detection",
            json={
                "source_id": "alert-api-1",
                "label": "person",
                "confidence": 0.95,
                "lat": 46.0,
                "lon": 14.5,
                "detected_at": now,
            },
        )
        resp = client.get("/api/alerts")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_acknowledge_alert(self, client):
        now = datetime.now(UTC).isoformat()
        client.post(
            "/api/ingest/detection",
            json={
                "source_id": "alert-ack-1",
                "label": "drone",
                "confidence": 0.96,
                "detected_at": now,
            },
        )
        alerts = client.get("/api/alerts").json()
        if alerts:
            resp = client.post(f"/api/alerts/{alerts[0]['id']}/acknowledge")
            assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Mesh health tests
# ---------------------------------------------------------------------------


class TestMeshHealth:
    def test_device_health(self, session, now):
        session.add(
            TelemetryRow(
                source_id="mh-1",
                device_name="drone-a",
                lat=46.0,
                lon=14.5,
                battery_pct=80,
                recorded_at=now,
            )
        )
        session.add(
            TelemetryRow(
                source_id="mh-2",
                device_name="drone-b",
                lat=46.1,
                lon=14.6,
                battery_pct=10,
                recorded_at=now - timedelta(hours=1),
            )
        )
        session.commit()
        devices = get_device_health(session)
        assert len(devices) == 2
        names = [d.device_name for d in devices]
        assert "drone-a" in names
        assert "drone-b" in names

    def test_api(self, client):
        now = datetime.now(UTC).isoformat()
        client.post(
            "/api/ingest/telemetry",
            json={
                "source_id": "mh-api-1",
                "device_name": "sensor-1",
                "lat": 46.0,
                "lon": 14.5,
                "battery_pct": 50,
                "recorded_at": now,
            },
        )
        resp = client.get("/api/mesh/health")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1


# ---------------------------------------------------------------------------
# Replay tests
# ---------------------------------------------------------------------------


class TestReplay:
    def test_empty(self, session):
        result = get_time_range(session)
        assert result["earliest"] is None

    def test_with_data(self, session, now):
        session.add(
            DetectionRow(
                source_id="rp-d1",
                label="car",
                confidence=0.8,
                detected_at=now,
            )
        )
        session.commit()
        result = get_time_range(session)
        assert result["earliest"] is not None

    def test_frame(self, session, now):
        session.add(
            DetectionRow(
                source_id="rp-d2",
                label="person",
                confidence=0.9,
                detected_at=now,
            )
        )
        session.commit()
        frame = get_replay_frame(
            session,
            now - timedelta(hours=1),
            now + timedelta(hours=1),
        )
        assert len(frame["detections"]) == 1

    def test_api(self, client):
        resp = client.get("/api/replay/range")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Entity timeline tests
# ---------------------------------------------------------------------------


class TestEntityTimeline:
    def test_api(self, client):
        now = datetime.now(UTC).isoformat()
        # Ingest + resolve
        client.post(
            "/api/ingest/detection",
            json={
                "source_id": "et-d1",
                "label": "person",
                "confidence": 0.9,
                "lat": 46.0,
                "lon": 14.5,
                "detected_at": now,
            },
        )
        resp = client.post("/api/entities/resolve")
        entities = resp.json()
        if entities:
            eid = entities[0]["id"]
            resp = client.get(f"/api/entities/{eid}/timeline")
            assert resp.status_code == 200

    def test_404(self, client):
        resp = client.get("/api/entities/nonexistent/timeline")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Briefing export tests
# ---------------------------------------------------------------------------


class TestBriefingExport:
    def test_export(self, client):
        # Generate a briefing first
        client.post("/api/briefings/generate")
        latest = client.get("/api/briefings/latest").json()
        assert latest is not None

        resp = client.get(f"/api/briefings/{latest['id']}/export")
        assert resp.status_code == 200
        assert "text/markdown" in resp.headers["content-type"]
        assert "attachment" in resp.headers["content-disposition"]

    def test_export_404(self, client):
        resp = client.get("/api/briefings/nonexistent/export")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Event bus tests
# ---------------------------------------------------------------------------


class TestEventBus:
    def test_subscribe_publish(self):
        q = subscribe()
        publish("test", {"key": "value"})
        event = q.get_nowait()
        assert event["event"] == "test"
        assert event["data"]["key"] == "value"
        unsubscribe(q)

    def test_unsubscribe(self):
        q = subscribe()
        unsubscribe(q)
        publish("test", {"key": "value"})
        assert q.empty()


# ---------------------------------------------------------------------------
# Dashboard stats with new fields
# ---------------------------------------------------------------------------


class TestDashboardStatsV2:
    def test_includes_alerts_geofences(self, client):
        resp = client.get("/api/dashboard/stats")
        data = resp.json()
        assert "total_alerts" in data
        assert "total_geofences" in data


# ---------------------------------------------------------------------------
# Ollama briefing (fallback test — no Ollama running)
# ---------------------------------------------------------------------------


class TestOllamaBriefing:
    def test_fallback_to_template(self, client):
        resp = client.post(
            "/api/briefings/generate",
            params={"use_ollama": True},
        )
        assert resp.status_code == 200
        assert "SITREP" in resp.json()["title"]
