"""Application configuration."""

from __future__ import annotations

import os
from pathlib import Path

DATABASE_URL: str = os.getenv(
    "OVERWATCH_DATABASE_URL",
    f"sqlite:///{Path.home() / '.overwatch' / 'overwatch.db'}",
)

# For tests / ephemeral usage
DATABASE_URL_MEMORY: str = "sqlite://"

# TheWire-STT integration
THEWIRE_API_URL: str = os.getenv("THEWIRE_API_URL", "http://localhost:5000/api")

# Briefing defaults
BRIEFING_MAX_ITEMS: int = 20
BRIEFING_LOOKBACK_HOURS: int = 24

# Entity resolution
ENTITY_FUZZY_THRESHOLD: float = 0.75

# Discord webhook (set to enable alerts)
DISCORD_WEBHOOK_URL: str = os.getenv("OVERWATCH_DISCORD_WEBHOOK", "")

# Alert thresholds
ALERT_HIGH_CONFIDENCE: float = float(os.getenv("OVERWATCH_ALERT_CONFIDENCE", "0.9"))
ALERT_LOW_BATTERY: float = float(os.getenv("OVERWATCH_ALERT_BATTERY", "20.0"))
ALERT_DEVICE_STALE_SECONDS: float = float(os.getenv("OVERWATCH_DEVICE_STALE_SECONDS", "300"))
ALERT_DEVICE_OFFLINE_SECONDS: float = float(os.getenv("OVERWATCH_DEVICE_OFFLINE_SECONDS", "900"))

# Ollama (local LLM for enhanced briefings)
OLLAMA_URL: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen2.5:14b")
OLLAMA_ENABLED: bool = os.getenv("OLLAMA_ENABLED", "false").lower() == "true"

# YOLO watcher
YOLO_WATCH_DIR: str = os.getenv("YOLO_WATCH_DIR", "")
YOLO_API_URL: str = os.getenv("YOLO_API_URL", "http://localhost:8080/api")
