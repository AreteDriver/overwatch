"""Ingest drone / sensor telemetry."""

from __future__ import annotations

import json
import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from overwatch.models import TelemetryIn, TelemetryRow

log = logging.getLogger(__name__)


def ingest_telemetry(session: Session, data: TelemetryIn) -> TelemetryRow | None:
    """Store a telemetry point. Returns None if duplicate source_id."""
    row = TelemetryRow(
        source_id=data.source_id,
        device_name=data.device_name,
        lat=data.lat,
        lon=data.lon,
        altitude=data.altitude,
        heading=data.heading,
        speed=data.speed,
        battery_pct=data.battery_pct,
        recorded_at=data.recorded_at,
        meta_json=json.dumps(data.meta),
    )
    session.add(row)
    try:
        session.commit()
        log.info("Ingested telemetry %s from %s", row.id, row.device_name)
        return row
    except IntegrityError:
        session.rollback()
        log.debug("Duplicate telemetry source_id=%s, skipping", data.source_id)
        return None


def ingest_telemetry_batch(session: Session, items: list[TelemetryIn]) -> list[TelemetryRow]:
    """Ingest a batch, skipping duplicates."""
    results = []
    for item in items:
        row = ingest_telemetry(session, item)
        if row:
            results.append(row)
    return results
