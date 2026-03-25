"""Tests for ingest adapters."""

from __future__ import annotations

from overwatch.ingest.detections import ingest_detection, ingest_detections_batch
from overwatch.ingest.intel import ingest_intel_batch, ingest_intel_report
from overwatch.ingest.telemetry import ingest_telemetry, ingest_telemetry_batch
from overwatch.models import (
    DetectionIn,
    IntelReportIn,
    TelemetryIn,
)


class TestDetectionIngest:
    def test_single(self, session, now):
        data = DetectionIn(
            source_id="det-100",
            label="person",
            confidence=0.92,
            bbox=[10, 20, 50, 80],
            lat=46.05,
            lon=14.5,
            detected_at=now,
        )
        row = ingest_detection(session, data)
        assert row is not None
        assert row.label == "person"
        assert row.bbox_x == 10
        assert row.bbox_w == 50

    def test_dedup(self, session, now):
        data = DetectionIn(
            source_id="det-dup",
            label="car",
            confidence=0.8,
            detected_at=now,
        )
        row1 = ingest_detection(session, data)
        row2 = ingest_detection(session, data)
        assert row1 is not None
        assert row2 is None

    def test_batch(self, session, now):
        items = [
            DetectionIn(source_id=f"batch-{i}", label="truck", confidence=0.7, detected_at=now)
            for i in range(5)
        ]
        results = ingest_detections_batch(session, items)
        assert len(results) == 5

    def test_batch_with_dups(self, session, now):
        items = [
            DetectionIn(source_id="dup-batch", label="bus", confidence=0.6, detected_at=now),
            DetectionIn(source_id="dup-batch", label="bus", confidence=0.6, detected_at=now),
        ]
        results = ingest_detections_batch(session, items)
        assert len(results) == 1

    def test_no_bbox(self, session, now):
        data = DetectionIn(
            source_id="no-bbox",
            label="drone",
            confidence=0.88,
            detected_at=now,
        )
        row = ingest_detection(session, data)
        assert row.bbox_x is None

    def test_meta_stored(self, session, now):
        data = DetectionIn(
            source_id="with-meta",
            label="person",
            confidence=0.9,
            detected_at=now,
            meta={"camera": "cam-north", "zone": "A"},
        )
        row = ingest_detection(session, data)
        assert "cam-north" in row.meta_json


class TestIntelIngest:
    def test_single(self, session, now):
        data = IntelReportIn(
            source_id="tw-100",
            title="Breaking: Major Event",
            summary="Something happened",
            published_at=now,
            tags=["conflict"],
        )
        row = ingest_intel_report(session, data)
        assert row is not None
        assert row.title == "Breaking: Major Event"
        assert "conflict" in row.tags_json

    def test_dedup(self, session, now):
        data = IntelReportIn(
            source_id="tw-dup",
            title="Dup",
            summary="Dup",
            published_at=now,
        )
        row1 = ingest_intel_report(session, data)
        row2 = ingest_intel_report(session, data)
        assert row1 is not None
        assert row2 is None

    def test_batch(self, session, now):
        items = [
            IntelReportIn(
                source_id=f"tw-b-{i}",
                title=f"Story {i}",
                summary=f"Summary {i}",
                published_at=now,
            )
            for i in range(3)
        ]
        results = ingest_intel_batch(session, items)
        assert len(results) == 3


class TestTelemetryIngest:
    def test_single(self, session, now):
        data = TelemetryIn(
            source_id="tel-100",
            device_name="drone-alpha",
            lat=46.05,
            lon=14.5,
            altitude=120.0,
            heading=270.0,
            speed=15.0,
            battery_pct=72.0,
            recorded_at=now,
        )
        row = ingest_telemetry(session, data)
        assert row is not None
        assert row.device_name == "drone-alpha"
        assert row.altitude == 120.0

    def test_dedup(self, session, now):
        data = TelemetryIn(
            source_id="tel-dup",
            device_name="drone-beta",
            lat=46.0,
            lon=14.5,
            recorded_at=now,
        )
        row1 = ingest_telemetry(session, data)
        row2 = ingest_telemetry(session, data)
        assert row1 is not None
        assert row2 is None

    def test_batch(self, session, now):
        items = [
            TelemetryIn(
                source_id=f"tel-b-{i}",
                device_name="drone-gamma",
                lat=46.0 + i * 0.01,
                lon=14.5,
                recorded_at=now,
            )
            for i in range(4)
        ]
        results = ingest_telemetry_batch(session, items)
        assert len(results) == 4

    def test_minimal_fields(self, session, now):
        data = TelemetryIn(
            source_id="tel-min",
            device_name="sensor-1",
            lat=46.0,
            lon=14.5,
            recorded_at=now,
        )
        row = ingest_telemetry(session, data)
        assert row.altitude is None
        assert row.battery_pct is None
