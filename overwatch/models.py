"""SQLAlchemy models and Pydantic schemas."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import Boolean, Column, DateTime, Float, Index, Integer, String, Text
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


class GeofenceRow(Base):
    """A named geofence zone (polygon)."""

    __tablename__ = "geofences"

    id = Column(String, primary_key=True, default=_new_id)
    name = Column(String, nullable=False)
    coords_json = Column(Text, nullable=False)  # [[lat,lon], ...]
    alert_on_enter = Column(Boolean, default=True)
    alert_on_exit = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)


class WebhookRow(Base):
    """An external webhook subscription."""

    __tablename__ = "webhooks"

    id = Column(String, primary_key=True, default=_new_id)
    url = Column(String, nullable=False)
    event_types = Column(Text, nullable=False, default="[]")  # JSON list
    secret = Column(String, default="")
    active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    last_delivered_at = Column(DateTime(timezone=True), nullable=True)
    failure_count = Column(Integer, default=0)


class AlertRow(Base):
    """A triggered alert."""

    __tablename__ = "alerts"

    id = Column(String, primary_key=True, default=_new_id)
    alert_type = Column(String, nullable=False)  # geofence, low_battery, high_conf, entity_new
    severity = Column(String, default="warning")  # info, warning, critical
    title = Column(String, nullable=False)
    body = Column(Text, default="")
    source_id = Column(String, default="")
    lat = Column(Float)
    lon = Column(Float)
    acknowledged = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    meta_json = Column(Text, default="{}")


class ApiKeyRow(Base):
    """A scoped API key for multi-user auth."""

    __tablename__ = "api_keys"

    id = Column(String, primary_key=True, default=_new_id)
    name = Column(String, nullable=False)
    key_hash = Column(String, nullable=False, unique=True)
    scopes_json = Column(Text, nullable=False, default='["read"]')
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    active = Column(Boolean, default=True)

    @property
    def scopes(self) -> list[str]:
        return json.loads(self.scopes_json or "[]")

    @scopes.setter
    def scopes(self, value: list[str]) -> None:
        self.scopes_json = json.dumps(value)


class RuleType(StrEnum):
    geofence_entity = "geofence_entity"
    detection_count = "detection_count"
    entity_new = "entity_new"
    custom_field = "custom_field"


class AlertRuleRow(Base):
    """A configurable alerting rule."""

    __tablename__ = "alert_rules"

    id = Column(String, primary_key=True, default=_new_id)
    name = Column(String, nullable=False)
    rule_type = Column(String, nullable=False)  # RuleType values
    enabled = Column(Boolean, default=True)
    config_json = Column(Text, default="{}")
    created_at = Column(DateTime(timezone=True), default=_utcnow)


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
    total_alerts: int = 0
    total_geofences: int = 0
    latest_detection: datetime | None
    latest_intel: datetime | None


class GeofenceIn(BaseModel):
    name: str
    coords: list[list[float]]  # [[lat, lon], ...]
    alert_on_enter: bool = True
    alert_on_exit: bool = False


class GeofenceOut(BaseModel):
    id: str
    name: str
    coords: list[list[float]] = Field(default_factory=list)
    alert_on_enter: bool = True
    alert_on_exit: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class AlertOut(BaseModel):
    id: str
    alert_type: str
    severity: str
    title: str
    body: str
    source_id: str
    lat: float | None
    lon: float | None
    acknowledged: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class WebhookIn(BaseModel):
    url: str
    event_types: list[str] = Field(
        default_factory=lambda: ["detection", "intel", "telemetry", "alert"]
    )
    secret: str | None = None


class WebhookOut(BaseModel):
    id: str
    url: str
    event_types: list[str] = Field(default_factory=list)
    active: bool = True
    created_at: datetime
    last_delivered_at: datetime | None = None
    failure_count: int = 0

    model_config = {"from_attributes": True}


class ApiKeyScope(StrEnum):
    read = "read"
    write = "write"
    admin = "admin"


class ApiKeyCreate(BaseModel):
    name: str
    scopes: list[ApiKeyScope] = Field(default_factory=lambda: [ApiKeyScope.read])


class ApiKeyOut(BaseModel):
    id: str
    name: str
    scopes: list[str] = Field(default_factory=list)
    created_at: datetime
    last_used_at: datetime | None = None
    active: bool = True

    model_config = {"from_attributes": True}


class ApiKeyCreated(BaseModel):
    """Returned once on creation — includes the raw key (never stored)."""

    id: str
    name: str
    key: str
    scopes: list[str]
    created_at: datetime


class DeviceHealth(BaseModel):
    device_name: str
    last_seen: datetime
    lat: float
    lon: float
    battery_pct: float | None
    altitude: float | None
    speed: float | None
    staleness_seconds: float
    status: str  # online, stale, offline


class EntityTimelineEntry(BaseModel):
    source_type: str  # detection, intel
    source_id: str
    label: str
    timestamp: datetime
    lat: float | None = None
    lon: float | None = None


class ReplayFrame(BaseModel):
    timestamp: datetime
    detections: list[DetectionOut] = Field(default_factory=list)
    telemetry: list[TelemetryOut] = Field(default_factory=list)
    intel: list[IntelReportOut] = Field(default_factory=list)
    speed: float = 1.0
    event_types: list[str] = Field(default_factory=list)


class ReplaySummary(BaseModel):
    start: datetime
    end: datetime
    detections: int = 0
    telemetry: int = 0
    intel: int = 0


class AlertRuleIn(BaseModel):
    name: str
    rule_type: RuleType
    config: dict[str, Any] = Field(default_factory=dict)


class AlertRuleUpdate(BaseModel):
    name: str | None = None
    rule_type: RuleType | None = None
    enabled: bool | None = None
    config: dict[str, Any] | None = None


class AlertRuleOut(BaseModel):
    id: str
    name: str
    rule_type: str
    enabled: bool
    config: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    model_config = {"from_attributes": True}
