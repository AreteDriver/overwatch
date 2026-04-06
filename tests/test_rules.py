"""Tests for the alerting rules engine."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from overwatch.analysis.rules import evaluate_rules
from overwatch.api.routes import _get_session
from overwatch.app import app
from overwatch.models import (
    AlertRuleRow,
    Base,
    DetectionRow,
    EntityRow,
    GeofenceRow,
)


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


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_session():
        sess = factory()
        try:
            yield sess
        finally:
            sess.close()

    with TestClient(app) as c:
        app.dependency_overrides[_get_session] = override_session
        app.state.session_factory = factory
        app.state.engine = engine
        yield c, factory

    app.dependency_overrides.clear()
    engine.dispose()


class TestGeofenceEntityRule:
    def test_fires_when_label_in_geofence(self, session):
        gf = GeofenceRow(
            id="gf-1",
            name="Zone Alpha",
            coords_json=json.dumps([[45.0, 13.0], [47.0, 13.0], [47.0, 15.0], [45.0, 15.0]]),
        )
        session.add(gf)
        rule = AlertRuleRow(
            name="person in zone alpha",
            rule_type="geofence_entity",
            enabled=1,
            config_json=json.dumps({"label": "person", "geofence_id": "gf-1"}),
        )
        session.add(rule)
        session.commit()

        alerts = evaluate_rules(
            session,
            "detection",
            {
                "label": "person",
                "lat": 46.0,
                "lon": 14.0,
                "source_id": "det-1",
            },
        )
        assert len(alerts) == 1
        assert "Zone Alpha" in alerts[0].title

    def test_no_fire_wrong_label(self, session):
        gf = GeofenceRow(
            id="gf-1",
            name="Zone Alpha",
            coords_json=json.dumps([[45.0, 13.0], [47.0, 13.0], [47.0, 15.0], [45.0, 15.0]]),
        )
        session.add(gf)
        rule = AlertRuleRow(
            name="person only",
            rule_type="geofence_entity",
            enabled=1,
            config_json=json.dumps({"label": "person", "geofence_id": "gf-1"}),
        )
        session.add(rule)
        session.commit()

        alerts = evaluate_rules(
            session,
            "detection",
            {
                "label": "vehicle",
                "lat": 46.0,
                "lon": 14.0,
                "source_id": "det-2",
            },
        )
        assert len(alerts) == 0

    def test_no_fire_outside_geofence(self, session):
        gf = GeofenceRow(
            id="gf-1",
            name="Zone Alpha",
            coords_json=json.dumps([[45.0, 13.0], [47.0, 13.0], [47.0, 15.0], [45.0, 15.0]]),
        )
        session.add(gf)
        rule = AlertRuleRow(
            name="person in zone alpha",
            rule_type="geofence_entity",
            enabled=1,
            config_json=json.dumps({"label": "person", "geofence_id": "gf-1"}),
        )
        session.add(rule)
        session.commit()

        alerts = evaluate_rules(
            session,
            "detection",
            {
                "label": "person",
                "lat": 50.0,
                "lon": 20.0,
                "source_id": "det-3",
            },
        )
        assert len(alerts) == 0


class TestDetectionCountRule:
    def test_fires_when_threshold_exceeded(self, session):
        now = datetime.now(UTC)
        for i in range(6):
            session.add(
                DetectionRow(
                    source_id=f"det-{i}",
                    label="drone",
                    confidence=0.9,
                    detected_at=now - timedelta(minutes=i),
                )
            )
        session.commit()

        rule = AlertRuleRow(
            name="drone swarm",
            rule_type="detection_count",
            enabled=1,
            config_json=json.dumps({"label": "drone", "count": 5, "window_minutes": 10}),
        )
        session.add(rule)
        session.commit()

        alerts = evaluate_rules(
            session,
            "detection",
            {
                "label": "drone",
                "source_id": "det-trigger",
            },
        )
        assert len(alerts) == 1
        assert "drone" in alerts[0].title

    def test_no_fire_below_threshold(self, session):
        now = datetime.now(UTC)
        for i in range(3):
            session.add(
                DetectionRow(
                    source_id=f"det-{i}",
                    label="drone",
                    confidence=0.9,
                    detected_at=now - timedelta(minutes=i),
                )
            )
        session.commit()

        rule = AlertRuleRow(
            name="drone swarm",
            rule_type="detection_count",
            enabled=1,
            config_json=json.dumps({"label": "drone", "count": 5, "window_minutes": 10}),
        )
        session.add(rule)
        session.commit()

        alerts = evaluate_rules(
            session,
            "detection",
            {
                "label": "drone",
                "source_id": "det-x",
            },
        )
        assert len(alerts) == 0


class TestEntityNewRule:
    def test_fires_for_new_entity_type(self, session):
        rule = AlertRuleRow(
            name="new vehicle",
            rule_type="entity_new",
            enabled=1,
            config_json=json.dumps({"entity_type": "vehicle"}),
        )
        session.add(rule)
        session.commit()

        alerts = evaluate_rules(
            session,
            "detection",
            {
                "label": "vehicle",
                "source_id": "det-v1",
            },
        )
        assert len(alerts) == 1

    def test_no_fire_if_entity_exists(self, session):
        session.add(
            EntityRow(
                canonical_name="truck-1",
                entity_type="vehicle",
                first_seen=datetime.now(UTC),
                last_seen=datetime.now(UTC),
            )
        )
        rule = AlertRuleRow(
            name="new vehicle",
            rule_type="entity_new",
            enabled=1,
            config_json=json.dumps({"entity_type": "vehicle"}),
        )
        session.add(rule)
        session.commit()

        alerts = evaluate_rules(
            session,
            "detection",
            {
                "label": "vehicle",
                "source_id": "det-v2",
            },
        )
        assert len(alerts) == 0


class TestCustomFieldRule:
    def test_eq_match(self, session):
        rule = AlertRuleRow(
            name="yolov8 check",
            rule_type="custom_field",
            enabled=1,
            config_json=json.dumps({"field": "model", "operator": "eq", "value": "yolov8n"}),
        )
        session.add(rule)
        session.commit()

        alerts = evaluate_rules(
            session,
            "detection",
            {
                "label": "person",
                "source_id": "det-m1",
                "meta": {"model": "yolov8n"},
            },
        )
        assert len(alerts) == 1

    def test_no_match(self, session):
        rule = AlertRuleRow(
            name="yolov8 check",
            rule_type="custom_field",
            enabled=1,
            config_json=json.dumps({"field": "model", "operator": "eq", "value": "yolov8n"}),
        )
        session.add(rule)
        session.commit()

        alerts = evaluate_rules(
            session,
            "detection",
            {
                "label": "person",
                "source_id": "det-m2",
                "meta": {"model": "yolov5s"},
            },
        )
        assert len(alerts) == 0


class TestDisabledRule:
    def test_disabled_rule_not_evaluated(self, session):
        rule = AlertRuleRow(
            name="disabled",
            rule_type="entity_new",
            enabled=0,
            config_json=json.dumps({"entity_type": "vehicle"}),
        )
        session.add(rule)
        session.commit()

        alerts = evaluate_rules(
            session,
            "detection",
            {
                "label": "vehicle",
                "source_id": "det-d1",
            },
        )
        assert len(alerts) == 0


class TestRulesCRUD:
    def test_create_rule(self, client):
        c, _ = client
        resp = c.post(
            "/api/rules",
            json={
                "name": "test rule",
                "rule_type": "detection_count",
                "config": {"label": "drone", "count": 3, "window_minutes": 5},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "test rule"
        assert data["enabled"] is True

    def test_list_rules(self, client):
        c, _ = client
        c.post(
            "/api/rules",
            json={
                "name": "rule A",
                "rule_type": "entity_new",
                "config": {"entity_type": "person"},
            },
        )
        resp = c.get("/api/rules")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_update_rule(self, client):
        c, _ = client
        create = c.post(
            "/api/rules",
            json={
                "name": "updatable",
                "rule_type": "entity_new",
                "config": {"entity_type": "person"},
            },
        )
        rule_id = create.json()["id"]

        resp = c.put(f"/api/rules/{rule_id}", json={"enabled": False})
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

    def test_delete_rule(self, client):
        c, _ = client
        create = c.post(
            "/api/rules",
            json={
                "name": "deletable",
                "rule_type": "entity_new",
                "config": {"entity_type": "drone"},
            },
        )
        rule_id = create.json()["id"]

        resp = c.delete(f"/api/rules/{rule_id}")
        assert resp.status_code == 200

        resp = c.delete(f"/api/rules/{rule_id}")
        assert resp.status_code == 404
