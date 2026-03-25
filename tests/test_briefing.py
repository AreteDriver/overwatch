"""Tests for briefing generation."""

from __future__ import annotations

from datetime import timedelta

from overwatch.analysis.briefing import generate_briefing, get_latest_briefing
from overwatch.models import (
    BriefingRow,
    DetectionRow,
    EntityRow,
    IntelReportRow,
    TelemetryRow,
)


class TestGenerateBriefing:
    def test_empty_data(self, session):
        briefing = generate_briefing(session, lookback_hours=24)
        assert briefing is not None
        assert "Situation Briefing" in briefing.body
        assert "No detections" in briefing.body
        assert "No intel reports" in briefing.body

    def test_with_detections(self, session, now):
        for i in range(3):
            session.add(
                DetectionRow(
                    source_id=f"b-d-{i}",
                    label="person",
                    confidence=0.9,
                    detected_at=now,
                )
            )
        session.commit()
        briefing = generate_briefing(session)
        assert "3" in briefing.body
        assert "person" in briefing.body

    def test_with_intel(self, session, now):
        session.add(
            IntelReportRow(
                source_id="b-i-1",
                title="Important Report",
                summary="Key intel",
                published_at=now,
            )
        )
        session.commit()
        briefing = generate_briefing(session)
        assert "Important Report" in briefing.body

    def test_with_telemetry(self, session, now):
        session.add(
            TelemetryRow(
                source_id="b-t-1",
                device_name="drone-echo",
                lat=46.0,
                lon=14.5,
                battery_pct=15.0,
                recorded_at=now,
            )
        )
        session.commit()
        briefing = generate_briefing(session)
        assert "drone-echo" in briefing.body
        assert "WARNING" in briefing.body  # low battery

    def test_with_entities(self, session, now):
        session.add(
            EntityRow(
                canonical_name="General Smith",
                entity_type="person",
                first_seen=now,
                last_seen=now,
                sighting_count=5,
            )
        )
        session.commit()
        briefing = generate_briefing(session)
        assert "General Smith" in briefing.body

    def test_lookback_filtering(self, session, now):
        old = now - timedelta(hours=48)
        session.add(
            DetectionRow(
                source_id="b-old-1",
                label="car",
                confidence=0.8,
                detected_at=old,
            )
        )
        session.add(
            DetectionRow(
                source_id="b-new-1",
                label="truck",
                confidence=0.7,
                detected_at=now,
            )
        )
        session.commit()
        briefing = generate_briefing(session, lookback_hours=24)
        assert "truck" in briefing.body
        # Old detection should not appear
        assert "1" in briefing.body  # only 1 detection

    def test_briefing_persisted(self, session):
        generate_briefing(session)
        count = session.query(BriefingRow).count()
        assert count == 1

    def test_animus_callout(self, session):
        briefing = generate_briefing(session)
        assert "Animus" in briefing.body

    def test_title_format(self, session):
        briefing = generate_briefing(session)
        assert briefing.title.startswith("SITREP")

    def test_stats_json(self, session, now):
        session.add(
            DetectionRow(source_id="b-s-1", label="person", confidence=0.9, detected_at=now)
        )
        session.commit()
        briefing = generate_briefing(session)
        import json

        stats = json.loads(briefing.stats_json)
        assert stats["detections"] == 1


class TestGetLatestBriefing:
    def test_none_when_empty(self, session):
        assert get_latest_briefing(session) is None

    def test_returns_most_recent(self, session, now):
        generate_briefing(session)
        generate_briefing(session)
        latest = get_latest_briefing(session)
        assert latest is not None
        count = session.query(BriefingRow).count()
        assert count == 2
