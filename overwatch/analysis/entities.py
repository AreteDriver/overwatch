"""Entity extraction and cross-source resolution.

This is a lightweight rule-based implementation. For production, replace with
Dossier's NER + entity resolver which provides:
  - 4+ NER entity types with ML-backed extraction
  - Fuzzy matching with configurable thresholds
  - Dynamic gazetteer loading
  - Cross-document entity consolidation
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from difflib import SequenceMatcher

from sqlalchemy import desc
from sqlalchemy.orm import Session

from overwatch.config import ENTITY_FUZZY_THRESHOLD
from overwatch.models import (
    DetectionRow,
    EntityRow,
    IntelReportRow,
)

log = logging.getLogger(__name__)

# Common YOLO classes that map to entity types
LABEL_TYPE_MAP: dict[str, str] = {
    "person": "person",
    "car": "vehicle",
    "truck": "vehicle",
    "bus": "vehicle",
    "motorcycle": "vehicle",
    "bicycle": "vehicle",
    "boat": "vehicle",
    "airplane": "vehicle",
    "drone": "vehicle",
}

# Simple named entity patterns for intel text
_PERSON_RE = re.compile(
    r"\b(?:President|General|Commander|Minister|Dr\.|Col\.)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b"
)
_LOCATION_RE = re.compile(r"\b(?:in|near|at|from)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b")
_ORG_RE = re.compile(
    r"\b([A-Z]{2,}(?:\s+[A-Z][a-z]+)*)\b"  # e.g. NATO, UN Forces
)


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _find_or_create_entity(
    session: Session,
    name: str,
    entity_type: str,
    timestamp: datetime,
    source_id: str,
) -> EntityRow:
    """Find an existing entity by fuzzy match or create a new one."""
    existing = session.query(EntityRow).filter(EntityRow.entity_type == entity_type).all()
    for entity in existing:
        if _similarity(entity.canonical_name, name) >= ENTITY_FUZZY_THRESHOLD:
            # Update existing entity
            entity.last_seen = max(entity.last_seen, timestamp)
            entity.sighting_count = (entity.sighting_count or 0) + 1
            source_ids = json.loads(entity.source_ids_json or "[]")
            if source_id not in source_ids:
                source_ids.append(source_id)
                entity.source_ids_json = json.dumps(source_ids)
            aliases = json.loads(entity.aliases_json or "[]")
            if name.lower() != entity.canonical_name.lower() and name not in aliases:
                aliases.append(name)
                entity.aliases_json = json.dumps(aliases)
            session.commit()
            log.debug("Merged '%s' into entity '%s'", name, entity.canonical_name)
            return entity

    # Create new entity
    entity = EntityRow(
        canonical_name=name,
        entity_type=entity_type,
        first_seen=timestamp,
        last_seen=timestamp,
        sighting_count=1,
        source_ids_json=json.dumps([source_id]),
    )
    session.add(entity)
    session.commit()
    log.info("Created entity '%s' (type=%s)", name, entity_type)
    return entity


def extract_entities_from_detections(session: Session, limit: int = 100) -> list[EntityRow]:
    """Extract entities from recent YOLO detections."""
    detections = (
        session.query(DetectionRow).order_by(desc(DetectionRow.created_at)).limit(limit).all()
    )
    entities: list[EntityRow] = []
    for det in detections:
        entity_type = LABEL_TYPE_MAP.get(det.label.lower())
        if not entity_type:
            continue
        name = f"{det.label}@{det.lat:.4f},{det.lon:.4f}" if det.lat and det.lon else det.label
        entity = _find_or_create_entity(session, name, entity_type, det.detected_at, det.source_id)
        entities.append(entity)
    return entities


def extract_entities_from_intel(session: Session, limit: int = 50) -> list[EntityRow]:
    """Extract named entities from recent intel reports using regex patterns.

    For production, replace with Dossier NER (4 entity types, ML-backed).
    """
    reports = (
        session.query(IntelReportRow).order_by(desc(IntelReportRow.created_at)).limit(limit).all()
    )
    entities: list[EntityRow] = []
    for report in reports:
        text = f"{report.title} {report.summary} {report.body}"

        for match in _PERSON_RE.finditer(text):
            entity = _find_or_create_entity(
                session, match.group(1), "person", report.published_at, report.source_id
            )
            entities.append(entity)

        for match in _LOCATION_RE.finditer(text):
            name = match.group(1)
            if len(name) > 3:  # skip short fragments
                entity = _find_or_create_entity(
                    session, name, "location", report.published_at, report.source_id
                )
                entities.append(entity)

    return entities


def resolve_all_entities(session: Session) -> list[EntityRow]:
    """Run full entity extraction from all sources."""
    det_entities = extract_entities_from_detections(session)
    intel_entities = extract_entities_from_intel(session)
    all_entities = det_entities + intel_entities
    log.info(
        "Resolved %d entities (%d from detections, %d from intel)",
        len(all_entities),
        len(det_entities),
        len(intel_entities),
    )
    return all_entities
