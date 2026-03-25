"""Adapter to pull stories from a TheWire-STT compatible API.

TheWire-STT (rp9376) serves stories via:
  GET /api/stories -> [{id, title, summary, body, published_at, tags, source_url}, ...]

This adapter fetches stories and converts them to IntelReportIn for ingestion.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx

from overwatch.config import THEWIRE_API_URL
from overwatch.models import IntelReportIn

log = logging.getLogger(__name__)


def fetch_stories(
    base_url: str | None = None,
    timeout: float = 10.0,
) -> list[IntelReportIn]:
    """Fetch stories from TheWire-STT API and convert to IntelReportIn."""
    url = (base_url or THEWIRE_API_URL).rstrip("/") + "/stories"
    try:
        resp = httpx.get(url, timeout=timeout)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("Failed to fetch TheWire stories from %s: %s", url, exc)
        return []

    stories = resp.json()
    if not isinstance(stories, list):
        stories = stories.get("stories", stories.get("data", []))

    results: list[IntelReportIn] = []
    for story in stories:
        try:
            published = story.get("published_at") or story.get("date")
            if isinstance(published, str):
                # Handle ISO format
                pub_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
            else:
                pub_dt = datetime.now(UTC)

            results.append(
                IntelReportIn(
                    source_id=f"thewire-{story['id']}",
                    title=story.get("title", "Untitled"),
                    summary=story.get("summary", ""),
                    body=story.get("body", story.get("content", "")),
                    source_name="thewire",
                    source_url=story.get("source_url", story.get("url", "")),
                    published_at=pub_dt,
                    tags=story.get("tags", []),
                )
            )
        except (KeyError, ValueError) as exc:
            log.warning("Skipping malformed story: %s", exc)
            continue

    log.info("Fetched %d stories from TheWire-STT", len(results))
    return results
