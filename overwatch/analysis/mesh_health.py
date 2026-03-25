"""Mesh node health tracking from telemetry heartbeats."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from overwatch.config import ALERT_DEVICE_OFFLINE_SECONDS, ALERT_DEVICE_STALE_SECONDS
from overwatch.models import DeviceHealth, TelemetryRow


def get_device_health(session: Session) -> list[DeviceHealth]:
    """Compute health status for all known devices."""
    # Get the latest telemetry per device
    subq = (
        session.query(
            TelemetryRow.device_name,
            func.max(TelemetryRow.recorded_at).label("max_ts"),
        )
        .group_by(TelemetryRow.device_name)
        .subquery()
    )

    latest = (
        session.query(TelemetryRow)
        .join(
            subq,
            (TelemetryRow.device_name == subq.c.device_name)
            & (TelemetryRow.recorded_at == subq.c.max_ts),
        )
        .all()
    )

    now = datetime.now(UTC)
    results: list[DeviceHealth] = []
    for row in latest:
        ts = row.recorded_at
        if ts.tzinfo is None:
            # Naive datetime — assume UTC
            staleness = (now.replace(tzinfo=None) - ts).total_seconds()
        else:
            staleness = (now - ts).total_seconds()

        if staleness > ALERT_DEVICE_OFFLINE_SECONDS:
            status = "offline"
        elif staleness > ALERT_DEVICE_STALE_SECONDS:
            status = "stale"
        else:
            status = "online"

        results.append(
            DeviceHealth(
                device_name=row.device_name,
                last_seen=row.recorded_at,
                lat=row.lat,
                lon=row.lon,
                battery_pct=row.battery_pct,
                altitude=row.altitude,
                speed=row.speed,
                staleness_seconds=staleness,
                status=status,
            )
        )

    return sorted(results, key=lambda d: d.staleness_seconds)
