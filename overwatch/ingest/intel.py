"""Ingest OSINT intel reports (TheWire-STT format)."""

from __future__ import annotations

import json
import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from overwatch.models import IntelReportIn, IntelReportRow

log = logging.getLogger(__name__)


def ingest_intel_report(session: Session, data: IntelReportIn) -> IntelReportRow | None:
    """Store an intel report. Returns None if duplicate source_id."""
    row = IntelReportRow(
        source_id=data.source_id,
        title=data.title,
        summary=data.summary,
        body=data.body,
        source_name=data.source_name,
        source_url=data.source_url,
        published_at=data.published_at,
        tags_json=json.dumps(data.tags),
    )
    session.add(row)
    try:
        session.commit()
        log.info("Ingested intel report %s: %s", row.id, row.title[:60])
        return row
    except IntegrityError:
        session.rollback()
        log.debug("Duplicate intel source_id=%s, skipping", data.source_id)
        return None


def ingest_intel_batch(session: Session, items: list[IntelReportIn]) -> list[IntelReportRow]:
    """Ingest a batch, skipping duplicates."""
    results = []
    for item in items:
        row = ingest_intel_report(session, item)
        if row:
            results.append(row)
    return results
