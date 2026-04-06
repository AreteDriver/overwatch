#!/usr/bin/env python3
"""YOLO auto-ingest watcher.

Monitors a directory for YOLO detection output files and auto-posts
them to the Overwatch API. Supports ultralytics JSON output format.

Usage:
    python tools/yolo_watcher.py --dir /path/to/yolo/output
    python tools/yolo_watcher.py --dir ./runs/detect --api http://localhost:8080/api

Ultralytics JSON format (per image):
[
  {
    "name": "person",
    "class": 0,
    "confidence": 0.92,
    "box": {"x1": 10, "y1": 20, "x2": 60, "y2": 100}
  }
]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)


def parse_yolo_json(
    filepath: Path,
    default_lat: float | None = None,
    default_lon: float | None = None,
    model_version: str = "",
) -> list[dict]:
    """Parse a YOLO ultralytics JSON output file into detection payloads."""
    with open(filepath) as f:
        data = json.load(f)

    if not isinstance(data, list):
        data = [data]

    detections = []
    file_hash = hashlib.md5(str(filepath).encode()).hexdigest()[:8]

    for i, det in enumerate(data):
        box = det.get("box", {})
        bbox = [
            box.get("x1", 0),
            box.get("y1", 0),
            box.get("x2", 0) - box.get("x1", 0),
            box.get("y2", 0) - box.get("y1", 0),
        ]
        detections.append(
            {
                "source_id": f"yolo-{file_hash}-{i}",
                "label": det.get("name", det.get("label", "unknown")),
                "confidence": det.get("confidence", 0.0),
                "bbox": bbox,
                "lat": default_lat,
                "lon": default_lon,
                "source_name": "yolo",
                "detected_at": datetime.now(UTC).isoformat(),
                "meta": {
                    "file": str(filepath.name),
                    "class_id": det.get("class", -1),
                    **({"model_version": model_version} if model_version else {}),
                },
            }
        )
    return detections


def send_detections(api_url: str, detections: list[dict], api_key: str = "") -> int:
    """Post detections to the Overwatch API. Returns count of ingested."""
    if not detections:
        return 0
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        resp = httpx.post(
            f"{api_url}/ingest/detections",
            json=detections,
            headers=headers,
            timeout=10,
        )
        resp.raise_for_status()
        return len(resp.json())
    except httpx.HTTPError as exc:
        log.error("Failed to send detections: %s", exc)
        return 0


def watch_directory(
    watch_dir: Path,
    api_url: str,
    poll_interval: float = 2.0,
    lat: float | None = None,
    lon: float | None = None,
    api_key: str = "",
    model_version: str = "",
) -> None:
    """Poll a directory for new JSON files and ingest them."""
    seen: set[str] = set()
    log.info("Watching %s for YOLO output files...", watch_dir)
    log.info("API: %s", api_url)

    # Pre-load existing files as "seen"
    for f in watch_dir.glob("*.json"):
        seen.add(str(f))

    while True:
        for f in watch_dir.glob("*.json"):
            path_str = str(f)
            if path_str in seen:
                continue
            seen.add(path_str)

            log.info("New file: %s", f.name)
            try:
                dets = parse_yolo_json(
                    f,
                    default_lat=lat,
                    default_lon=lon,
                    model_version=model_version,
                )
                count = send_detections(api_url, dets, api_key=api_key)
                log.info("Ingested %d detections from %s", count, f.name)
            except (json.JSONDecodeError, OSError) as exc:
                log.error("Failed to parse %s: %s", f.name, exc)

        time.sleep(poll_interval)


def main():
    parser = argparse.ArgumentParser(description="YOLO auto-ingest watcher")
    parser.add_argument("--dir", required=True, help="Directory to watch for YOLO JSON output")
    parser.add_argument(
        "--api",
        default=os.getenv("YOLO_API_URL", "http://localhost:8080/api"),
        help="Overwatch API URL",
    )
    parser.add_argument("--interval", type=float, default=2.0, help="Poll interval (seconds)")
    parser.add_argument("--lat", type=float, default=None, help="Default latitude for detections")
    parser.add_argument("--lon", type=float, default=None, help="Default longitude for detections")
    parser.add_argument(
        "--api-key",
        default=os.getenv("OVERWATCH_API_KEY", ""),
        help="API key for authentication",
    )
    parser.add_argument(
        "--model",
        default="",
        help="YOLO model version (e.g. yolov8n, yolov5s) for audit trail",
    )
    args = parser.parse_args()

    watch_path = Path(args.dir)
    if not watch_path.is_dir():
        log.error("Directory does not exist: %s", args.dir)
        sys.exit(1)

    watch_directory(
        watch_path,
        args.api,
        args.interval,
        args.lat,
        args.lon,
        api_key=args.api_key,
        model_version=args.model,
    )


if __name__ == "__main__":
    main()
