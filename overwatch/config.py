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
ENTITY_FUZZY_THRESHOLD: float = 0.75  # minimum similarity for entity merge
