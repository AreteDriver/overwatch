"""Auto-briefing generation from aggregated data.

This is a template-based implementation. For production, replace with
Animus-orchestrated LLM briefing generation which provides:
  - Persistent memory across sessions
  - Context-aware summarization via Ollama or Anthropic
  - Tool orchestration (37 tools, 6 proactive checks)
  - Priority-ranked intel delivery
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import desc
from sqlalchemy.orm import Session

from overwatch.config import BRIEFING_LOOKBACK_HOURS, BRIEFING_MAX_ITEMS
from overwatch.models import (
    BriefingRow,
    DetectionRow,
    EntityRow,
    IntelReportRow,
    TelemetryRow,
)

log = logging.getLogger(__name__)


@dataclass
class BriefingContext:
    """Aggregated data context for briefing generation."""

    detections: list[DetectionRow]
    intel_reports: list[IntelReportRow]
    telemetry: list[TelemetryRow]
    entities: list[EntityRow]


def _gather_briefing_context(
    session: Session,
    cutoff: datetime,
    max_items: int = BRIEFING_MAX_ITEMS,
    entity_limit: int = 10,
) -> BriefingContext:
    """Gather recent data for briefing generation."""
    detections = (
        session.query(DetectionRow)
        .filter(DetectionRow.detected_at >= cutoff)
        .order_by(desc(DetectionRow.detected_at))
        .limit(max_items)
        .all()
    )

    intel_reports = (
        session.query(IntelReportRow)
        .filter(IntelReportRow.published_at >= cutoff)
        .order_by(desc(IntelReportRow.published_at))
        .limit(max_items)
        .all()
    )

    telemetry = (
        session.query(TelemetryRow)
        .filter(TelemetryRow.recorded_at >= cutoff)
        .order_by(desc(TelemetryRow.recorded_at))
        .limit(max_items)
        .all()
    )

    entities = (
        session.query(EntityRow)
        .filter(EntityRow.last_seen >= cutoff)
        .order_by(desc(EntityRow.sighting_count))
        .limit(entity_limit)
        .all()
    )

    return BriefingContext(
        detections=detections,
        intel_reports=intel_reports,
        telemetry=telemetry,
        entities=entities,
    )


def generate_briefing(
    session: Session,
    lookback_hours: int | None = None,
) -> BriefingRow:
    """Generate a situation briefing from recent data."""
    hours = lookback_hours or BRIEFING_LOOKBACK_HOURS
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    now = datetime.now(UTC)

    ctx = _gather_briefing_context(session, cutoff)
    detections = ctx.detections
    intel_reports = ctx.intel_reports
    telemetry = ctx.telemetry
    entities = ctx.entities

    # Build detection summary
    label_counts: dict[str, int] = {}
    for det in detections:
        label_counts[det.label] = label_counts.get(det.label, 0) + 1
    det_summary = ", ".join(
        f"{v}x {k}" for k, v in sorted(label_counts.items(), key=lambda x: -x[1])
    )

    # Build telemetry summary
    devices = {t.device_name for t in telemetry}
    low_battery = [t for t in telemetry if t.battery_pct is not None and t.battery_pct < 20]

    # Build entity summary
    entity_lines = []
    for e in entities[:5]:
        entity_lines.append(
            f"  - {e.canonical_name} ({e.entity_type}): {int(e.sighting_count)} sightings"
        )

    # Build intel summary
    intel_lines = []
    for report in intel_reports[:5]:
        intel_lines.append(f"  - [{report.source_name}] {report.title}")

    # Compose briefing
    sections = []

    sections.append("# Situation Briefing")
    sections.append(
        f"**Period**: {cutoff.strftime('%Y-%m-%d %H:%M')} to {now.strftime('%Y-%m-%d %H:%M')} UTC"
    )
    sections.append(f"**Generated**: {now.strftime('%Y-%m-%d %H:%M')} UTC\n")

    # Detection section
    sections.append("## Detection Summary")
    if detections:
        sections.append(f"{len(detections)} detections in the last {hours}h: {det_summary}")
    else:
        sections.append("No detections in this period.")

    # Intel section
    sections.append("\n## Intel Feed")
    if intel_reports:
        sections.append(f"{len(intel_reports)} reports received:")
        sections.extend(intel_lines)
    else:
        sections.append("No intel reports in this period.")

    # Telemetry section
    sections.append("\n## Asset Status")
    if telemetry:
        sections.append(
            f"{len(telemetry)} telemetry points from {len(devices)} device(s): "
            f"{', '.join(sorted(devices))}"
        )
        if low_battery:
            sections.append(f"**WARNING**: {len(low_battery)} low battery reading(s)")
    else:
        sections.append("No telemetry in this period.")

    # Entity section
    sections.append("\n## Tracked Entities")
    if entities:
        sections.append(f"{len(entities)} active entities:")
        sections.extend(entity_lines)
    else:
        sections.append("No entities tracked in this period.")

    # Integration callout
    sections.append("\n---")
    sections.append(
        "*Enhanced briefings available with [Animus](https://github.com/AreteDriver/animus)"
        " — LLM-orchestrated summaries with persistent memory and context-aware prioritization.*"
    )

    body = "\n".join(sections)

    stats = {
        "detections": len(detections),
        "intel_reports": len(intel_reports),
        "telemetry_points": len(telemetry),
        "entities": len(entities),
        "devices": list(devices),
        "label_counts": label_counts,
    }

    briefing = BriefingRow(
        title=f"SITREP {now.strftime('%Y-%m-%d %H:%M')} UTC",
        body=body,
        period_start=cutoff,
        period_end=now,
        stats_json=json.dumps(stats),
    )
    session.add(briefing)
    session.commit()
    log.info(
        "Generated briefing %s: %d det, %d intel, %d telem",
        briefing.id,
        len(detections),
        len(intel_reports),
        len(telemetry),
    )
    return briefing


def get_latest_briefing(session: Session) -> BriefingRow | None:
    """Return the most recent briefing."""
    return session.query(BriefingRow).order_by(desc(BriefingRow.created_at)).first()
