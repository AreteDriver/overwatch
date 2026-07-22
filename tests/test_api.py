"""Tests for FastAPI endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest


@pytest.fixture()
def now_str():
    return datetime.now(UTC).isoformat()


class TestDetectionEndpoints:
    def test_post_detection(self, client, now_str):
        resp = client.post(
            "/api/ingest/detection",
            json={
                "source_id": "api-d1",
                "label": "person",
                "confidence": 0.9,
                "lat": 46.05,
                "lon": 14.5,
                "detected_at": now_str,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["label"] == "person"
        assert data["id"] is not None

    def test_duplicate_409(self, client, now_str):
        payload = {
            "source_id": "api-dup",
            "label": "car",
            "confidence": 0.8,
            "detected_at": now_str,
        }
        resp1 = client.post("/api/ingest/detection", json=payload)
        assert resp1.status_code == 200
        resp2 = client.post("/api/ingest/detection", json=payload)
        assert resp2.status_code == 409

    def test_batch(self, client, now_str):
        items = [
            {
                "source_id": f"api-batch-{i}",
                "label": "truck",
                "confidence": 0.7,
                "detected_at": now_str,
            }
            for i in range(3)
        ]
        resp = client.post("/api/ingest/detections", json=items)
        assert resp.status_code == 200
        assert len(resp.json()) == 3

    def test_get_detections(self, client, now_str):
        client.post(
            "/api/ingest/detection",
            json={
                "source_id": "api-g1",
                "label": "boat",
                "confidence": 0.6,
                "detected_at": now_str,
            },
        )
        resp = client.get("/api/detections")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_get_detections_filter(self, client, now_str):
        client.post(
            "/api/ingest/detection",
            json={
                "source_id": "api-f1",
                "label": "motorcycle",
                "confidence": 0.7,
                "detected_at": now_str,
            },
        )
        client.post(
            "/api/ingest/detection",
            json={"source_id": "api-f2", "label": "bus", "confidence": 0.8, "detected_at": now_str},
        )
        resp = client.get("/api/detections", params={"label": "motorcycle"})
        assert resp.status_code == 200
        data = resp.json()
        assert all(d["label"] == "motorcycle" for d in data)


class TestIntelEndpoints:
    def test_post_intel(self, client, now_str):
        resp = client.post(
            "/api/ingest/intel",
            json={
                "source_id": "api-i1",
                "title": "Breaking News",
                "summary": "Major event",
                "published_at": now_str,
                "tags": ["conflict"],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Breaking News"

    def test_intel_batch(self, client, now_str):
        items = [
            {
                "source_id": f"api-ib-{i}",
                "title": f"Story {i}",
                "summary": f"Sum {i}",
                "published_at": now_str,
            }
            for i in range(2)
        ]
        resp = client.post("/api/ingest/intel/batch", json=items)
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_get_intel(self, client, now_str):
        client.post(
            "/api/ingest/intel",
            json={"source_id": "api-ig1", "title": "T", "summary": "S", "published_at": now_str},
        )
        resp = client.get("/api/intel")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1


class TestTelemetryEndpoints:
    def test_post_telemetry(self, client, now_str):
        resp = client.post(
            "/api/ingest/telemetry",
            json={
                "source_id": "api-t1",
                "device_name": "drone-alpha",
                "lat": 46.05,
                "lon": 14.5,
                "altitude": 120.0,
                "battery_pct": 80.0,
                "recorded_at": now_str,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["device_name"] == "drone-alpha"

    def test_telemetry_batch(self, client, now_str):
        items = [
            {
                "source_id": f"api-tb-{i}",
                "device_name": "d1",
                "lat": 46.0,
                "lon": 14.5,
                "recorded_at": now_str,
            }
            for i in range(2)
        ]
        resp = client.post("/api/ingest/telemetry/batch", json=items)
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_get_telemetry_filter(self, client, now_str):
        client.post(
            "/api/ingest/telemetry",
            json={
                "source_id": "api-tf1",
                "device_name": "alpha",
                "lat": 46.0,
                "lon": 14.5,
                "recorded_at": now_str,
            },
        )
        client.post(
            "/api/ingest/telemetry",
            json={
                "source_id": "api-tf2",
                "device_name": "beta",
                "lat": 46.0,
                "lon": 14.5,
                "recorded_at": now_str,
            },
        )
        resp = client.get("/api/telemetry", params={"device": "alpha"})
        assert resp.status_code == 200
        assert all(t["device_name"] == "alpha" for t in resp.json())


class TestBriefingEndpoints:
    def test_generate(self, client):
        resp = client.post("/api/briefings/generate", params={"lookback_hours": 24})
        assert resp.status_code == 200
        assert "SITREP" in resp.json()["title"]

    def test_latest_empty(self, client):
        resp = client.get("/api/briefings/latest")
        assert resp.status_code == 200

    def test_list(self, client):
        client.post("/api/briefings/generate")
        resp = client.get("/api/briefings")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1


class TestEntityEndpoints:
    def test_resolve_empty(self, client):
        resp = client.post("/api/entities/resolve")
        assert resp.status_code == 200

    def test_resolve_with_data(self, client, now_str):
        client.post(
            "/api/ingest/detection",
            json={
                "source_id": "ent-d1",
                "label": "person",
                "confidence": 0.9,
                "lat": 46.0,
                "lon": 14.5,
                "detected_at": now_str,
            },
        )
        resp = client.post("/api/entities/resolve")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_get_entities(self, client, now_str):
        client.post(
            "/api/ingest/detection",
            json={
                "source_id": "ent-g1",
                "label": "car",
                "confidence": 0.8,
                "lat": 46.0,
                "lon": 14.5,
                "detected_at": now_str,
            },
        )
        client.post("/api/entities/resolve")
        resp = client.get("/api/entities")
        assert resp.status_code == 200


class TestDashboardStats:
    def test_empty(self, client):
        resp = client.get("/api/dashboard/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_detections"] == 0
        assert data["latest_detection"] is None

    def test_with_data(self, client, now_str):
        client.post(
            "/api/ingest/detection",
            json={
                "source_id": "stat-1",
                "label": "person",
                "confidence": 0.9,
                "detected_at": now_str,
            },
        )
        resp = client.get("/api/dashboard/stats")
        data = resp.json()
        assert data["total_detections"] == 1
        assert data["latest_detection"] is not None
