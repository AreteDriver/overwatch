"""Tests for bulk export endpoints (CSV / GeoJSON)."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from overwatch.api.routes import _get_session
from overwatch.app import app
from overwatch.models import Base, DetectionRow, IntelReportRow, TelemetryRow


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
        # Override AFTER lifespan runs (lifespan sets its own override)
        app.dependency_overrides[_get_session] = override_session
        app.state.session_factory = factory
        app.state.engine = engine
        yield c, factory

    app.dependency_overrides.clear()
    engine.dispose()


def _seed_data(factory):
    """Seed test data into all tables."""
    now = datetime.now(UTC)
    sess = factory()
    sess.add(
        DetectionRow(
            source_id="det-1",
            label="person",
            confidence=0.95,
            lat=46.05,
            lon=14.5,
            detected_at=now,
        )
    )
    sess.add(
        DetectionRow(
            source_id="det-2",
            label="vehicle",
            confidence=0.8,
            lat=46.06,
            lon=14.51,
            detected_at=now,
        )
    )
    sess.add(
        DetectionRow(
            source_id="det-3",
            label="person",
            confidence=0.7,
            lat=None,
            lon=None,
            detected_at=now,  # no coords
        )
    )
    sess.add(
        IntelReportRow(
            source_id="int-1",
            title="Report A",
            summary="Summary A",
            published_at=now,
        )
    )
    sess.add(
        IntelReportRow(
            source_id="int-2",
            title="Report B",
            summary="Summary B",
            published_at=now,
        )
    )
    sess.add(
        TelemetryRow(
            source_id="tel-1",
            device_name="drone-1",
            lat=46.05,
            lon=14.5,
            battery_pct=85.0,
            recorded_at=now,
        )
    )
    sess.commit()
    sess.close()


class TestDetectionExportCSV:
    def test_export_csv_returns_all_rows(self, client):
        c, factory = client
        _seed_data(factory)
        resp = c.get("/api/export/detections.csv")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "text/csv; charset=utf-8"
        reader = csv.reader(io.StringIO(resp.text))
        rows = list(reader)
        assert rows[0] == [
            "id",
            "source_id",
            "label",
            "confidence",
            "lat",
            "lon",
            "source_name",
            "detected_at",
            "created_at",
        ]
        assert len(rows) == 4  # header + 3 data rows

    def test_export_csv_filter_by_label(self, client):
        c, factory = client
        _seed_data(factory)
        resp = c.get("/api/export/detections.csv?label=person")
        assert resp.status_code == 200
        reader = csv.reader(io.StringIO(resp.text))
        rows = list(reader)
        assert len(rows) == 3  # header + 2 person rows

    def test_export_csv_empty(self, client):
        c, _ = client
        resp = c.get("/api/export/detections.csv")
        assert resp.status_code == 200
        reader = csv.reader(io.StringIO(resp.text))
        rows = list(reader)
        assert len(rows) == 1  # header only


class TestDetectionExportGeoJSON:
    def test_export_geojson_excludes_null_coords(self, client):
        c, factory = client
        _seed_data(factory)
        resp = c.get("/api/export/detections.geojson")
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "FeatureCollection"
        assert len(data["features"]) == 2  # det-3 excluded (no coords)

    def test_export_geojson_structure(self, client):
        c, factory = client
        _seed_data(factory)
        resp = c.get("/api/export/detections.geojson")
        feature = resp.json()["features"][0]
        assert feature["type"] == "Feature"
        assert feature["geometry"]["type"] == "Point"
        assert len(feature["geometry"]["coordinates"]) == 2
        assert "label" in feature["properties"]
        assert "confidence" in feature["properties"]

    def test_export_geojson_filter_by_label(self, client):
        c, factory = client
        _seed_data(factory)
        resp = c.get("/api/export/detections.geojson?label=vehicle")
        data = resp.json()
        assert len(data["features"]) == 1
        assert data["features"][0]["properties"]["label"] == "vehicle"


class TestIntelExportCSV:
    def test_export_intel_csv(self, client):
        c, factory = client
        _seed_data(factory)
        resp = c.get("/api/export/intel.csv")
        assert resp.status_code == 200
        reader = csv.reader(io.StringIO(resp.text))
        rows = list(reader)
        assert len(rows) == 3  # header + 2 reports


class TestTelemetryExport:
    def test_export_telemetry_csv(self, client):
        c, factory = client
        _seed_data(factory)
        resp = c.get("/api/export/telemetry.csv")
        assert resp.status_code == 200
        reader = csv.reader(io.StringIO(resp.text))
        rows = list(reader)
        assert len(rows) == 2  # header + 1 reading

    def test_export_telemetry_geojson(self, client):
        c, factory = client
        _seed_data(factory)
        resp = c.get("/api/export/telemetry.geojson")
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "FeatureCollection"
        assert len(data["features"]) == 1
        props = data["features"][0]["properties"]
        assert props["device_name"] == "drone-1"
        assert props["battery_pct"] == 85.0

    def test_export_telemetry_csv_filter_device(self, client):
        c, factory = client
        _seed_data(factory)
        resp = c.get("/api/export/telemetry.csv?device=nonexistent")
        reader = csv.reader(io.StringIO(resp.text))
        rows = list(reader)
        assert len(rows) == 1  # header only


class TestAdminPurge:
    def test_purge_endpoint(self, client):
        c, factory = client
        _seed_data(factory)
        resp = c.post("/api/admin/purge?retention_days=1")
        assert resp.status_code == 200
        data = resp.json()
        assert "purged" in data
        assert data["retention_days"] == 1

    def test_purge_rejects_zero_days(self, client):
        c, _ = client
        resp = c.post("/api/admin/purge?retention_days=0")
        assert resp.status_code == 422


class TestEnrichedHealth:
    def test_health_returns_counts(self, client):
        c, factory = client
        _seed_data(factory)
        resp = c.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["version"] == "0.3.0"
        assert data["detections"] == 3
        assert data["intel_reports"] == 2
        assert data["telemetry_points"] == 1
        assert "ws_connections" in data
        assert "retention_days" in data

    def test_health_empty_db(self, client):
        c, _ = client
        resp = c.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["detections"] == 0
