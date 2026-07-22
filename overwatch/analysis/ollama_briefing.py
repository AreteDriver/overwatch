"""Ollama-powered enhanced briefing generation.

Uses the local Ollama API to generate LLM-summarized situation reports.
Falls back to template briefings if Ollama is unavailable.

For production, replace with Animus-orchestrated generation which adds:
  - Persistent memory across sessions
  - Multi-model routing (Ollama for small, Anthropic for large)
  - Tool orchestration and proactive checks
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from overwatch.analysis.briefing import (
    _gather_briefing_context,
)
from overwatch.analysis.briefing import (
    generate_briefing as template_briefing,
)
from overwatch.config import (
    BRIEFING_LOOKBACK_HOURS,
    OLLAMA_ENABLED,
    OLLAMA_MODEL,
    OLLAMA_URL,
)
from overwatch.models import BriefingRow

log = logging.getLogger(__name__)


def generate_ollama_briefing(
    session: Session,
    lookback_hours: int | None = None,
) -> BriefingRow:
    """Generate a briefing using Ollama LLM, falling back to templates."""
    if not OLLAMA_ENABLED:
        return template_briefing(session, lookback_hours)

    hours = lookback_hours or BRIEFING_LOOKBACK_HOURS
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    now = datetime.now(UTC)

    ctx = _gather_briefing_context(session, cutoff)
    detections = ctx.detections
    intel_reports = ctx.intel_reports
    telemetry = ctx.telemetry
    entities = ctx.entities

    # Build context for LLM
    context_parts = []
    if detections:
        labels = {}
        for d in detections:
            labels[d.label] = labels.get(d.label, 0) + 1
        det_str = ", ".join(f"{v}x {k}" for k, v in labels.items())
        context_parts.append(f"DETECTIONS ({len(detections)}): {det_str}")

    if intel_reports:
        intel_str = "\n".join(
            f"- [{r.source_name}] {r.title}: {r.summary[:100]}" for r in intel_reports[:5]
        )
        context_parts.append(f"INTEL REPORTS ({len(intel_reports)}):\n{intel_str}")

    if telemetry:
        devices = {t.device_name for t in telemetry}
        low_batt = [t for t in telemetry if t.battery_pct and t.battery_pct < 20]
        telem_str = f"{len(devices)} devices: {', '.join(devices)}"
        if low_batt:
            telem_str += f". WARNING: {len(low_batt)} low battery"
        context_parts.append(f"TELEMETRY: {telem_str}")

    if entities:
        ent_str = ", ".join(f"{e.canonical_name} ({e.entity_type})" for e in entities[:5])
        context_parts.append(f"ENTITIES: {ent_str}")

    context = "\n\n".join(context_parts)

    prompt = (
        "You are a military intelligence analyst. Generate a concise SITREP "
        "(situation report) from the following data. Use markdown formatting. "
        "Include: summary, key findings, threat assessment, and recommendations.\n\n"
        f"Period: last {hours} hours\n"
        f"Data:\n{context}\n\n"
        "Generate the SITREP:"
    )

    try:
        resp = httpx.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
            },
            timeout=60,
        )
        resp.raise_for_status()
        body = resp.json().get("response", "")
        if not body.strip():
            raise ValueError("Empty response from Ollama")
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        log.warning("Ollama briefing failed (%s), falling back to template", exc)
        return template_briefing(session, lookback_hours)

    briefing = BriefingRow(
        title=f"SITREP {now.strftime('%Y-%m-%d %H:%M')} UTC [LLM]",
        body=body,
        period_start=cutoff,
        period_end=now,
        stats_json=json.dumps(
            {
                "detections": len(detections),
                "intel_reports": len(intel_reports),
                "telemetry_points": len(telemetry),
                "entities": len(entities),
                "model": OLLAMA_MODEL,
                "source": "ollama",
            }
        ),
    )
    session.add(briefing)
    session.commit()
    log.info("Generated Ollama briefing %s", briefing.id)
    return briefing
