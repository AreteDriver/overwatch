"""Tests for entity resolution."""

from __future__ import annotations

from overwatch.analysis.entities import (
    _similarity,
    extract_entities_from_detections,
    extract_entities_from_intel,
    resolve_all_entities,
)
from overwatch.models import DetectionRow, IntelReportRow


class TestSimilarity:
    def test_identical(self):
        assert _similarity("hello", "hello") == 1.0

    def test_different(self):
        assert _similarity("abc", "xyz") < 0.5

    def test_case_insensitive(self):
        assert _similarity("John Doe", "john doe") == 1.0

    def test_partial_match(self):
        score = _similarity("John Smith", "John Smyth")
        assert 0.7 < score < 1.0


class TestDetectionEntities:
    def test_person_detection(self, session, now):
        session.add(
            DetectionRow(
                source_id="e-d1",
                label="person",
                confidence=0.9,
                lat=46.05,
                lon=14.5,
                detected_at=now,
            )
        )
        session.commit()
        entities = extract_entities_from_detections(session)
        assert len(entities) == 1
        assert entities[0].entity_type == "person"

    def test_vehicle_detection(self, session, now):
        session.add(
            DetectionRow(
                source_id="e-d2",
                label="car",
                confidence=0.85,
                lat=46.05,
                lon=14.5,
                detected_at=now,
            )
        )
        session.commit()
        entities = extract_entities_from_detections(session)
        assert len(entities) == 1
        assert entities[0].entity_type == "vehicle"

    def test_unknown_label_skipped(self, session, now):
        session.add(
            DetectionRow(
                source_id="e-d3",
                label="backpack",
                confidence=0.9,
                lat=46.05,
                lon=14.5,
                detected_at=now,
            )
        )
        session.commit()
        entities = extract_entities_from_detections(session)
        assert len(entities) == 0

    def test_no_location_still_creates_entity(self, session, now):
        session.add(
            DetectionRow(
                source_id="e-d4",
                label="truck",
                confidence=0.9,
                detected_at=now,
            )
        )
        session.commit()
        entities = extract_entities_from_detections(session)
        assert len(entities) == 1
        assert entities[0].canonical_name == "truck"

    def test_merge_similar_detections(self, session, now):
        for i in range(3):
            session.add(
                DetectionRow(
                    source_id=f"e-merge-{i}",
                    label="person",
                    confidence=0.9,
                    lat=46.0500,
                    lon=14.5000,
                    detected_at=now,
                )
            )
        session.commit()
        entities = extract_entities_from_detections(session)
        # Same location = same entity name, should merge
        unique_ids = {e.id for e in entities}
        assert len(unique_ids) == 1


class TestIntelEntities:
    def test_person_extraction(self, session, now):
        session.add(
            IntelReportRow(
                source_id="e-i1",
                title="General Smith addresses troops",
                summary="Commander Davis leads operation near Kyiv",
                published_at=now,
            )
        )
        session.commit()
        entities = extract_entities_from_intel(session)
        names = [e.canonical_name for e in entities]
        assert any("Smith" in n for n in names)

    def test_location_extraction(self, session, now):
        session.add(
            IntelReportRow(
                source_id="e-i2",
                title="Attack near Mariupol",
                summary="Forces moving from Kherson to the front",
                published_at=now,
            )
        )
        session.commit()
        entities = extract_entities_from_intel(session)
        types = [e.entity_type for e in entities]
        assert "location" in types

    def test_empty_report(self, session, now):
        session.add(
            IntelReportRow(
                source_id="e-i3",
                title="no entities here",
                summary="nothing notable",
                published_at=now,
            )
        )
        session.commit()
        entities = extract_entities_from_intel(session)
        assert len(entities) == 0


class TestResolveAll:
    def test_combined(self, session, now):
        session.add(
            DetectionRow(
                source_id="ra-d1",
                label="person",
                confidence=0.9,
                lat=46.0,
                lon=14.5,
                detected_at=now,
            )
        )
        session.add(
            IntelReportRow(
                source_id="ra-i1",
                title="President Novak visits border",
                summary="Forces positioned near Ljubljana",
                published_at=now,
            )
        )
        session.commit()
        entities = resolve_all_entities(session)
        assert len(entities) >= 2
