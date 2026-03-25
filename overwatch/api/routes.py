"""FastAPI routes for Overwatch."""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from overwatch.analysis.alerts import (
    check_detection_alerts,
    check_geofence_alerts,
    check_telemetry_alerts,
)
from overwatch.analysis.briefing import generate_briefing, get_latest_briefing
from overwatch.analysis.entities import resolve_all_entities
from overwatch.analysis.geofence import (
    create_geofence,
    delete_geofence,
    geofence_row_to_out,
    list_geofences,
)
from overwatch.analysis.mesh_health import get_device_health
from overwatch.analysis.ollama_briefing import generate_ollama_briefing
from overwatch.analysis.replay import get_replay_frame, get_time_range
from overwatch.events import publish
from overwatch.ingest.detections import ingest_detection, ingest_detections_batch
from overwatch.ingest.intel import ingest_intel_batch, ingest_intel_report
from overwatch.ingest.telemetry import ingest_telemetry, ingest_telemetry_batch
from overwatch.models import (
    AlertOut,
    AlertRow,
    BriefingOut,
    BriefingRow,
    DashboardStats,
    DetectionIn,
    DetectionOut,
    DetectionRow,
    DeviceHealth,
    EntityOut,
    EntityRow,
    EntityTimelineEntry,
    GeofenceIn,
    GeofenceOut,
    GeofenceRow,
    IntelReportIn,
    IntelReportOut,
    IntelReportRow,
    ReplayFrame,
    TelemetryIn,
    TelemetryOut,
    TelemetryRow,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Dependency: session from app state
# ---------------------------------------------------------------------------


def _get_session():
    """Injected by app startup — see app.py."""
    raise NotImplementedError("Session dependency not configured")


# ---------------------------------------------------------------------------
# Ingest endpoints (with event publishing + alert checks)
# ---------------------------------------------------------------------------


@router.post(
    "/ingest/detection",
    response_model=DetectionOut | None,
    tags=["ingest"],
)
def post_detection(data: DetectionIn, session: Session = Depends(_get_session)):
    row = ingest_detection(session, data)
    if row is None:
        raise HTTPException(status_code=409, detail="Duplicate source_id")
    publish("detection", data.model_dump(mode="json"))
    # Alert checks
    check_detection_alerts(session, data.model_dump())
    if data.lat is not None and data.lon is not None:
        gfs = list_geofences(session)
        check_geofence_alerts(session, data.lat, data.lon, data.label, data.source_id, gfs)
    return row


@router.post(
    "/ingest/detections",
    response_model=list[DetectionOut],
    tags=["ingest"],
)
def post_detections(items: list[DetectionIn], session: Session = Depends(_get_session)):
    results = ingest_detections_batch(session, items)
    for item in items:
        publish("detection", item.model_dump(mode="json"))
    return results


@router.post(
    "/ingest/intel",
    response_model=IntelReportOut | None,
    tags=["ingest"],
)
def post_intel(data: IntelReportIn, session: Session = Depends(_get_session)):
    row = ingest_intel_report(session, data)
    if row is None:
        raise HTTPException(status_code=409, detail="Duplicate source_id")
    publish("intel", data.model_dump(mode="json"))
    return row


@router.post(
    "/ingest/intel/batch",
    response_model=list[IntelReportOut],
    tags=["ingest"],
)
def post_intel_batch(items: list[IntelReportIn], session: Session = Depends(_get_session)):
    return ingest_intel_batch(session, items)


@router.post(
    "/ingest/telemetry",
    response_model=TelemetryOut | None,
    tags=["ingest"],
)
def post_telemetry(data: TelemetryIn, session: Session = Depends(_get_session)):
    row = ingest_telemetry(session, data)
    if row is None:
        raise HTTPException(status_code=409, detail="Duplicate source_id")
    publish("telemetry", data.model_dump(mode="json"))
    check_telemetry_alerts(session, data.model_dump())
    return row


@router.post(
    "/ingest/telemetry/batch",
    response_model=list[TelemetryOut],
    tags=["ingest"],
)
def post_telemetry_batch(items: list[TelemetryIn], session: Session = Depends(_get_session)):
    return ingest_telemetry_batch(session, items)


# ---------------------------------------------------------------------------
# Query endpoints
# ---------------------------------------------------------------------------


@router.get("/detections", response_model=list[DetectionOut], tags=["query"])
def get_detections(
    limit: int = 50,
    label: str | None = None,
    session: Session = Depends(_get_session),
):
    q = session.query(DetectionRow).order_by(desc(DetectionRow.detected_at))
    if label:
        q = q.filter(DetectionRow.label == label)
    return q.limit(limit).all()


@router.get("/intel", response_model=list[IntelReportOut], tags=["query"])
def get_intel(limit: int = 50, session: Session = Depends(_get_session)):
    return (
        session.query(IntelReportRow).order_by(desc(IntelReportRow.published_at)).limit(limit).all()
    )


@router.get("/telemetry", response_model=list[TelemetryOut], tags=["query"])
def get_telemetry(
    limit: int = 50,
    device: str | None = None,
    session: Session = Depends(_get_session),
):
    q = session.query(TelemetryRow).order_by(desc(TelemetryRow.recorded_at))
    if device:
        q = q.filter(TelemetryRow.device_name == device)
    return q.limit(limit).all()


@router.get("/entities", response_model=list[EntityOut], tags=["query"])
def get_entities(limit: int = 50, session: Session = Depends(_get_session)):
    return session.query(EntityRow).order_by(desc(EntityRow.sighting_count)).limit(limit).all()


# ---------------------------------------------------------------------------
# Briefing endpoints
# ---------------------------------------------------------------------------


@router.post("/briefings/generate", response_model=BriefingOut, tags=["briefing"])
def post_generate_briefing(
    lookback_hours: int = 24,
    use_ollama: bool = False,
    session: Session = Depends(_get_session),
):
    if use_ollama:
        return generate_ollama_briefing(session, lookback_hours)
    return generate_briefing(session, lookback_hours)


@router.get("/briefings/latest", response_model=BriefingOut | None, tags=["briefing"])
def get_latest(session: Session = Depends(_get_session)):
    return get_latest_briefing(session)


@router.get("/briefings", response_model=list[BriefingOut], tags=["briefing"])
def get_briefings(limit: int = 10, session: Session = Depends(_get_session)):
    return session.query(BriefingRow).order_by(desc(BriefingRow.created_at)).limit(limit).all()


@router.get("/briefings/{briefing_id}/export", tags=["briefing"])
def export_briefing(briefing_id: str, session: Session = Depends(_get_session)):
    """Export a briefing as downloadable Markdown."""
    row = session.query(BriefingRow).filter(BriefingRow.id == briefing_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Briefing not found")
    filename = f"sitrep-{row.created_at.strftime('%Y%m%d-%H%M')}.md"
    return Response(
        content=row.body,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Entity resolution + timeline
# ---------------------------------------------------------------------------


@router.post("/entities/resolve", response_model=list[EntityOut], tags=["analysis"])
def post_resolve_entities(session: Session = Depends(_get_session)):
    return resolve_all_entities(session)


@router.get(
    "/entities/{entity_id}/timeline",
    response_model=list[EntityTimelineEntry],
    tags=["analysis"],
)
def get_entity_timeline(entity_id: str, session: Session = Depends(_get_session)):
    """Get cross-source timeline for a specific entity."""
    entity = session.query(EntityRow).filter(EntityRow.id == entity_id).first()
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    source_ids = json.loads(entity.source_ids_json or "[]")
    entries: list[EntityTimelineEntry] = []

    for sid in source_ids:
        # Check detections
        det = session.query(DetectionRow).filter(DetectionRow.source_id == sid).first()
        if det:
            entries.append(
                EntityTimelineEntry(
                    source_type="detection",
                    source_id=sid,
                    label=det.label,
                    timestamp=det.detected_at,
                    lat=det.lat,
                    lon=det.lon,
                )
            )
        # Check intel
        intel = session.query(IntelReportRow).filter(IntelReportRow.source_id == sid).first()
        if intel:
            entries.append(
                EntityTimelineEntry(
                    source_type="intel",
                    source_id=sid,
                    label=intel.title,
                    timestamp=intel.published_at,
                )
            )

    entries.sort(key=lambda e: e.timestamp)
    return entries


# ---------------------------------------------------------------------------
# Geofence endpoints
# ---------------------------------------------------------------------------


@router.post("/geofences", response_model=GeofenceOut, tags=["geofence"])
def post_geofence(data: GeofenceIn, session: Session = Depends(_get_session)):
    row = create_geofence(session, data)
    return geofence_row_to_out(row)


@router.get("/geofences", response_model=list[GeofenceOut], tags=["geofence"])
def get_geofences(session: Session = Depends(_get_session)):
    rows = session.query(GeofenceRow).all()
    return [geofence_row_to_out(r) for r in rows]


@router.delete("/geofences/{geofence_id}", tags=["geofence"])
def del_geofence(geofence_id: str, session: Session = Depends(_get_session)):
    if not delete_geofence(session, geofence_id):
        raise HTTPException(status_code=404, detail="Geofence not found")
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Alert endpoints
# ---------------------------------------------------------------------------


@router.get("/alerts", response_model=list[AlertOut], tags=["alerts"])
def get_alerts(
    limit: int = 50,
    unacknowledged_only: bool = False,
    session: Session = Depends(_get_session),
):
    q = session.query(AlertRow).order_by(desc(AlertRow.created_at))
    if unacknowledged_only:
        q = q.filter(AlertRow.acknowledged == 0)
    return q.limit(limit).all()


@router.post("/alerts/{alert_id}/acknowledge", tags=["alerts"])
def ack_alert(alert_id: str, session: Session = Depends(_get_session)):
    row = session.query(AlertRow).filter(AlertRow.id == alert_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Alert not found")
    row.acknowledged = 1
    session.commit()
    return {"status": "acknowledged"}


# ---------------------------------------------------------------------------
# Mesh health
# ---------------------------------------------------------------------------


@router.get(
    "/mesh/health",
    response_model=list[DeviceHealth],
    tags=["mesh"],
)
def get_mesh_health(session: Session = Depends(_get_session)):
    return get_device_health(session)


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


@router.get("/replay/range", tags=["replay"])
def get_replay_range(session: Session = Depends(_get_session)):
    return get_time_range(session)


@router.get("/replay/frame", response_model=ReplayFrame, tags=["replay"])
def get_frame(
    start: datetime,
    end: datetime,
    session: Session = Depends(_get_session),
):
    data = get_replay_frame(session, start, end)
    return ReplayFrame(
        timestamp=start,
        detections=data["detections"],
        telemetry=data["telemetry"],
    )


# ---------------------------------------------------------------------------
# Dashboard stats
# ---------------------------------------------------------------------------


@router.get("/dashboard/stats", response_model=DashboardStats, tags=["dashboard"])
def get_dashboard_stats(session: Session = Depends(_get_session)):
    latest_det = session.query(func.max(DetectionRow.detected_at)).scalar()
    latest_intel = session.query(func.max(IntelReportRow.published_at)).scalar()

    return DashboardStats(
        total_detections=session.query(DetectionRow).count(),
        total_intel_reports=session.query(IntelReportRow).count(),
        total_telemetry_points=session.query(TelemetryRow).count(),
        total_entities=session.query(EntityRow).count(),
        total_briefings=session.query(BriefingRow).count(),
        total_alerts=session.query(AlertRow).count(),
        total_geofences=session.query(GeofenceRow).count(),
        latest_detection=latest_det,
        latest_intel=latest_intel,
    )
