"""YOLO watcher CLI tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.yolo_watcher import parse_yolo_json, send_detections


@pytest.fixture()
def yolo_json(tmp_path: Path) -> Path:
    """Create a sample YOLO JSON output file."""
    data = [
        {
            "name": "person",
            "class": 0,
            "confidence": 0.92,
            "box": {"x1": 10, "y1": 20, "x2": 60, "y2": 100},
        },
        {
            "name": "car",
            "class": 2,
            "confidence": 0.85,
            "box": {"x1": 100, "y1": 200, "x2": 300, "y2": 400},
        },
    ]
    filepath = tmp_path / "detections.json"
    filepath.write_text(json.dumps(data))
    return filepath


@pytest.fixture()
def yolo_single(tmp_path: Path) -> Path:
    """YOLO file with a single detection (not wrapped in list)."""
    data = {
        "name": "drone",
        "class": 5,
        "confidence": 0.77,
        "box": {"x1": 0, "y1": 0, "x2": 50, "y2": 50},
    }
    filepath = tmp_path / "single.json"
    filepath.write_text(json.dumps(data))
    return filepath


class TestParseYoloJson:
    """Tests for parse_yolo_json."""

    def test_parse_multiple_detections(self, yolo_json: Path):
        result = parse_yolo_json(yolo_json, default_lat=46.05, default_lon=14.5)
        assert len(result) == 2
        assert result[0]["label"] == "person"
        assert result[0]["confidence"] == 0.92
        assert result[0]["lat"] == 46.05
        assert result[0]["lon"] == 14.5
        assert result[0]["source_name"] == "yolo"
        assert result[0]["source_id"].startswith("yolo-")

    def test_parse_single_detection(self, yolo_single: Path):
        result = parse_yolo_json(yolo_single)
        assert len(result) == 1
        assert result[0]["label"] == "drone"
        assert result[0]["confidence"] == 0.77

    def test_bbox_conversion(self, yolo_json: Path):
        result = parse_yolo_json(yolo_json)
        # bbox should be [x, y, width, height]
        bbox = result[0]["bbox"]
        assert bbox == [10, 20, 50, 80]  # x1, y1, x2-x1, y2-y1

    def test_no_default_coords(self, yolo_json: Path):
        result = parse_yolo_json(yolo_json)
        assert result[0]["lat"] is None
        assert result[0]["lon"] is None

    def test_unique_source_ids(self, yolo_json: Path):
        result = parse_yolo_json(yolo_json)
        ids = [d["source_id"] for d in result]
        assert len(set(ids)) == len(ids)

    def test_meta_contains_file_and_class(self, yolo_json: Path):
        result = parse_yolo_json(yolo_json)
        assert result[0]["meta"]["file"] == "detections.json"
        assert result[0]["meta"]["class_id"] == 0

    def test_detected_at_is_iso(self, yolo_json: Path):
        result = parse_yolo_json(yolo_json)
        # Should be parseable as ISO datetime
        from datetime import datetime

        datetime.fromisoformat(result[0]["detected_at"])


class TestSendDetections:
    """Tests for send_detections."""

    def test_empty_list_returns_zero(self):
        assert send_detections("http://fake", []) == 0

    @patch("tools.yolo_watcher.httpx.post")
    def test_successful_send(self, mock_post: MagicMock):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"id": 1}, {"id": 2}]
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        result = send_detections("http://fake/api", [{"a": 1}, {"b": 2}])
        assert result == 2
        mock_post.assert_called_once()

    @patch("tools.yolo_watcher.httpx.post")
    def test_send_with_api_key(self, mock_post: MagicMock):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"id": 1}]
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        send_detections("http://fake/api", [{"a": 1}], api_key="secret-key")
        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer secret-key"

    @patch("tools.yolo_watcher.httpx.post")
    def test_send_without_api_key_no_auth_header(self, mock_post: MagicMock):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{"id": 1}]
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        send_detections("http://fake/api", [{"a": 1}])
        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs["headers"] == {}

    @patch("tools.yolo_watcher.httpx.post")
    def test_send_failure_returns_zero(self, mock_post: MagicMock):
        import httpx

        mock_post.side_effect = httpx.HTTPError("Connection refused")
        result = send_detections("http://fake/api", [{"a": 1}])
        assert result == 0
