"""Alert engine — checks thresholds and dispatches to Discord/WebSocket.

Fires on every ingest event via the event bus.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from sqlalchemy.orm import Session

from overwatch.config import (
    ALERT_HIGH_CONFIDENCE,
    ALERT_LOW_BATTERY,
    DISCORD_WEBHOOK_URL,
)
from overwatch.models import AlertRow

log = logging.getLogger(__name__)


def check_detection_alerts(session: Session, data: dict[str, Any]) -> list[AlertRow]:
    """Check a detection event for alert-worthy conditions."""
    alerts: list[AlertRow] = []

    confidence = data.get("confidence", 0)
    label = data.get("label", "unknown")
    source_id = data.get("source_id", "")

    if confidence >= ALERT_HIGH_CONFIDENCE:
        alert = AlertRow(
            alert_type="high_confidence",
            severity="warning",
            title=f"High-confidence detection: {label} ({confidence:.0%})",
            body=f"Source: {data.get('source_name', 'yolo')}",
            source_id=source_id,
            lat=data.get("lat"),
            lon=data.get("lon"),
        )
        session.add(alert)
        alerts.append(alert)

    if alerts:
        session.commit()
        for a in alerts:
            _dispatch_discord(a)
    return alerts


def check_telemetry_alerts(session: Session, data: dict[str, Any]) -> list[AlertRow]:
    """Check telemetry for low battery."""
    alerts: list[AlertRow] = []

    battery = data.get("battery_pct")
    device = data.get("device_name", "unknown")
    source_id = data.get("source_id", "")

    if battery is not None and battery < ALERT_LOW_BATTERY:
        alert = AlertRow(
            alert_type="low_battery",
            severity="critical",
            title=f"Low battery: {device} at {battery:.0f}%",
            body=f"Device {device} battery critically low",
            source_id=source_id,
            lat=data.get("lat"),
            lon=data.get("lon"),
        )
        session.add(alert)
        alerts.append(alert)

    if alerts:
        session.commit()
        for a in alerts:
            _dispatch_discord(a)
    return alerts


def check_geofence_alerts(
    session: Session,
    lat: float,
    lon: float,
    label: str,
    source_id: str,
    geofences: list[dict],
) -> list[AlertRow]:
    """Check if a point is inside any geofence and fire alerts."""
    alerts: list[AlertRow] = []
    for gf in geofences:
        if gf.get("alert_on_enter") and _point_in_polygon(lat, lon, gf["coords"]):
            alert = AlertRow(
                alert_type="geofence_enter",
                severity="warning",
                title=f"{label} entered zone: {gf['name']}",
                body=f"Detected at ({lat:.4f}, {lon:.4f})",
                source_id=source_id,
                lat=lat,
                lon=lon,
                meta_json=json.dumps({"geofence_id": gf.get("id", "")}),
            )
            session.add(alert)
            alerts.append(alert)

    if alerts:
        session.commit()
        for a in alerts:
            _dispatch_discord(a)
    return alerts


def _point_in_polygon(lat: float, lon: float, polygon: list[list[float]]) -> bool:
    """Ray-casting point-in-polygon test. Coords are [lat, lon]."""
    n = len(polygon)
    if n < 3:
        return False
    inside = False
    # Use lat=y, lon=x for the ray-casting algorithm
    py, px = lat, lon
    j = n - 1
    for i in range(n):
        iy, ix = polygon[i]
        jy, jx = polygon[j]
        if ((iy > py) != (jy > py)) and (px < (jx - ix) * (py - iy) / (jy - iy) + ix):
            inside = not inside
        j = i
    return inside


def _dispatch_discord(alert: AlertRow) -> None:
    """Send alert to Discord webhook if configured."""
    if not DISCORD_WEBHOOK_URL:
        return
    color_map = {"info": 3447003, "warning": 16776960, "critical": 16711680}
    embed = {
        "title": alert.title,
        "description": alert.body,
        "color": color_map.get(alert.severity, 3447003),
        "footer": {"text": f"Overwatch | {alert.alert_type}"},
    }
    if alert.lat and alert.lon:
        embed["description"] += f"\nLocation: ({alert.lat:.4f}, {alert.lon:.4f})"
    try:
        httpx.post(
            DISCORD_WEBHOOK_URL,
            json={"embeds": [embed]},
            timeout=5,
        )
    except httpx.HTTPError:
        log.warning("Failed to send Discord alert: %s", alert.title)
