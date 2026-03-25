"""Smoke tests — full write path end-to-end."""

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
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
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


@pytest.mark.smoke
class TestFullWritePath:
    """Exercises the complete ingest -> resolve -> briefing pipeline."""

    def test_full_pipeline(self, client):
        now = datetime.now(UTC).isoformat()

        # 1. Ingest detections
        detections = [
            {
                "source_id": f"smoke-d-{i}",
                "label": "person",
                "confidence": 0.9,
                "lat": 46.05 + i * 0.001,
                "lon": 14.5,
                "detected_at": now,
            }
            for i in range(5)
        ]
        resp = client.post("/api/ingest/detections", json=detections)
        assert resp.status_code == 200
        assert len(resp.json()) == 5

        # 2. Ingest intel reports
        intel = [
            {
                "source_id": f"smoke-i-{i}",
                "title": f"General Smith spotted near Zone {i}",
                "summary": f"Commander Davis reported activity near Ljubljana sector {i}",
                "published_at": now,
                "tags": ["conflict", "movement"],
            }
            for i in range(3)
        ]
        resp = client.post("/api/ingest/intel/batch", json=intel)
        assert resp.status_code == 200
        assert len(resp.json()) == 3

        # 3. Ingest telemetry
        telemetry = [
            {
                "source_id": f"smoke-t-{i}",
                "device_name": f"drone-{chr(65 + i)}",
                "lat": 46.05 + i * 0.01,
                "lon": 14.5 + i * 0.01,
                "altitude": 100 + i * 20,
                "battery_pct": 90 - i * 25,
                "recorded_at": now,
            }
            for i in range(4)
        ]
        resp = client.post("/api/ingest/telemetry/batch", json=telemetry)
        assert resp.status_code == 200
        assert len(resp.json()) == 4

        # 4. Verify data persisted
        stats = client.get("/api/dashboard/stats").json()
        assert stats["total_detections"] == 5
        assert stats["total_intel_reports"] == 3
        assert stats["total_telemetry_points"] == 4

        # 5. Resolve entities
        resp = client.post("/api/entities/resolve")
        assert resp.status_code == 200
        entities = resp.json()
        assert len(entities) >= 1

        # 6. Verify entities persisted
        resp = client.get("/api/entities")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

        # 7. Generate briefing
        resp = client.post("/api/briefings/generate", params={"lookback_hours": 24})
        assert resp.status_code == 200
        briefing = resp.json()
        assert "SITREP" in briefing["title"]
        assert "person" in briefing["body"]

        # 8. Verify briefing accessible
        resp = client.get("/api/briefings/latest")
        assert resp.status_code == 200
        assert resp.json()["id"] == briefing["id"]

        # 9. Final stats
        final_stats = client.get("/api/dashboard/stats").json()
        assert final_stats["total_entities"] >= 1
        assert final_stats["total_briefings"] == 1

    def test_idempotent_ingest(self, client):
        """Verify duplicate ingestion is handled gracefully."""
        now = datetime.now(UTC).isoformat()
        payload = {
            "source_id": "smoke-idem-1",
            "label": "car",
            "confidence": 0.8,
            "detected_at": now,
        }

        resp1 = client.post("/api/ingest/detection", json=payload)
        assert resp1.status_code == 200

        resp2 = client.post("/api/ingest/detection", json=payload)
        assert resp2.status_code == 409

        stats = client.get("/api/dashboard/stats").json()
        assert stats["total_detections"] == 1

    def test_cross_source_entity_resolution(self, client):
        """Verify entities are correlated across detection + intel sources."""
        now = datetime.now(UTC).isoformat()

        client.post(
            "/api/ingest/detection",
            json={
                "source_id": "smoke-cross-d1",
                "label": "person",
                "confidence": 0.92,
                "lat": 46.05,
                "lon": 14.5,
                "detected_at": now,
            },
        )

        client.post(
            "/api/ingest/intel",
            json={
                "source_id": "smoke-cross-i1",
                "title": "President Novak visits Ljubljana",
                "summary": "Forces deployed near Ljubljana following visit",
                "published_at": now,
            },
        )

        resp = client.post("/api/entities/resolve")
        assert resp.status_code == 200
        entities = resp.json()

        types = {e["entity_type"] for e in entities}
        assert "person" in types
