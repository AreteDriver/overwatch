"""Configurable alerting rules engine.

Evaluates user-defined rules against ingest events and creates AlertRow
entries when conditions are met.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from overwatch.models import AlertRow, AlertRuleRow, DetectionRow, EntityRow

log = logging.getLogger(__name__)


def evaluate_rules(
    session: Session,
    event_type: str,
    event_data: dict[str, Any],
) -> list[AlertRow]:
    """Check all enabled rules against an event and create alerts for matches."""
    rules = session.query(AlertRuleRow).filter(AlertRuleRow.enabled == 1).all()
    fired: list[AlertRow] = []

    for rule in rules:
        config = json.loads(rule.config_json or "{}")
        alert = _evaluate_single(session, rule, config, event_type, event_data)
        if alert is not None:
            session.add(alert)
            fired.append(alert)

    if fired:
        session.commit()
    return fired


def _evaluate_single(
    session: Session,
    rule: AlertRuleRow,
    config: dict[str, Any],
    event_type: str,
    event_data: dict[str, Any],
) -> AlertRow | None:
    """Dispatch to the correct rule evaluator."""
    if rule.rule_type == "geofence_entity":
        return _eval_geofence_entity(session, rule, config, event_type, event_data)
    if rule.rule_type == "detection_count":
        return _eval_detection_count(session, rule, config, event_type, event_data)
    if rule.rule_type == "entity_new":
        return _eval_entity_new(session, rule, config, event_type, event_data)
    if rule.rule_type == "custom_field":
        return _eval_custom_field(rule, config, event_type, event_data)
    return None


# ---------------------------------------------------------------------------
# Rule type implementations
# ---------------------------------------------------------------------------


def _eval_geofence_entity(
    session: Session,
    rule: AlertRuleRow,
    config: dict[str, Any],
    event_type: str,
    event_data: dict[str, Any],
) -> AlertRow | None:
    """Alert when a specific entity label enters a specific geofence.

    Config: {"label": "person", "geofence_id": "abc"}
    """
    if event_type != "detection":
        return None

    required_label = config.get("label", "")
    geofence_id = config.get("geofence_id", "")
    if not required_label or not geofence_id:
        return None

    if event_data.get("label") != required_label:
        return None

    lat = event_data.get("lat")
    lon = event_data.get("lon")
    if lat is None or lon is None:
        return None

    # Import here to avoid circular dependency
    from overwatch.analysis.alerts import _point_in_polygon
    from overwatch.models import GeofenceRow

    gf = session.query(GeofenceRow).filter(GeofenceRow.id == geofence_id).first()
    if gf is None:
        return None

    coords = json.loads(gf.coords_json or "[]")
    if not _point_in_polygon(lat, lon, coords):
        return None

    return AlertRow(
        alert_type="rule",
        severity="warning",
        title=f"Rule '{rule.name}': {required_label} in zone {gf.name}",
        body=f"Detected at ({lat:.4f}, {lon:.4f})",
        source_id=event_data.get("source_id", ""),
        lat=lat,
        lon=lon,
        meta_json=json.dumps({"rule_id": rule.id, "geofence_id": geofence_id}),
    )


def _eval_detection_count(
    session: Session,
    rule: AlertRuleRow,
    config: dict[str, Any],
    event_type: str,
    event_data: dict[str, Any],
) -> AlertRow | None:
    """Alert when >N detections of a label occur in T minutes.

    Config: {"label": "drone", "count": 5, "window_minutes": 10}
    """
    if event_type != "detection":
        return None

    required_label = config.get("label", "")
    threshold = config.get("count", 0)
    window_minutes = config.get("window_minutes", 10)
    if not required_label or threshold <= 0:
        return None

    if event_data.get("label") != required_label:
        return None

    cutoff = datetime.now(UTC) - timedelta(minutes=window_minutes)
    count = (
        session.query(DetectionRow)
        .filter(
            DetectionRow.label == required_label,
            DetectionRow.detected_at >= cutoff,
        )
        .count()
    )

    if count <= threshold:
        return None

    return AlertRow(
        alert_type="rule",
        severity="warning",
        title=f"Rule '{rule.name}': {count} {required_label} detections in {window_minutes}m",
        body=f"Threshold {threshold} exceeded",
        source_id=event_data.get("source_id", ""),
        lat=event_data.get("lat"),
        lon=event_data.get("lon"),
        meta_json=json.dumps({"rule_id": rule.id, "count": count}),
    )


def _eval_entity_new(
    session: Session,
    rule: AlertRuleRow,
    config: dict[str, Any],
    event_type: str,
    event_data: dict[str, Any],
) -> AlertRow | None:
    """Alert when a never-before-seen entity type appears.

    Config: {"entity_type": "vehicle"}
    Fires on detection events where the label matches the entity_type
    and no EntityRow of that type exists yet.
    """
    if event_type != "detection":
        return None

    target_type = config.get("entity_type", "")
    if not target_type:
        return None

    if event_data.get("label") != target_type:
        return None

    exists = session.query(EntityRow).filter(EntityRow.entity_type == target_type).first()
    if exists is not None:
        return None

    return AlertRow(
        alert_type="rule",
        severity="info",
        title=f"Rule '{rule.name}': new entity type '{target_type}' detected",
        body=f"Source: {event_data.get('source_name', 'unknown')}",
        source_id=event_data.get("source_id", ""),
        lat=event_data.get("lat"),
        lon=event_data.get("lon"),
        meta_json=json.dumps({"rule_id": rule.id, "entity_type": target_type}),
    )


def _eval_custom_field(
    rule: AlertRuleRow,
    config: dict[str, Any],
    event_type: str,
    event_data: dict[str, Any],
) -> AlertRow | None:
    """Alert when a detection's meta field matches a condition.

    Config: {"field": "model_version", "operator": "eq", "value": "yolov8n"}
    Supported operators: eq, ne, gt, lt, gte, lte, contains
    """
    if event_type != "detection":
        return None

    field = config.get("field", "")
    operator = config.get("operator", "eq")
    expected = config.get("value")
    if not field or expected is None:
        return None

    meta = event_data.get("meta", {})
    actual = meta.get(field)
    if actual is None:
        return None

    matched = _compare(actual, operator, expected)
    if not matched:
        return None

    return AlertRow(
        alert_type="rule",
        severity="info",
        title=f"Rule '{rule.name}': {field} {operator} {expected}",
        body=f"Actual value: {actual}",
        source_id=event_data.get("source_id", ""),
        lat=event_data.get("lat"),
        lon=event_data.get("lon"),
        meta_json=json.dumps({"rule_id": rule.id, "field": field, "actual": actual}),
    )


def _compare(actual: Any, operator: str, expected: Any) -> bool:
    """Compare two values using the given operator."""
    if operator == "eq":
        return str(actual) == str(expected)
    if operator == "ne":
        return str(actual) != str(expected)
    if operator == "contains":
        return str(expected) in str(actual)
    # Numeric comparisons
    try:
        a, e = float(actual), float(expected)
    except (ValueError, TypeError):
        return False
    if operator == "gt":
        return a > e
    if operator == "lt":
        return a < e
    if operator == "gte":
        return a >= e
    if operator == "lte":
        return a <= e
    return False
