"""Geofence management."""

from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from overwatch.models import GeofenceIn, GeofenceOut, GeofenceRow

log = logging.getLogger(__name__)


def create_geofence(session: Session, data: GeofenceIn) -> GeofenceRow:
    row = GeofenceRow(
        name=data.name,
        coords_json=json.dumps(data.coords),
        alert_on_enter=data.alert_on_enter,
        alert_on_exit=data.alert_on_exit,
    )
    session.add(row)
    session.commit()
    log.info("Created geofence '%s' with %d points", data.name, len(data.coords))
    return row


def list_geofences(session: Session) -> list[dict]:
    """Return geofences as dicts with parsed coords."""
    rows = session.query(GeofenceRow).all()
    result = []
    for r in rows:
        result.append(
            {
                "id": r.id,
                "name": r.name,
                "coords": json.loads(r.coords_json),
                "alert_on_enter": bool(r.alert_on_enter),
                "alert_on_exit": bool(r.alert_on_exit),
                "created_at": r.created_at,
            }
        )
    return result


def delete_geofence(session: Session, geofence_id: str) -> bool:
    row = session.query(GeofenceRow).filter(GeofenceRow.id == geofence_id).first()
    if row:
        session.delete(row)
        session.commit()
        return True
    return False


def geofence_row_to_out(row: GeofenceRow) -> GeofenceOut:
    """Convert a GeofenceRow to GeofenceOut with parsed coords."""
    return GeofenceOut(
        id=row.id,
        name=row.name,
        coords=json.loads(row.coords_json),
        alert_on_enter=bool(row.alert_on_enter),
        alert_on_exit=bool(row.alert_on_exit),
        created_at=row.created_at,
    )
