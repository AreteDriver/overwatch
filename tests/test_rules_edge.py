"""Edge-case tests for overwatch.analysis.rules — _compare and rule evaluators."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from overwatch.analysis.rules import _compare, _evaluate_single, evaluate_rules
from overwatch.models import (
    AlertRuleRow,
    Base,
    DetectionRow,
    EntityRow,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session(engine):
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    sess = factory()
    yield sess
    sess.close()


def _make_rule(session, *, rule_type, name="test-rule", config=None):
    """Helper to insert an enabled alert rule."""
    rule = AlertRuleRow(
        name=name,
        rule_type=rule_type,
        enabled=True,
        config_json=json.dumps(config or {}),
    )
    session.add(rule)
    session.commit()
    return rule


# ---------------------------------------------------------------------------
# _compare operator tests
# ---------------------------------------------------------------------------


class TestCompareOperators:
    """Test _compare() with all supported operators."""

    def test_eq_match(self):
        assert _compare("yolov8n", "eq", "yolov8n") is True

    def test_eq_mismatch(self):
        assert _compare("yolov8n", "eq", "yolov5s") is False

    def test_eq_coerces_to_string(self):
        assert _compare(42, "eq", "42") is True

    def test_ne_match(self):
        assert _compare("a", "ne", "b") is True

    def test_ne_mismatch(self):
        assert _compare("same", "ne", "same") is False

    def test_gt(self):
        assert _compare(10, "gt", 5) is True
        assert _compare(5, "gt", 10) is False

    def test_lt(self):
        assert _compare(3, "lt", 7) is True
        assert _compare(7, "lt", 3) is False

    def test_gte(self):
        assert _compare(10, "gte", 10) is True
        assert _compare(10, "gte", 11) is False

    def test_lte(self):
        assert _compare(5, "lte", 5) is True
        assert _compare(6, "lte", 5) is False

    def test_contains(self):
        assert _compare("hello world", "contains", "world") is True
        assert _compare("hello", "contains", "xyz") is False

    def test_non_numeric_gt_returns_false(self):
        assert _compare("abc", "gt", "def") is False

    def test_non_numeric_lt_returns_false(self):
        assert _compare("abc", "lt", "def") is False

    def test_non_numeric_gte_returns_false(self):
        assert _compare("abc", "gte", "def") is False

    def test_non_numeric_lte_returns_false(self):
        assert _compare("abc", "lte", "def") is False

    def test_unknown_operator_returns_false(self):
        assert _compare(1, "xor", 1) is False

    def test_none_actual_numeric_returns_false(self):
        assert _compare(None, "gt", 5) is False


# ---------------------------------------------------------------------------
# geofence_entity edge cases
# ---------------------------------------------------------------------------


class TestGeofenceEntityEdges:
    def test_missing_geofence_does_not_fire(self, session):
        rule = _make_rule(
            session,
            rule_type="geofence_entity",
            config={"label": "person", "geofence_id": "nonexistent-id"},
        )
        config = json.loads(rule.config_json)
        event_data = {"label": "person", "lat": 46.05, "lon": 14.5, "source_id": "s1"}

        result = _evaluate_single(session, rule, config, "detection", event_data)
        assert result is None

    def test_no_coords_on_detection_does_not_fire(self, session):
        rule = _make_rule(
            session,
            rule_type="geofence_entity",
            config={"label": "person", "geofence_id": "gf1"},
        )
        config = json.loads(rule.config_json)
        # No lat/lon in event_data
        event_data = {"label": "person", "source_id": "s1"}

        result = _evaluate_single(session, rule, config, "detection", event_data)
        assert result is None

    def test_non_detection_event_does_not_fire(self, session):
        rule = _make_rule(
            session,
            rule_type="geofence_entity",
            config={"label": "person", "geofence_id": "gf1"},
        )
        config = json.loads(rule.config_json)
        event_data = {"label": "person", "lat": 46.05, "lon": 14.5}

        result = _evaluate_single(session, rule, config, "telemetry", event_data)
        assert result is None

    def test_wrong_label_does_not_fire(self, session):
        rule = _make_rule(
            session,
            rule_type="geofence_entity",
            config={"label": "vehicle", "geofence_id": "gf1"},
        )
        config = json.loads(rule.config_json)
        event_data = {"label": "person", "lat": 46.05, "lon": 14.5}

        result = _evaluate_single(session, rule, config, "detection", event_data)
        assert result is None

    def test_empty_label_config_does_not_fire(self, session):
        rule = _make_rule(
            session,
            rule_type="geofence_entity",
            config={"label": "", "geofence_id": "gf1"},
        )
        config = json.loads(rule.config_json)
        event_data = {"label": "person", "lat": 46.05, "lon": 14.5}

        result = _evaluate_single(session, rule, config, "detection", event_data)
        assert result is None


# ---------------------------------------------------------------------------
# detection_count edge cases
# ---------------------------------------------------------------------------


class TestDetectionCountEdges:
    def test_non_detection_event_does_not_fire(self, session):
        rule = _make_rule(
            session,
            rule_type="detection_count",
            config={"label": "drone", "count": 5, "window_minutes": 10},
        )
        config = json.loads(rule.config_json)
        event_data = {"label": "drone"}

        result = _evaluate_single(session, rule, config, "intel", event_data)
        assert result is None

    def test_below_threshold_does_not_fire(self, session):
        rule = _make_rule(
            session,
            rule_type="detection_count",
            config={"label": "drone", "count": 5, "window_minutes": 10},
        )
        config = json.loads(rule.config_json)
        # Add 3 recent detections (below threshold of 5)
        now = datetime.now(UTC)
        for i in range(3):
            session.add(
                DetectionRow(
                    source_id=f"dc-{i}",
                    label="drone",
                    confidence=0.9,
                    detected_at=now - timedelta(minutes=1),
                )
            )
        session.commit()

        event_data = {"label": "drone", "source_id": "dc-new"}
        result = _evaluate_single(session, rule, config, "detection", event_data)
        assert result is None

    def test_above_threshold_fires(self, session):
        rule = _make_rule(
            session,
            rule_type="detection_count",
            config={"label": "drone", "count": 2, "window_minutes": 10},
        )
        config = json.loads(rule.config_json)
        now = datetime.now(UTC)
        for i in range(5):
            session.add(
                DetectionRow(
                    source_id=f"dc-fire-{i}",
                    label="drone",
                    confidence=0.9,
                    detected_at=now - timedelta(minutes=1),
                )
            )
        session.commit()

        event_data = {"label": "drone", "source_id": "dc-fire-new"}
        result = _evaluate_single(session, rule, config, "detection", event_data)
        assert result is not None
        assert "drone" in result.title

    def test_wrong_label_does_not_fire(self, session):
        rule = _make_rule(
            session,
            rule_type="detection_count",
            config={"label": "drone", "count": 1, "window_minutes": 10},
        )
        config = json.loads(rule.config_json)
        event_data = {"label": "person"}

        result = _evaluate_single(session, rule, config, "detection", event_data)
        assert result is None


# ---------------------------------------------------------------------------
# custom_field edge cases
# ---------------------------------------------------------------------------


class TestCustomFieldEdges:
    def test_missing_meta_field_does_not_fire(self, session):
        rule = _make_rule(
            session,
            rule_type="custom_field",
            config={"field": "model_version", "operator": "eq", "value": "yolov8n"},
        )
        config = json.loads(rule.config_json)
        # meta has no "model_version" key
        event_data = {"label": "person", "meta": {"other_field": "x"}}

        result = _evaluate_single(session, rule, config, "detection", event_data)
        assert result is None

    def test_missing_meta_entirely_does_not_fire(self, session):
        rule = _make_rule(
            session,
            rule_type="custom_field",
            config={"field": "model_version", "operator": "eq", "value": "yolov8n"},
        )
        config = json.loads(rule.config_json)
        event_data = {"label": "person"}

        result = _evaluate_single(session, rule, config, "detection", event_data)
        assert result is None

    def test_non_detection_event_does_not_fire(self, session):
        rule = _make_rule(
            session,
            rule_type="custom_field",
            config={"field": "model_version", "operator": "eq", "value": "yolov8n"},
        )
        config = json.loads(rule.config_json)
        event_data = {"meta": {"model_version": "yolov8n"}}

        result = _evaluate_single(session, rule, config, "telemetry", event_data)
        assert result is None

    def test_matching_custom_field_fires(self, session):
        rule = _make_rule(
            session,
            rule_type="custom_field",
            config={"field": "model_version", "operator": "eq", "value": "yolov8n"},
        )
        config = json.loads(rule.config_json)
        event_data = {
            "label": "person",
            "meta": {"model_version": "yolov8n"},
            "source_id": "s1",
        }

        result = _evaluate_single(session, rule, config, "detection", event_data)
        assert result is not None
        assert "model_version" in result.title

    def test_mismatched_value_does_not_fire(self, session):
        rule = _make_rule(
            session,
            rule_type="custom_field",
            config={"field": "model_version", "operator": "eq", "value": "yolov8n"},
        )
        config = json.loads(rule.config_json)
        event_data = {"meta": {"model_version": "yolov5s"}}

        result = _evaluate_single(session, rule, config, "detection", event_data)
        assert result is None

    def test_empty_field_config_does_not_fire(self, session):
        rule = _make_rule(
            session,
            rule_type="custom_field",
            config={"field": "", "operator": "eq", "value": "yolov8n"},
        )
        config = json.loads(rule.config_json)
        event_data = {"meta": {"model_version": "yolov8n"}}

        result = _evaluate_single(session, rule, config, "detection", event_data)
        assert result is None


# ---------------------------------------------------------------------------
# entity_new edge cases
# ---------------------------------------------------------------------------


class TestEntityNewEdges:
    def test_non_detection_event_does_not_fire(self, session):
        rule = _make_rule(
            session,
            rule_type="entity_new",
            config={"entity_type": "vehicle"},
        )
        config = json.loads(rule.config_json)
        event_data = {"label": "vehicle"}

        result = _evaluate_single(session, rule, config, "intel", event_data)
        assert result is None

    def test_existing_entity_does_not_fire(self, session):
        # Insert existing entity of type "vehicle"
        now = datetime.now(UTC)
        session.add(
            EntityRow(
                canonical_name="SUV-1",
                entity_type="vehicle",
                first_seen=now,
                last_seen=now,
            )
        )
        session.commit()

        rule = _make_rule(
            session,
            rule_type="entity_new",
            config={"entity_type": "vehicle"},
        )
        config = json.loads(rule.config_json)
        event_data = {"label": "vehicle", "source_id": "s1"}

        result = _evaluate_single(session, rule, config, "detection", event_data)
        assert result is None

    def test_new_entity_fires(self, session):
        rule = _make_rule(
            session,
            rule_type="entity_new",
            config={"entity_type": "helicopter"},
        )
        config = json.loads(rule.config_json)
        event_data = {
            "label": "helicopter",
            "source_id": "s1",
            "source_name": "cam-north",
        }

        result = _evaluate_single(session, rule, config, "detection", event_data)
        assert result is not None
        assert "helicopter" in result.title

    def test_wrong_label_does_not_fire(self, session):
        rule = _make_rule(
            session,
            rule_type="entity_new",
            config={"entity_type": "vehicle"},
        )
        config = json.loads(rule.config_json)
        event_data = {"label": "person"}

        result = _evaluate_single(session, rule, config, "detection", event_data)
        assert result is None

    def test_empty_entity_type_does_not_fire(self, session):
        rule = _make_rule(
            session,
            rule_type="entity_new",
            config={"entity_type": ""},
        )
        config = json.loads(rule.config_json)
        event_data = {"label": ""}

        result = _evaluate_single(session, rule, config, "detection", event_data)
        assert result is None


# ---------------------------------------------------------------------------
# Unknown rule_type
# ---------------------------------------------------------------------------


class TestUnknownRuleType:
    def test_unknown_rule_type_returns_none(self, session):
        rule = _make_rule(session, rule_type="flux_capacitor", config={})
        config = json.loads(rule.config_json)
        event_data = {"label": "person"}

        result = _evaluate_single(session, rule, config, "detection", event_data)
        assert result is None


# ---------------------------------------------------------------------------
# evaluate_rules integration
# ---------------------------------------------------------------------------


class TestEvaluateRulesIntegration:
    def test_evaluate_rules_commits_fired_alerts(self, session):
        """When rules fire, alerts are committed to the DB."""
        _make_rule(
            session,
            rule_type="entity_new",
            config={"entity_type": "tank"},
        )
        event_data = {"label": "tank", "source_id": "s1", "source_name": "cam-1"}

        alerts = evaluate_rules(session, "detection", event_data)
        assert len(alerts) == 1
        assert alerts[0].alert_type == "rule"

    def test_evaluate_rules_no_match_returns_empty(self, session):
        _make_rule(
            session,
            rule_type="entity_new",
            config={"entity_type": "tank"},
        )
        event_data = {"label": "person"}

        alerts = evaluate_rules(session, "detection", event_data)
        assert alerts == []
