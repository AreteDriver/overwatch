"""Tests for data models and schemas."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from overwatch.models import (
    BriefingRow,
    DashboardStats,
    DetectionIn,
    DetectionOut,
    DetectionRow,
    EntityRow,
    IntelReportIn,
    IntelReportOut,
    IntelReportRow,
    TelemetryIn,
    TelemetryOut,
    TelemetryRow,
)


class TestDetectionIn:
    def test_valid(self):
        d = DetectionIn(
            source_id="det-001",
            label="person",
            confidence=0.95,
            bbox=[10, 20, 50, 80],
            lat=46.05,
            lon=14.5,
            detected_at=datetime.now(UTC),
        )
        assert d.label == "person"
        assert d.confidence == 0.95
        assert d.bbox == [10, 20, 50, 80]

    def test_confidence_bounds(self):
        with pytest.raises(Exception):
            DetectionIn(
                source_id="x",
                label="car",
                confidence=1.5,
                detected_at=datetime.now(UTC),
            )

    def test_defaults(self):
        d = DetectionIn(
            source_id="det-002",
            label="truck",
            confidence=0.5,
            detected_at=datetime.now(UTC),
        )
        assert d.bbox is None
        assert d.lat is None
        assert d.source_name == "yolo"
        assert d.meta == {}


class TestIntelReportIn:
    def test_valid(self):
        r = IntelReportIn(
            source_id="tw-001",
            title="Breaking News",
            summary="Summary here",
            published_at=datetime.now(UTC),
        )
        assert r.source_name == "thewire"
        assert r.tags == []

    def test_with_tags(self):
        r = IntelReportIn(
            source_id="tw-002",
            title="Report",
            summary="Sum",
            published_at=datetime.now(UTC),
            tags=["conflict", "europe"],
        )
        assert len(r.tags) == 2


class TestTelemetryIn:
    def test_valid(self):
        t = TelemetryIn(
            source_id="tel-001",
            device_name="drone-alpha",
            lat=46.0,
            lon=14.5,
            altitude=120.0,
            battery_pct=85.0,
            recorded_at=datetime.now(UTC),
        )
        assert t.device_name == "drone-alpha"


class TestOrmModels:
    def test_detection_row_defaults(self, session, now):
        row = DetectionRow(
            source_id="d-1",
            label="person",
            confidence=0.9,
            detected_at=now,
        )
        session.add(row)
        session.commit()
        assert row.id is not None
        assert row.created_at is not None

    def test_intel_row(self, session, now):
        row = IntelReportRow(
            source_id="i-1",
            title="Test",
            summary="Test summary",
            published_at=now,
        )
        session.add(row)
        session.commit()
        assert row.id is not None

    def test_entity_row(self, session, now):
        row = EntityRow(
            canonical_name="John Doe",
            entity_type="person",
            first_seen=now,
            last_seen=now,
        )
        session.add(row)
        session.commit()
        assert row.sighting_count == 1

    def test_briefing_row(self, session, now):
        row = BriefingRow(
            title="SITREP",
            body="Test briefing body",
            period_start=now,
            period_end=now,
        )
        session.add(row)
        session.commit()
        assert row.id is not None


class TestOutputSchemas:
    def test_detection_out_from_orm(self, session, now):
        row = DetectionRow(
            source_id="do-1",
            label="car",
            confidence=0.8,
            detected_at=now,
        )
        session.add(row)
        session.commit()
        out = DetectionOut.model_validate(row)
        assert out.label == "car"

    def test_intel_out_from_orm(self, session, now):
        row = IntelReportRow(
            source_id="io-1",
            title="Test",
            summary="Summary",
            published_at=now,
        )
        session.add(row)
        session.commit()
        out = IntelReportOut.model_validate(row)
        assert out.title == "Test"

    def test_telemetry_out_from_orm(self, session, now):
        row = TelemetryRow(
            source_id="to-1",
            device_name="drone-1",
            lat=46.0,
            lon=14.5,
            recorded_at=now,
        )
        session.add(row)
        session.commit()
        out = TelemetryOut.model_validate(row)
        assert out.device_name == "drone-1"


class TestDashboardStats:
    def test_all_none(self):
        s = DashboardStats(
            total_detections=0,
            total_intel_reports=0,
            total_telemetry_points=0,
            total_entities=0,
            total_briefings=0,
            latest_detection=None,
            latest_intel=None,
        )
        assert s.total_detections == 0
