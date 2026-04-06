"""Tests for data retention / auto-purge."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from overwatch.models import AlertRow, BriefingRow, DetectionRow, IntelReportRow, TelemetryRow
from overwatch.retention import purge_old_records


def _make_detection(session, source_id, created_at):
    row = DetectionRow(
        source_id=source_id,
        label="person",
        confidence=0.9,
        detected_at=created_at,
        created_at=created_at,
    )
    session.add(row)
    session.commit()
    return row


def _make_intel(session, source_id, created_at):
    row = IntelReportRow(
        source_id=source_id,
        title="Test",
        summary="Test summary",
        published_at=created_at,
        created_at=created_at,
    )
    session.add(row)
    session.commit()
    return row


def _make_telemetry(session, source_id, created_at):
    row = TelemetryRow(
        source_id=source_id,
        device_name="drone-1",
        lat=46.0,
        lon=14.0,
        recorded_at=created_at,
        created_at=created_at,
    )
    session.add(row)
    session.commit()
    return row


def _make_alert(session, created_at):
    row = AlertRow(
        alert_type="test",
        severity="info",
        title="Test alert",
        created_at=created_at,
    )
    session.add(row)
    session.commit()
    return row


def _make_briefing(session, created_at):
    row = BriefingRow(
        title="SITREP",
        body="Test briefing",
        period_start=created_at,
        period_end=created_at,
        created_at=created_at,
    )
    session.add(row)
    session.commit()
    return row


class TestPurgeOldRecords:
    def test_purge_removes_old_records(self, session):
        now = datetime.now(UTC)
        old = now - timedelta(days=60)

        _make_detection(session, "det-old", old)
        _make_detection(session, "det-new", now)
        _make_intel(session, "int-old", old)
        _make_intel(session, "int-new", now)
        _make_telemetry(session, "tel-old", old)
        _make_telemetry(session, "tel-new", now)
        _make_alert(session, old)
        _make_alert(session, now)
        _make_briefing(session, old)
        _make_briefing(session, now)

        results = purge_old_records(session, retention_days=30)

        assert results["detections"] == 1
        assert results["intel_reports"] == 1
        assert results["telemetry"] == 1
        assert results["alerts"] == 1
        assert results["briefings"] == 1

        # New records still exist
        assert session.query(DetectionRow).count() == 1
        assert session.query(IntelReportRow).count() == 1
        assert session.query(TelemetryRow).count() == 1
        assert session.query(AlertRow).count() == 1
        assert session.query(BriefingRow).count() == 1

    def test_purge_zero_days_keeps_everything(self, session):
        now = datetime.now(UTC)
        old = now - timedelta(days=365)
        _make_detection(session, "det-ancient", old)

        results = purge_old_records(session, retention_days=0)

        assert results == {}
        assert session.query(DetectionRow).count() == 1

    def test_purge_nothing_to_purge(self, session):
        now = datetime.now(UTC)
        _make_detection(session, "det-fresh", now)

        results = purge_old_records(session, retention_days=30)

        assert results["detections"] == 0
        assert session.query(DetectionRow).count() == 1

    def test_purge_boundary_exact_cutoff(self, session):
        now = datetime.now(UTC)
        exactly_30 = now - timedelta(days=30, seconds=1)
        just_under_30 = now - timedelta(days=29, hours=23)

        _make_detection(session, "det-over", exactly_30)
        _make_detection(session, "det-under", just_under_30)

        results = purge_old_records(session, retention_days=30)

        assert results["detections"] == 1
        assert session.query(DetectionRow).count() == 1
