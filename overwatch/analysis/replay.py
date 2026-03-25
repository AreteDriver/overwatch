"""Replay mode — time-windowed data retrieval for post-mission review."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_
from sqlalchemy.orm import Session

from overwatch.models import DetectionOut, DetectionRow, TelemetryOut, TelemetryRow


def get_replay_frame(
    session: Session,
    start: datetime,
    end: datetime,
) -> dict:
    """Get all detections and telemetry within a time window."""
    detections = (
        session.query(DetectionRow)
        .filter(
            and_(
                DetectionRow.detected_at >= start,
                DetectionRow.detected_at <= end,
            )
        )
        .all()
    )
    telemetry = (
        session.query(TelemetryRow)
        .filter(
            and_(
                TelemetryRow.recorded_at >= start,
                TelemetryRow.recorded_at <= end,
            )
        )
        .all()
    )
    return {
        "detections": [DetectionOut.model_validate(d) for d in detections],
        "telemetry": [TelemetryOut.model_validate(t) for t in telemetry],
    }


def get_time_range(session: Session) -> dict:
    """Get the earliest and latest timestamps across all data."""
    from sqlalchemy import func

    det_min = session.query(func.min(DetectionRow.detected_at)).scalar()
    det_max = session.query(func.max(DetectionRow.detected_at)).scalar()
    tel_min = session.query(func.min(TelemetryRow.recorded_at)).scalar()
    tel_max = session.query(func.max(TelemetryRow.recorded_at)).scalar()

    candidates_min = [t for t in [det_min, tel_min] if t is not None]
    candidates_max = [t for t in [det_max, tel_max] if t is not None]

    return {
        "earliest": min(candidates_min) if candidates_min else None,
        "latest": max(candidates_max) if candidates_max else None,
    }
