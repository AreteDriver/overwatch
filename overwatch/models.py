"""SQLAlchemy models and Pydantic schemas."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Float, Index, String, Text
from sqlalchemy.orm import DeclarativeBase


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# SQLAlchemy ORM
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


class DetectionRow(Base):
    """A YOLO object detection event."""

    __tablename__ = "detections"

    id = Column(String, primary_key=True, default=_new_id)
    source_id = Column(String, unique=True, nullable=False)
    label = Column(String, nullable=False)
    confidence = Column(Float, nullable=False)
    bbox_x = Column(Float)
    bbox_y = Column(Float)
    bbox_w = Column(Float)
    bbox_h = Column(Float)
    lat = Column(Float)
    lon = Column(Float)
    source_name = Column(String, default="yolo")
    detected_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    meta_json = Column(Text, default="{}")

    __table_args__ = (Index("ix_detections_label", "label"),)


class IntelReportRow(Base):
    """An OSINT intel report (e.g. from TheWire-STT)."""

    __tablename__ = "intel_reports"

    id = Column(String, primary_key=True, default=_new_id)
    source_id = Column(String, unique=True, nullable=False)
    title = Column(String, nullable=False)
    summary = Column(Text, nullable=False)
    body = Column(Text, default="")
    source_name = Column(String, default="thewire")
    source_url = Column(String, default="")
    published_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    tags_json = Column(Text, default="[]")


class TelemetryRow(Base):
    """Drone / sensor telemetry point."""

    __tablename__ = "telemetry"

    id = Column(String, primary_key=True, default=_new_id)
    source_id = Column(String, unique=True, nullable=False)
    device_name = Column(String, nullable=False)
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    altitude = Column(Float)
    heading = Column(Float)
    speed = Column(Float)
    battery_pct = Column(Float)
    recorded_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    meta_json = Column(Text, default="{}")

    __table_args__ = (Index("ix_telemetry_device", "device_name"),)


class EntityRow(Base):
    """A resolved entity tracked across sources."""

    __tablename__ = "entities"

    id = Column(String, primary_key=True, default=_new_id)
    canonical_name = Column(String, nullable=False)
    entity_type = Column(String, nullable=False)  # person, vehicle, location, org
    aliases_json = Column(Text, default="[]")
    first_seen = Column(DateTime(timezone=True), nullable=False)
    last_seen = Column(DateTime(timezone=True), nullable=False)
    sighting_count = Column(Float, default=1)
    source_ids_json = Column(Text, default="[]")
    meta_json = Column(Text, default="{}")


class BriefingRow(Base):
    """An auto-generated situation briefing."""

    __tablename__ = "briefings"

    id = Column(String, primary_key=True, default=_new_id)
    title = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    stats_json = Column(Text, default="{}")


# ---------------------------------------------------------------------------
# Pydantic schemas (API request/response)
# ---------------------------------------------------------------------------


class SourceType(StrEnum):
    yolo = "yolo"
    thewire = "thewire"
    manual = "manual"
    mesh = "mesh"


class DetectionIn(BaseModel):
    source_id: str
    label: str
    confidence: float = Field(ge=0.0, le=1.0)
    bbox: list[float] | None = None  # [x, y, w, h]
    lat: float | None = None
    lon: float | None = None
    source_name: str = "yolo"
    detected_at: datetime
    meta: dict[str, Any] = Field(default_factory=dict)


class DetectionOut(BaseModel):
    id: str
    source_id: str
    label: str
    confidence: float
    lat: float | None
    lon: float | None
    source_name: str
    detected_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class IntelReportIn(BaseModel):
    source_id: str
    title: str
    summary: str
    body: str = ""
    source_name: str = "thewire"
    source_url: str = ""
    published_at: datetime
    tags: list[str] = Field(default_factory=list)


class IntelReportOut(BaseModel):
    id: str
    source_id: str
    title: str
    summary: str
    source_name: str
    source_url: str
    published_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class TelemetryIn(BaseModel):
    source_id: str
    device_name: str
    lat: float
    lon: float
    altitude: float | None = None
    heading: float | None = None
    speed: float | None = None
    battery_pct: float | None = None
    recorded_at: datetime
    meta: dict[str, Any] = Field(default_factory=dict)


class TelemetryOut(BaseModel):
    id: str
    source_id: str
    device_name: str
    lat: float
    lon: float
    altitude: float | None
    heading: float | None
    speed: float | None
    battery_pct: float | None
    recorded_at: datetime

    model_config = {"from_attributes": True}


class EntityOut(BaseModel):
    id: str
    canonical_name: str
    entity_type: str
    first_seen: datetime
    last_seen: datetime
    sighting_count: float

    model_config = {"from_attributes": True}


class BriefingOut(BaseModel):
    id: str
    title: str
    body: str
    period_start: datetime
    period_end: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class DashboardStats(BaseModel):
    total_detections: int
    total_intel_reports: int
    total_telemetry_points: int
    total_entities: int
    total_briefings: int
    latest_detection: datetime | None
    latest_intel: datetime | None
