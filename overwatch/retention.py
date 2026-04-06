"""Data retention — purge old records beyond the configured TTL."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from overwatch.config import RETENTION_DAYS
from overwatch.models import (
    AlertRow,
    BriefingRow,
    DetectionRow,
    IntelReportRow,
    TelemetryRow,
)

log = logging.getLogger(__name__)

# Map table → timestamp column used for age comparison
_TABLE_COLUMNS = [
    (DetectionRow, DetectionRow.created_at),
    (IntelReportRow, IntelReportRow.created_at),
    (TelemetryRow, TelemetryRow.created_at),
    (AlertRow, AlertRow.created_at),
    (BriefingRow, BriefingRow.created_at),
]


def purge_old_records(session: Session, retention_days: int | None = None) -> dict[str, int]:
    """Delete records older than *retention_days*.

    Returns a dict of {table_name: rows_deleted}.
    """
    days = retention_days if retention_days is not None else RETENTION_DAYS
    if days <= 0:
        return {}

    cutoff = datetime.now(UTC) - timedelta(days=days)
    results: dict[str, int] = {}

    for model, col in _TABLE_COLUMNS:
        count = session.query(model).filter(col < cutoff).delete(synchronize_session=False)
        results[model.__tablename__] = count

    session.commit()
    total = sum(results.values())
    if total:
        log.info("Purged %d records older than %d days: %s", total, days, results)
    return results
