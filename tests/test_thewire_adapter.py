"""Tests for TheWire-STT adapter."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx

from overwatch.ingest.thewire_adapter import fetch_stories


def _mock_response(data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


class TestFetchStories:
    @patch("overwatch.ingest.thewire_adapter.httpx.get")
    def test_basic_stories(self, mock_get):
        mock_get.return_value = _mock_response(
            [
                {
                    "id": "tw-1",
                    "title": "Test Story",
                    "summary": "A test summary",
                    "body": "Full body text",
                    "published_at": "2026-04-01T12:00:00Z",
                    "tags": ["test"],
                    "source_url": "https://example.com/1",
                },
            ]
        )

        results = fetch_stories(base_url="http://mock:5000/api")
        assert len(results) == 1
        assert results[0].source_id == "thewire-tw-1"
        assert results[0].title == "Test Story"
        assert results[0].summary == "A test summary"
        assert results[0].source_name == "thewire"
        assert results[0].tags == ["test"]

    @patch("overwatch.ingest.thewire_adapter.httpx.get")
    def test_multiple_stories(self, mock_get):
        mock_get.return_value = _mock_response(
            [
                {"id": "1", "title": "A", "summary": "S1", "published_at": "2026-04-01T12:00:00Z"},
                {"id": "2", "title": "B", "summary": "S2", "published_at": "2026-04-01T13:00:00Z"},
                {"id": "3", "title": "C", "summary": "S3", "published_at": "2026-04-01T14:00:00Z"},
            ]
        )
        results = fetch_stories(base_url="http://mock:5000/api")
        assert len(results) == 3

    @patch("overwatch.ingest.thewire_adapter.httpx.get")
    def test_wrapped_in_stories_key(self, mock_get):
        """Some APIs wrap results in {"stories": [...]}."""
        mock_get.return_value = _mock_response(
            {
                "stories": [
                    {
                        "id": "w1",
                        "title": "Wrapped",
                        "summary": "S",
                        "published_at": "2026-04-01T00:00:00Z",
                    },
                ]
            }
        )
        results = fetch_stories(base_url="http://mock:5000/api")
        assert len(results) == 1
        assert results[0].title == "Wrapped"

    @patch("overwatch.ingest.thewire_adapter.httpx.get")
    def test_wrapped_in_data_key(self, mock_get):
        """Some APIs wrap results in {"data": [...]}."""
        mock_get.return_value = _mock_response(
            {
                "data": [
                    {
                        "id": "d1",
                        "title": "Data",
                        "summary": "S",
                        "published_at": "2026-04-01T00:00:00Z",
                    },
                ]
            }
        )
        results = fetch_stories(base_url="http://mock:5000/api")
        assert len(results) == 1

    @patch("overwatch.ingest.thewire_adapter.httpx.get")
    def test_http_error_returns_empty(self, mock_get):
        mock_get.return_value = _mock_response([], status_code=500)
        results = fetch_stories(base_url="http://mock:5000/api")
        assert results == []

    @patch("overwatch.ingest.thewire_adapter.httpx.get")
    def test_connection_error_returns_empty(self, mock_get):
        mock_get.side_effect = httpx.ConnectError("Connection refused")
        results = fetch_stories(base_url="http://mock:5000/api")
        assert results == []

    @patch("overwatch.ingest.thewire_adapter.httpx.get")
    def test_malformed_story_skipped(self, mock_get):
        """Story missing 'id' key should be skipped."""
        mock_get.return_value = _mock_response(
            [
                {"title": "No ID", "summary": "Missing id field"},
                {
                    "id": "ok",
                    "title": "Good",
                    "summary": "OK",
                    "published_at": "2026-04-01T00:00:00Z",
                },
            ]
        )
        results = fetch_stories(base_url="http://mock:5000/api")
        assert len(results) == 1
        assert results[0].source_id == "thewire-ok"

    @patch("overwatch.ingest.thewire_adapter.httpx.get")
    def test_missing_published_at_uses_now(self, mock_get):
        mock_get.return_value = _mock_response(
            [
                {"id": "np1", "title": "No Date", "summary": "S"},
            ]
        )
        results = fetch_stories(base_url="http://mock:5000/api")
        assert len(results) == 1
        assert results[0].published_at is not None

    @patch("overwatch.ingest.thewire_adapter.httpx.get")
    def test_date_field_fallback(self, mock_get):
        """Some APIs use 'date' instead of 'published_at'."""
        mock_get.return_value = _mock_response(
            [
                {
                    "id": "df1",
                    "title": "Date Field",
                    "summary": "S",
                    "date": "2026-04-01T00:00:00Z",
                },
            ]
        )
        results = fetch_stories(base_url="http://mock:5000/api")
        assert len(results) == 1

    @patch("overwatch.ingest.thewire_adapter.httpx.get")
    def test_defaults_for_optional_fields(self, mock_get):
        mock_get.return_value = _mock_response(
            [
                {"id": "min1", "published_at": "2026-04-01T00:00:00Z"},
            ]
        )
        results = fetch_stories(base_url="http://mock:5000/api")
        assert len(results) == 1
        assert results[0].title == "Untitled"
        assert results[0].summary == ""
        assert results[0].body == ""
        assert results[0].source_url == ""
        assert results[0].tags == []

    @patch("overwatch.ingest.thewire_adapter.httpx.get")
    def test_content_field_fallback(self, mock_get):
        """Some APIs use 'content' instead of 'body'."""
        mock_get.return_value = _mock_response(
            [
                {
                    "id": "cf1",
                    "title": "Content Field",
                    "summary": "S",
                    "content": "Full body via content",
                    "published_at": "2026-04-01T00:00:00Z",
                },
            ]
        )
        results = fetch_stories(base_url="http://mock:5000/api")
        assert results[0].body == "Full body via content"

    @patch("overwatch.ingest.thewire_adapter.httpx.get")
    def test_url_construction(self, mock_get):
        mock_get.return_value = _mock_response([])
        fetch_stories(base_url="http://example.com/api/")
        mock_get.assert_called_once()
        call_url = mock_get.call_args[0][0]
        assert call_url == "http://example.com/api/stories"
        assert "//" not in call_url.replace("http://", "")

    @patch("overwatch.ingest.thewire_adapter.httpx.get")
    def test_empty_list(self, mock_get):
        mock_get.return_value = _mock_response([])
        results = fetch_stories(base_url="http://mock:5000/api")
        assert results == []
