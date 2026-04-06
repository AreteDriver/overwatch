"""Tests for Ollama-powered briefing generation (overwatch.analysis.ollama_briefing)."""

from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import MagicMock, patch

import httpx

from overwatch.models import (
    BriefingRow,
    DetectionRow,
    EntityRow,
    IntelReportRow,
    TelemetryRow,
)

MODULE = "overwatch.analysis.ollama_briefing"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_detections(session, now, count=3):
    rows = []
    for i in range(count):
        row = DetectionRow(
            source_id=f"det-{i}",
            label="person" if i % 2 == 0 else "vehicle",
            confidence=0.95,
            lat=46.0 + i * 0.01,
            lon=14.5,
            detected_at=now - timedelta(hours=1, minutes=i),
        )
        rows.append(row)
        session.add(row)
    session.commit()
    return rows


def _seed_intel(session, now, count=2):
    rows = []
    for i in range(count):
        row = IntelReportRow(
            source_id=f"intel-{i}",
            title=f"Report Alpha-{i}",
            summary=f"Summary of intel report {i} with important details",
            source_name="thewire",
            published_at=now - timedelta(hours=1, minutes=i),
        )
        rows.append(row)
        session.add(row)
    session.commit()
    return rows


def _seed_telemetry(session, now, battery_pct=85.0, device="drone-1"):
    row = TelemetryRow(
        source_id=f"telem-{device}-{battery_pct}",
        device_name=device,
        lat=46.05,
        lon=14.51,
        battery_pct=battery_pct,
        recorded_at=now - timedelta(minutes=10),
    )
    session.add(row)
    session.commit()
    return row


def _seed_entities(session, now, count=2):
    rows = []
    for i in range(count):
        row = EntityRow(
            canonical_name=f"Entity-{i}",
            entity_type="person" if i % 2 == 0 else "vehicle",
            first_seen=now - timedelta(hours=2),
            last_seen=now - timedelta(minutes=5),
            sighting_count=i + 1,
        )
        rows.append(row)
        session.add(row)
    session.commit()
    return rows


def _mock_ollama_response(body_text="# SITREP\nAll clear."):
    """Return a mock httpx.Response with Ollama JSON payload."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"response": body_text}
    return resp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOllamaDisabled:
    """When OLLAMA_ENABLED is False, falls back to template briefing."""

    def test_returns_template_briefing(self, session, now):
        with patch(f"{MODULE}.OLLAMA_ENABLED", False):
            from overwatch.analysis.ollama_briefing import generate_ollama_briefing

            result = generate_ollama_briefing(session)

        assert isinstance(result, BriefingRow)
        assert "[LLM]" not in result.title


class TestOllamaSuccess:
    """Successful Ollama LLM generation."""

    def test_generates_llm_briefing(self, session, now):
        mock_resp = _mock_ollama_response("# SITREP\nSituation normal.")

        with (
            patch(f"{MODULE}.OLLAMA_ENABLED", True),
            patch(f"{MODULE}.httpx.post", return_value=mock_resp) as mock_post,
        ):
            from overwatch.analysis.ollama_briefing import generate_ollama_briefing

            result = generate_ollama_briefing(session)

        assert isinstance(result, BriefingRow)
        assert "[LLM]" in result.title
        assert "SITREP" in result.title
        assert result.body == "# SITREP\nSituation normal."

        stats = json.loads(result.stats_json)
        assert stats["source"] == "ollama"
        assert "model" in stats

        # Verify httpx.post was called with expected args
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert "/api/generate" in call_kwargs.args[0]

    def test_briefing_saved_to_db(self, session, now):
        mock_resp = _mock_ollama_response("# Briefing content")

        with (
            patch(f"{MODULE}.OLLAMA_ENABLED", True),
            patch(f"{MODULE}.httpx.post", return_value=mock_resp),
        ):
            from overwatch.analysis.ollama_briefing import generate_ollama_briefing

            generate_ollama_briefing(session)

        rows = session.query(BriefingRow).all()
        assert len(rows) == 1
        assert "[LLM]" in rows[0].title


class TestOllamaEmptyResponse:
    """Ollama returns empty body -> falls back to template."""

    def test_empty_string_falls_back(self, session, now):
        mock_resp = _mock_ollama_response("")

        with (
            patch(f"{MODULE}.OLLAMA_ENABLED", True),
            patch(f"{MODULE}.httpx.post", return_value=mock_resp),
        ):
            from overwatch.analysis.ollama_briefing import generate_ollama_briefing

            result = generate_ollama_briefing(session)

        assert isinstance(result, BriefingRow)
        assert "[LLM]" not in result.title

    def test_whitespace_only_falls_back(self, session, now):
        mock_resp = _mock_ollama_response("   \n  ")

        with (
            patch(f"{MODULE}.OLLAMA_ENABLED", True),
            patch(f"{MODULE}.httpx.post", return_value=mock_resp),
        ):
            from overwatch.analysis.ollama_briefing import generate_ollama_briefing

            result = generate_ollama_briefing(session)

        assert isinstance(result, BriefingRow)
        assert "[LLM]" not in result.title


class TestOllamaHTTPError:
    """Ollama HTTP errors -> falls back to template."""

    def test_http_error_falls_back(self, session, now):
        with (
            patch(f"{MODULE}.OLLAMA_ENABLED", True),
            patch(
                f"{MODULE}.httpx.post",
                side_effect=httpx.HTTPError("Connection refused"),
            ),
        ):
            from overwatch.analysis.ollama_briefing import generate_ollama_briefing

            result = generate_ollama_briefing(session)

        assert isinstance(result, BriefingRow)
        assert "[LLM]" not in result.title

    def test_timeout_falls_back(self, session, now):
        with (
            patch(f"{MODULE}.OLLAMA_ENABLED", True),
            patch(
                f"{MODULE}.httpx.post",
                side_effect=httpx.ConnectTimeout("Timed out"),
            ),
        ):
            from overwatch.analysis.ollama_briefing import generate_ollama_briefing

            result = generate_ollama_briefing(session)

        assert isinstance(result, BriefingRow)
        assert "[LLM]" not in result.title

    def test_raise_for_status_error(self, session, now):
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500 Server Error",
            request=MagicMock(),
            response=MagicMock(),
        )

        with (
            patch(f"{MODULE}.OLLAMA_ENABLED", True),
            patch(f"{MODULE}.httpx.post", return_value=mock_resp),
        ):
            from overwatch.analysis.ollama_briefing import generate_ollama_briefing

            result = generate_ollama_briefing(session)

        assert isinstance(result, BriefingRow)
        assert "[LLM]" not in result.title


class TestWithDetections:
    """Prompt includes detection summary when detections exist."""

    def test_prompt_includes_detection_counts(self, session, now):
        _seed_detections(session, now, count=4)
        mock_resp = _mock_ollama_response("# SITREP with detections")

        with (
            patch(f"{MODULE}.OLLAMA_ENABLED", True),
            patch(f"{MODULE}.httpx.post", return_value=mock_resp) as mock_post,
        ):
            from overwatch.analysis.ollama_briefing import generate_ollama_briefing

            result = generate_ollama_briefing(session)

        assert "[LLM]" in result.title

        # Verify the prompt sent to Ollama contains detection info
        call_kwargs = mock_post.call_args
        prompt = call_kwargs.kwargs.get("json", call_kwargs[1].get("json", {}))["prompt"]
        assert "DETECTIONS" in prompt
        assert "person" in prompt

        stats = json.loads(result.stats_json)
        assert stats["detections"] == 4


class TestWithIntel:
    """Prompt includes intel titles when intel reports exist."""

    def test_prompt_includes_intel_titles(self, session, now):
        _seed_intel(session, now, count=3)
        mock_resp = _mock_ollama_response("# SITREP with intel")

        with (
            patch(f"{MODULE}.OLLAMA_ENABLED", True),
            patch(f"{MODULE}.httpx.post", return_value=mock_resp) as mock_post,
        ):
            from overwatch.analysis.ollama_briefing import generate_ollama_briefing

            result = generate_ollama_briefing(session)

        call_kwargs = mock_post.call_args
        prompt = call_kwargs.kwargs.get("json", call_kwargs[1].get("json", {}))["prompt"]
        assert "INTEL REPORTS" in prompt
        assert "Report Alpha-0" in prompt

        stats = json.loads(result.stats_json)
        assert stats["intel_reports"] == 3


class TestWithTelemetry:
    """Telemetry data including low battery warnings."""

    def test_normal_battery_no_warning(self, session, now):
        _seed_telemetry(session, now, battery_pct=85.0, device="drone-A")
        mock_resp = _mock_ollama_response("# SITREP telemetry")

        with (
            patch(f"{MODULE}.OLLAMA_ENABLED", True),
            patch(f"{MODULE}.httpx.post", return_value=mock_resp) as mock_post,
        ):
            from overwatch.analysis.ollama_briefing import generate_ollama_briefing

            generate_ollama_briefing(session)

        prompt = mock_post.call_args.kwargs.get("json", mock_post.call_args[1].get("json", {}))[
            "prompt"
        ]
        assert "TELEMETRY" in prompt
        assert "drone-A" in prompt
        assert "WARNING" not in prompt

    def test_low_battery_includes_warning(self, session, now):
        _seed_telemetry(session, now, battery_pct=12.0, device="drone-B")
        mock_resp = _mock_ollama_response("# SITREP low battery")

        with (
            patch(f"{MODULE}.OLLAMA_ENABLED", True),
            patch(f"{MODULE}.httpx.post", return_value=mock_resp) as mock_post,
        ):
            from overwatch.analysis.ollama_briefing import generate_ollama_briefing

            generate_ollama_briefing(session)

        prompt = mock_post.call_args.kwargs.get("json", mock_post.call_args[1].get("json", {}))[
            "prompt"
        ]
        assert "WARNING" in prompt
        assert "low battery" in prompt

    def test_mixed_batteries(self, session, now):
        _seed_telemetry(session, now, battery_pct=90.0, device="healthy")
        _seed_telemetry(session, now, battery_pct=5.0, device="dying")
        mock_resp = _mock_ollama_response("# SITREP mixed")

        with (
            patch(f"{MODULE}.OLLAMA_ENABLED", True),
            patch(f"{MODULE}.httpx.post", return_value=mock_resp) as mock_post,
        ):
            from overwatch.analysis.ollama_briefing import generate_ollama_briefing

            generate_ollama_briefing(session)

        prompt = mock_post.call_args.kwargs.get("json", mock_post.call_args[1].get("json", {}))[
            "prompt"
        ]
        assert "WARNING" in prompt
        assert "1 low battery" in prompt


class TestWithEntities:
    """Prompt includes entity names when entities exist."""

    def test_prompt_includes_entity_names(self, session, now):
        _seed_entities(session, now, count=3)
        mock_resp = _mock_ollama_response("# SITREP entities")

        with (
            patch(f"{MODULE}.OLLAMA_ENABLED", True),
            patch(f"{MODULE}.httpx.post", return_value=mock_resp) as mock_post,
        ):
            from overwatch.analysis.ollama_briefing import generate_ollama_briefing

            result = generate_ollama_briefing(session)

        prompt = mock_post.call_args.kwargs.get("json", mock_post.call_args[1].get("json", {}))[
            "prompt"
        ]
        assert "ENTITIES" in prompt
        assert "Entity-0" in prompt
        assert "person" in prompt

        stats = json.loads(result.stats_json)
        assert stats["entities"] == 3


class TestLookbackHours:
    """Custom lookback hours parameter."""

    def test_custom_lookback_hours(self, session, now):
        mock_resp = _mock_ollama_response("# SITREP custom period")

        with (
            patch(f"{MODULE}.OLLAMA_ENABLED", True),
            patch(f"{MODULE}.httpx.post", return_value=mock_resp) as mock_post,
        ):
            from overwatch.analysis.ollama_briefing import generate_ollama_briefing

            generate_ollama_briefing(session, lookback_hours=6)

        prompt = mock_post.call_args.kwargs.get("json", mock_post.call_args[1].get("json", {}))[
            "prompt"
        ]
        assert "last 6 hours" in prompt

    def test_old_data_excluded(self, session, now):
        """Detections older than lookback window are not included."""
        # Old detection (48h ago)
        session.add(
            DetectionRow(
                source_id="old-det",
                label="person",
                confidence=0.9,
                detected_at=now - timedelta(hours=48),
            )
        )
        # Recent detection (1h ago)
        session.add(
            DetectionRow(
                source_id="new-det",
                label="vehicle",
                confidence=0.9,
                detected_at=now - timedelta(hours=1),
            )
        )
        session.commit()

        mock_resp = _mock_ollama_response("# SITREP filtered")

        with (
            patch(f"{MODULE}.OLLAMA_ENABLED", True),
            patch(f"{MODULE}.httpx.post", return_value=mock_resp),
        ):
            from overwatch.analysis.ollama_briefing import generate_ollama_briefing

            result = generate_ollama_briefing(session, lookback_hours=12)

        stats = json.loads(result.stats_json)
        assert stats["detections"] == 1


class TestAllDataCombined:
    """Full briefing with all data types seeded."""

    def test_combined_context(self, session, now):
        _seed_detections(session, now, count=2)
        _seed_intel(session, now, count=2)
        _seed_telemetry(session, now, battery_pct=15.0, device="drone-X")
        _seed_entities(session, now, count=2)

        mock_resp = _mock_ollama_response("# Full SITREP\nCombined report.")

        with (
            patch(f"{MODULE}.OLLAMA_ENABLED", True),
            patch(f"{MODULE}.httpx.post", return_value=mock_resp) as mock_post,
        ):
            from overwatch.analysis.ollama_briefing import generate_ollama_briefing

            result = generate_ollama_briefing(session)

        prompt = mock_post.call_args.kwargs.get("json", mock_post.call_args[1].get("json", {}))[
            "prompt"
        ]
        assert "DETECTIONS" in prompt
        assert "INTEL REPORTS" in prompt
        assert "TELEMETRY" in prompt
        assert "WARNING" in prompt
        assert "ENTITIES" in prompt

        stats = json.loads(result.stats_json)
        assert stats["detections"] == 2
        assert stats["intel_reports"] == 2
        assert stats["telemetry_points"] == 1
        assert stats["entities"] == 2
        assert stats["source"] == "ollama"
