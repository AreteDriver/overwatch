"""FastAPI routes for Overwatch."""

from __future__ import annotations

import csv
import io
import json
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
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
from overwatch.analysis.replay import (
    get_replay_frame,
    get_replay_summary,
    get_time_range,
    parse_event_types,
)
from overwatch.analysis.rules import evaluate_rules
from overwatch.events import publish
from overwatch.ingest.detections import ingest_detection, ingest_detections_batch
from overwatch.ingest.intel import ingest_intel_batch, ingest_intel_report
from overwatch.ingest.telemetry import ingest_telemetry, ingest_telemetry_batch
from overwatch.models import (
    AlertOut,
    AlertRow,
    AlertRuleIn,
    AlertRuleOut,
    AlertRuleRow,
    AlertRuleUpdate,
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyOut,
    ApiKeyRow,
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
    ReplaySummary,
    TelemetryIn,
    TelemetryOut,
    TelemetryRow,
    WebhookIn,
    WebhookOut,
    WebhookRow,
    _new_id,
)
from overwatch.retention import purge_old_records
from overwatch.security import _hash_key, verify_api_key_scoped

router = APIRouter()


# ---------------------------------------------------------------------------
# Dependency: session from app state
# ---------------------------------------------------------------------------


def _get_session():
    """Injected by app startup — see app.py."""
    raise NotImplementedError("Session dependency not configured")


# ---------------------------------------------------------------------------
# Scope-checking dependencies
# ---------------------------------------------------------------------------


def _require_write(request: Request, session: Session = Depends(_get_session)):
    """Require 'write' scope for ingest endpoints."""
    verify_api_key_scoped(request, session, "write")


def _require_admin(request: Request, session: Session = Depends(_get_session)):
    """Require 'admin' scope for admin endpoints."""
    verify_api_key_scoped(request, session, "admin")


# ---------------------------------------------------------------------------
# Ingest endpoints (with event publishing + alert checks)
# ---------------------------------------------------------------------------


@router.post(
    "/ingest/detection",
    response_model=DetectionOut | None,
    tags=["ingest"],
    dependencies=[Depends(_require_write)],
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
    # Configurable rules engine
    evaluate_rules(session, "detection", data.model_dump())
    return row


@router.post(
    "/ingest/detections",
    response_model=list[DetectionOut],
    tags=["ingest"],
    dependencies=[Depends(_require_write)],
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
    dependencies=[Depends(_require_write)],
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
    dependencies=[Depends(_require_write)],
)
def post_intel_batch(items: list[IntelReportIn], session: Session = Depends(_get_session)):
    return ingest_intel_batch(session, items)


@router.post(
    "/ingest/telemetry",
    response_model=TelemetryOut | None,
    tags=["ingest"],
    dependencies=[Depends(_require_write)],
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
    dependencies=[Depends(_require_write)],
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
        q = q.filter(AlertRow.acknowledged.is_(False))
    return q.limit(limit).all()


@router.post("/alerts/{alert_id}/acknowledge", tags=["alerts"])
def ack_alert(alert_id: str, session: Session = Depends(_get_session)):
    row = session.query(AlertRow).filter(AlertRow.id == alert_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Alert not found")
    row.acknowledged = True
    session.commit()
    return {"status": "acknowledged"}


# ---------------------------------------------------------------------------
# Alert rules CRUD
# ---------------------------------------------------------------------------


@router.post(
    "/rules",
    response_model=AlertRuleOut,
    tags=["rules"],
    dependencies=[Depends(_require_admin)],
)
def post_rule(data: AlertRuleIn, session: Session = Depends(_get_session)):
    """Create a new alerting rule."""
    row = AlertRuleRow(
        name=data.name,
        rule_type=data.rule_type.value,
        enabled=True,
        config_json=json.dumps(data.config),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _rule_row_to_out(row)


@router.get("/rules", response_model=list[AlertRuleOut], tags=["rules"])
def get_rules(session: Session = Depends(_get_session)):
    """List all alerting rules."""
    rows = session.query(AlertRuleRow).order_by(desc(AlertRuleRow.created_at)).all()
    return [_rule_row_to_out(r) for r in rows]


@router.put(
    "/rules/{rule_id}",
    response_model=AlertRuleOut,
    tags=["rules"],
    dependencies=[Depends(_require_admin)],
)
def put_rule(
    rule_id: str,
    data: AlertRuleUpdate,
    session: Session = Depends(_get_session),
):
    """Update an alerting rule (enable/disable, change config)."""
    row = session.query(AlertRuleRow).filter(AlertRuleRow.id == rule_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found")
    if data.name is not None:
        row.name = data.name
    if data.rule_type is not None:
        row.rule_type = data.rule_type.value
    if data.enabled is not None:
        row.enabled = data.enabled
    if data.config is not None:
        row.config_json = json.dumps(data.config)
    session.commit()
    session.refresh(row)
    return _rule_row_to_out(row)


@router.delete(
    "/rules/{rule_id}",
    tags=["rules"],
    dependencies=[Depends(_require_admin)],
)
def delete_rule(rule_id: str, session: Session = Depends(_get_session)):
    """Delete an alerting rule."""
    row = session.query(AlertRuleRow).filter(AlertRuleRow.id == rule_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found")
    session.delete(row)
    session.commit()
    return {"status": "deleted"}


def _rule_row_to_out(row: AlertRuleRow) -> AlertRuleOut:
    """Convert an AlertRuleRow to AlertRuleOut, parsing JSON fields."""
    return AlertRuleOut(
        id=row.id,
        name=row.name,
        rule_type=row.rule_type,
        enabled=bool(row.enabled),
        config=json.loads(row.config_json or "{}"),
        created_at=row.created_at,
    )


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
    event_types: str | None = Query(
        default=None,
        description="Comma-separated filter: detections,telemetry,intel",
    ),
    speed: float = Query(default=1.0, gt=0.0, le=16.0, description="Playback speed multiplier"),
    session: Session = Depends(_get_session),
):
    """Get a replay frame with optional event filtering and speed control."""
    parsed_types = parse_event_types(event_types)
    data = get_replay_frame(session, start, end, event_types=parsed_types)
    return ReplayFrame(
        timestamp=start,
        detections=data["detections"],
        telemetry=data["telemetry"],
        intel=data["intel"],
        speed=speed,
        event_types=sorted(parsed_types),
    )


@router.get("/replay/summary", response_model=ReplaySummary, tags=["replay"])
def get_replay_summary_endpoint(
    start: datetime,
    end: datetime,
    session: Session = Depends(_get_session),
):
    """Get per-event-type counts in a time range for timeline scrubbing UI."""
    data = get_replay_summary(session, start, end)
    return ReplaySummary(**data)


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


# ---------------------------------------------------------------------------
# Webhook subscriptions
# ---------------------------------------------------------------------------


@router.post(
    "/webhooks",
    response_model=WebhookOut,
    tags=["webhooks"],
    dependencies=[Depends(_require_admin)],
)
def post_webhook(data: WebhookIn, session: Session = Depends(_get_session)):
    """Register an external webhook subscription."""
    row = WebhookRow(
        url=data.url,
        event_types=json.dumps(data.event_types),
        secret=data.secret or "",
        active=True,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _webhook_row_to_out(row)


@router.get("/webhooks", response_model=list[WebhookOut], tags=["webhooks"])
def get_webhooks(session: Session = Depends(_get_session)):
    """List all registered webhooks."""
    rows = session.query(WebhookRow).order_by(desc(WebhookRow.created_at)).all()
    return [_webhook_row_to_out(r) for r in rows]


@router.delete(
    "/webhooks/{webhook_id}",
    tags=["webhooks"],
    dependencies=[Depends(_require_admin)],
)
def delete_webhook(webhook_id: str, session: Session = Depends(_get_session)):
    """Remove a webhook subscription."""
    row = session.query(WebhookRow).filter(WebhookRow.id == webhook_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Webhook not found")
    session.delete(row)
    session.commit()
    return {"status": "deleted"}


@router.post(
    "/webhooks/{webhook_id}/test",
    tags=["webhooks"],
    dependencies=[Depends(_require_admin)],
)
def test_webhook(webhook_id: str, session: Session = Depends(_get_session)):
    """Send a test event to a specific webhook."""
    row = session.query(WebhookRow).filter(WebhookRow.id == webhook_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Webhook not found")

    test_payload = {
        "event": "test",
        "data": {"message": "Overwatch webhook test", "webhook_id": webhook_id},
        "timestamp": datetime.now().isoformat(),
    }
    body_bytes = json.dumps(test_payload).encode()

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if row.secret:
        import hashlib
        import hmac

        sig = hmac.new(row.secret.encode(), body_bytes, hashlib.sha256).hexdigest()
        headers["X-Overwatch-Signature"] = sig

    try:
        import httpx

        with httpx.Client(timeout=5.0) as client:
            resp = client.post(row.url, content=body_bytes, headers=headers)
            resp.raise_for_status()
        return {"status": "delivered", "status_code": resp.status_code}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Delivery failed: {exc}") from exc


def _webhook_row_to_out(row: WebhookRow) -> WebhookOut:
    """Convert a WebhookRow to WebhookOut, parsing JSON fields."""
    return WebhookOut(
        id=row.id,
        url=row.url,
        event_types=json.loads(row.event_types or "[]"),
        active=bool(row.active),
        created_at=row.created_at,
        last_delivered_at=row.last_delivered_at,
        failure_count=row.failure_count or 0,
    )


# ---------------------------------------------------------------------------
# API Key Management
# ---------------------------------------------------------------------------


@router.post(
    "/admin/keys",
    response_model=ApiKeyCreated,
    tags=["admin"],
    dependencies=[Depends(_require_admin)],
)
def create_api_key(data: ApiKeyCreate, session: Session = Depends(_get_session)):
    """Create a new scoped API key.

    Returns the raw key ONCE in the response body. Only the SHA-256 hash is stored.
    """
    raw_key = secrets.token_urlsafe(32)
    key_hash = _hash_key(raw_key)

    row = ApiKeyRow(
        id=_new_id(),
        name=data.name,
        key_hash=key_hash,
        scopes_json=json.dumps([s.value for s in data.scopes]),
        active=True,
    )
    session.add(row)
    session.commit()
    session.refresh(row)

    return ApiKeyCreated(
        id=row.id,
        name=row.name,
        key=raw_key,
        scopes=row.scopes,
        created_at=row.created_at,
    )


@router.get(
    "/admin/keys",
    response_model=list[ApiKeyOut],
    tags=["admin"],
    dependencies=[Depends(_require_admin)],
)
def list_api_keys(session: Session = Depends(_get_session)):
    """List all API keys (hash never exposed)."""
    rows = session.query(ApiKeyRow).order_by(ApiKeyRow.created_at.desc()).all()
    return [
        ApiKeyOut(
            id=r.id,
            name=r.name,
            scopes=r.scopes,
            created_at=r.created_at,
            last_used_at=r.last_used_at,
            active=bool(r.active),
        )
        for r in rows
    ]


@router.delete(
    "/admin/keys/{key_id}",
    tags=["admin"],
    dependencies=[Depends(_require_admin)],
)
def deactivate_api_key(key_id: str, session: Session = Depends(_get_session)):
    """Deactivate an API key (soft delete)."""
    row = session.query(ApiKeyRow).filter(ApiKeyRow.id == key_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="API key not found")
    row.active = 0
    session.commit()
    return {"status": "deactivated", "id": key_id}


# ---------------------------------------------------------------------------
# Data retention
# ---------------------------------------------------------------------------


@router.post(
    "/admin/purge",
    tags=["admin"],
    dependencies=[Depends(_require_admin)],
)
def post_purge(
    retention_days: int = Query(default=30, ge=1),
    session: Session = Depends(_get_session),
):
    """Manually purge records older than retention_days."""
    results = purge_old_records(session, retention_days)
    return {"purged": results, "retention_days": retention_days}


# ---------------------------------------------------------------------------
# Bulk export (CSV / GeoJSON)
# ---------------------------------------------------------------------------


@router.get("/export/detections.csv", tags=["export"])
def export_detections_csv(
    limit: int = Query(default=10000, le=50000),
    label: str | None = None,
    session: Session = Depends(_get_session),
):
    """Export detections as CSV."""
    q = session.query(DetectionRow).order_by(desc(DetectionRow.detected_at))
    if label:
        q = q.filter(DetectionRow.label == label)
    rows = q.limit(limit).all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "id",
            "source_id",
            "label",
            "confidence",
            "lat",
            "lon",
            "source_name",
            "detected_at",
            "created_at",
        ]
    )
    for r in rows:
        writer.writerow(
            [
                r.id,
                r.source_id,
                r.label,
                r.confidence,
                r.lat,
                r.lon,
                r.source_name,
                r.detected_at,
                r.created_at,
            ]
        )

    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="detections.csv"'},
    )


@router.get("/export/detections.geojson", tags=["export"])
def export_detections_geojson(
    limit: int = Query(default=10000, le=50000),
    label: str | None = None,
    session: Session = Depends(_get_session),
):
    """Export detections as GeoJSON FeatureCollection."""
    q = session.query(DetectionRow).order_by(desc(DetectionRow.detected_at))
    if label:
        q = q.filter(DetectionRow.label == label)
    q = q.filter(DetectionRow.lat.isnot(None), DetectionRow.lon.isnot(None))
    rows = q.limit(limit).all()

    features = []
    for r in rows:
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [r.lon, r.lat]},
                "properties": {
                    "id": r.id,
                    "label": r.label,
                    "confidence": r.confidence,
                    "source_name": r.source_name,
                    "detected_at": r.detected_at.isoformat() if r.detected_at else None,
                },
            }
        )

    return {"type": "FeatureCollection", "features": features}


@router.get("/export/intel.csv", tags=["export"])
def export_intel_csv(
    limit: int = Query(default=10000, le=50000),
    session: Session = Depends(_get_session),
):
    """Export intel reports as CSV."""
    rows = (
        session.query(IntelReportRow).order_by(desc(IntelReportRow.published_at)).limit(limit).all()
    )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "id",
            "source_id",
            "title",
            "summary",
            "source_name",
            "source_url",
            "published_at",
            "created_at",
        ]
    )
    for r in rows:
        writer.writerow(
            [
                r.id,
                r.source_id,
                r.title,
                r.summary,
                r.source_name,
                r.source_url,
                r.published_at,
                r.created_at,
            ]
        )

    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="intel.csv"'},
    )


@router.get("/export/telemetry.csv", tags=["export"])
def export_telemetry_csv(
    limit: int = Query(default=10000, le=50000),
    device: str | None = None,
    session: Session = Depends(_get_session),
):
    """Export telemetry as CSV."""
    q = session.query(TelemetryRow).order_by(desc(TelemetryRow.recorded_at))
    if device:
        q = q.filter(TelemetryRow.device_name == device)
    rows = q.limit(limit).all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "id",
            "source_id",
            "device_name",
            "lat",
            "lon",
            "altitude",
            "heading",
            "speed",
            "battery_pct",
            "recorded_at",
        ]
    )
    for r in rows:
        writer.writerow(
            [
                r.id,
                r.source_id,
                r.device_name,
                r.lat,
                r.lon,
                r.altitude,
                r.heading,
                r.speed,
                r.battery_pct,
                r.recorded_at,
            ]
        )

    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="telemetry.csv"'},
    )


@router.get("/export/telemetry.geojson", tags=["export"])
def export_telemetry_geojson(
    limit: int = Query(default=10000, le=50000),
    device: str | None = None,
    session: Session = Depends(_get_session),
):
    """Export telemetry as GeoJSON FeatureCollection."""
    q = session.query(TelemetryRow).order_by(desc(TelemetryRow.recorded_at))
    if device:
        q = q.filter(TelemetryRow.device_name == device)
    rows = q.limit(limit).all()

    features = []
    for r in rows:
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [r.lon, r.lat]},
                "properties": {
                    "id": r.id,
                    "device_name": r.device_name,
                    "altitude": r.altitude,
                    "heading": r.heading,
                    "speed": r.speed,
                    "battery_pct": r.battery_pct,
                    "recorded_at": r.recorded_at.isoformat() if r.recorded_at else None,
                },
            }
        )

    return {"type": "FeatureCollection", "features": features}
