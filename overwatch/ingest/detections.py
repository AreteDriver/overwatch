"""Ingest YOLO detection events."""

from __future__ import annotations

import json
import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from overwatch.models import DetectionIn, DetectionRow

log = logging.getLogger(__name__)


def ingest_detection(session: Session, data: DetectionIn) -> DetectionRow | None:
    """Store a detection. Returns None if duplicate source_id."""
    bbox = data.bbox or []
    row = DetectionRow(
        source_id=data.source_id,
        label=data.label,
        confidence=data.confidence,
        bbox_x=bbox[0] if len(bbox) > 0 else None,
        bbox_y=bbox[1] if len(bbox) > 1 else None,
        bbox_w=bbox[2] if len(bbox) > 2 else None,
        bbox_h=bbox[3] if len(bbox) > 3 else None,
        lat=data.lat,
        lon=data.lon,
        source_name=data.source_name,
        detected_at=data.detected_at,
        meta_json=json.dumps(data.meta),
    )
    session.add(row)
    try:
        session.commit()
        log.info("Ingested detection %s: %s (%.2f)", row.id, row.label, row.confidence)
        return row
    except IntegrityError:
        session.rollback()
        log.debug("Duplicate detection source_id=%s, skipping", data.source_id)
        return None


def ingest_detections_batch(session: Session, items: list[DetectionIn]) -> list[DetectionRow]:
    """Ingest a batch, skipping duplicates."""
    results = []
    for item in items:
        row = ingest_detection(session, item)
        if row:
            results.append(row)
    return results
