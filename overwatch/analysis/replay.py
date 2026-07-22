"""Replay mode — time-windowed data retrieval for post-mission review."""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from overwatch.models import (
    DetectionOut,
    DetectionRow,
    IntelReportOut,
    IntelReportRow,
    TelemetryOut,
    TelemetryRow,
)

log = logging.getLogger(__name__)

# Valid event type tokens for filtering
VALID_EVENT_TYPES = {"detections", "telemetry", "intel"}

# Safety cap to prevent unbounded queries from exhausting memory
MAX_REPLAY_RECORDS = 5000


def parse_event_types(raw: str | None) -> set[str]:
    """Parse comma-separated event type string into a validated set.

    Returns all types when *raw* is None or empty.
    """
    if not raw:
        return VALID_EVENT_TYPES
    requested = {t.strip().lower() for t in raw.split(",") if t.strip()}
    valid = requested & VALID_EVENT_TYPES
    return valid if valid else VALID_EVENT_TYPES


def get_replay_frame(
    session: Session,
    start: datetime,
    end: datetime,
    event_types: set[str] | None = None,
) -> dict:
    """Get detections, telemetry, and intel within a time window.

    *event_types* controls which categories are queried.  ``None`` means all.
    """
    types = event_types if event_types else VALID_EVENT_TYPES

    detections: list[DetectionOut] = []
    telemetry: list[TelemetryOut] = []
    intel: list[IntelReportOut] = []

    if "detections" in types:
        rows = (
            session.query(DetectionRow)
            .filter(
                and_(
                    DetectionRow.detected_at >= start,
                    DetectionRow.detected_at <= end,
                )
            )
            .limit(MAX_REPLAY_RECORDS)
            .all()
        )
        if len(rows) == MAX_REPLAY_RECORDS:
            log.warning("Replay detection query capped at %d records", MAX_REPLAY_RECORDS)
        detections = [DetectionOut.model_validate(d) for d in rows]

    if "telemetry" in types:
        rows = (
            session.query(TelemetryRow)
            .filter(
                and_(
                    TelemetryRow.recorded_at >= start,
                    TelemetryRow.recorded_at <= end,
                )
            )
            .limit(MAX_REPLAY_RECORDS)
            .all()
        )
        if len(rows) == MAX_REPLAY_RECORDS:
            log.warning("Replay telemetry query capped at %d records", MAX_REPLAY_RECORDS)
        telemetry = [TelemetryOut.model_validate(t) for t in rows]

    if "intel" in types:
        rows = (
            session.query(IntelReportRow)
            .filter(
                and_(
                    IntelReportRow.published_at >= start,
                    IntelReportRow.published_at <= end,
                )
            )
            .limit(MAX_REPLAY_RECORDS)
            .all()
        )
        if len(rows) == MAX_REPLAY_RECORDS:
            log.warning("Replay intel query capped at %d records", MAX_REPLAY_RECORDS)
        intel = [IntelReportOut.model_validate(i) for i in rows]

    return {
        "detections": detections,
        "telemetry": telemetry,
        "intel": intel,
    }


def get_time_range(session: Session) -> dict:
    """Get the earliest and latest timestamps across all data."""
    det_min = session.query(func.min(DetectionRow.detected_at)).scalar()
    det_max = session.query(func.max(DetectionRow.detected_at)).scalar()
    tel_min = session.query(func.min(TelemetryRow.recorded_at)).scalar()
    tel_max = session.query(func.max(TelemetryRow.recorded_at)).scalar()
    intel_min = session.query(func.min(IntelReportRow.published_at)).scalar()
    intel_max = session.query(func.max(IntelReportRow.published_at)).scalar()

    candidates_min = [t for t in [det_min, tel_min, intel_min] if t is not None]
    candidates_max = [t for t in [det_max, tel_max, intel_max] if t is not None]

    return {
        "earliest": min(candidates_min) if candidates_min else None,
        "latest": max(candidates_max) if candidates_max else None,
    }


def get_replay_summary(
    session: Session,
    start: datetime,
    end: datetime,
) -> dict:
    """Return per-event-type counts within a time range (for timeline scrubbing)."""
    det_count = (
        session.query(func.count(DetectionRow.id))
        .filter(
            and_(
                DetectionRow.detected_at >= start,
                DetectionRow.detected_at <= end,
            )
        )
        .scalar()
        or 0
    )
    tel_count = (
        session.query(func.count(TelemetryRow.id))
        .filter(
            and_(
                TelemetryRow.recorded_at >= start,
                TelemetryRow.recorded_at <= end,
            )
        )
        .scalar()
        or 0
    )
    intel_count = (
        session.query(func.count(IntelReportRow.id))
        .filter(
            and_(
                IntelReportRow.published_at >= start,
                IntelReportRow.published_at <= end,
            )
        )
        .scalar()
        or 0
    )
    return {
        "start": start,
        "end": end,
        "detections": det_count,
        "telemetry": tel_count,
        "intel": intel_count,
    }
