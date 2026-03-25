"""FastAPI routes for Overwatch."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from overwatch.analysis.briefing import generate_briefing, get_latest_briefing
from overwatch.analysis.entities import resolve_all_entities
from overwatch.ingest.detections import ingest_detection, ingest_detections_batch
from overwatch.ingest.intel import ingest_intel_batch, ingest_intel_report
from overwatch.ingest.telemetry import ingest_telemetry, ingest_telemetry_batch
from overwatch.models import (
    BriefingOut,
    BriefingRow,
    DashboardStats,
    DetectionIn,
    DetectionOut,
    DetectionRow,
    EntityOut,
    EntityRow,
    IntelReportIn,
    IntelReportOut,
    IntelReportRow,
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
# Ingest endpoints
# ---------------------------------------------------------------------------


@router.post("/ingest/detection", response_model=DetectionOut | None, tags=["ingest"])
def post_detection(data: DetectionIn, session: Session = Depends(_get_session)):
    row = ingest_detection(session, data)
    if row is None:
        raise HTTPException(status_code=409, detail="Duplicate source_id")
    return row


@router.post("/ingest/detections", response_model=list[DetectionOut], tags=["ingest"])
def post_detections(items: list[DetectionIn], session: Session = Depends(_get_session)):
    return ingest_detections_batch(session, items)


@router.post("/ingest/intel", response_model=IntelReportOut | None, tags=["ingest"])
def post_intel(data: IntelReportIn, session: Session = Depends(_get_session)):
    row = ingest_intel_report(session, data)
    if row is None:
        raise HTTPException(status_code=409, detail="Duplicate source_id")
    return row


@router.post("/ingest/intel/batch", response_model=list[IntelReportOut], tags=["ingest"])
def post_intel_batch(items: list[IntelReportIn], session: Session = Depends(_get_session)):
    return ingest_intel_batch(session, items)


@router.post("/ingest/telemetry", response_model=TelemetryOut | None, tags=["ingest"])
def post_telemetry(data: TelemetryIn, session: Session = Depends(_get_session)):
    row = ingest_telemetry(session, data)
    if row is None:
        raise HTTPException(status_code=409, detail="Duplicate source_id")
    return row


@router.post("/ingest/telemetry/batch", response_model=list[TelemetryOut], tags=["ingest"])
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
    session: Session = Depends(_get_session),
):
    return generate_briefing(session, lookback_hours)


@router.get("/briefings/latest", response_model=BriefingOut | None, tags=["briefing"])
def get_latest(session: Session = Depends(_get_session)):
    return get_latest_briefing(session)


@router.get("/briefings", response_model=list[BriefingOut], tags=["briefing"])
def get_briefings(limit: int = 10, session: Session = Depends(_get_session)):
    return session.query(BriefingRow).order_by(desc(BriefingRow.created_at)).limit(limit).all()


# ---------------------------------------------------------------------------
# Entity resolution trigger
# ---------------------------------------------------------------------------


@router.post("/entities/resolve", response_model=list[EntityOut], tags=["analysis"])
def post_resolve_entities(session: Session = Depends(_get_session)):
    return resolve_all_entities(session)


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
        latest_detection=latest_det,
        latest_intel=latest_intel,
    )
