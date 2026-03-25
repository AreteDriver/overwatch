# Overwatch — Tactical ISR Dashboard

## Project Overview
Tactical dashboard that unifies YOLO object detections, OSINT intel feeds (TheWire-STT), and drone telemetry into a single operational picture. Features real-time WebSocket feed, entity resolution, auto-briefing (template + Ollama LLM), geofencing, mesh node health, Discord alerts, detection heatmaps, entity timelines, replay mode, and briefing export. Built for rp9376's mesh-net ISR workflow, with Dossier and Animus integration points.

## Architecture
- **Backend**: FastAPI + SQLAlchemy + SQLite (WAL mode) + WebSocket event bus
- **Dashboard**: Streamlit with Folium maps (heatmap, geofences, draw tools, measure, minimap) + Plotly
- **Analysis**: Entity resolution, briefing (template + Ollama), alerts, geofencing, mesh health, replay
- **Ingest**: REST endpoints + YOLO file watcher CLI
- **Real-time**: WebSocket `/ws/feed` broadcasts all ingest events

```
overwatch/
├── overwatch/
│   ├── api/routes.py        # 30+ REST endpoints
│   ├── app.py               # FastAPI + WebSocket
│   ├── events.py            # In-process event bus
│   ├── ingest/              # Detection, intel, telemetry adapters
│   ├── analysis/
│   │   ├── alerts.py        # Threshold alerts + Discord webhook
│   │   ├── briefing.py      # Template briefing generator
│   │   ├── ollama_briefing.py # LLM briefing via local Ollama
│   │   ├── entities.py      # Entity extraction + resolution
│   │   ├── geofence.py      # Geofence CRUD + point-in-polygon
│   │   ├── mesh_health.py   # Device heartbeat tracking
│   │   └── replay.py        # Time-windowed data retrieval
│   ├── models.py            # ORM + Pydantic (15 models)
│   ├── database.py          # Engine + session factory
│   └── config.py            # Env-driven configuration
├── dashboard/app.py         # Streamlit (8 tabs)
├── tools/yolo_watcher.py    # CLI: watch dir for YOLO output, auto-ingest
└── tests/                   # 104 tests, 83% coverage
```

## Common Commands
```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,dashboard]"

# Run API server
uvicorn overwatch.app:app --reload --port 8080

# Run dashboard
streamlit run dashboard/app.py --server.port 8520

# YOLO watcher
python tools/yolo_watcher.py --dir /path/to/yolo/output --lat 46.05 --lon 14.5

# Tests
pytest                       # All 104 tests
pytest -m smoke              # Smoke tests only
pytest --cov=overwatch       # With coverage

# Lint (always run BOTH)
ruff check . && ruff format .
```

## Coding Standards
- Python 3.11+, type hints on all functions
- Ruff for linting and formatting (line-length 100)
- Pydantic v2 schemas with `model_config = {"from_attributes": True}`
- SQLAlchemy 2.0 ORM style (DeclarativeBase)
- All ingest endpoints are idempotent (dedup by source_id, unique constraint)
- `StaticPool` for in-memory SQLite in tests
- Event bus publishes on every ingest for WebSocket + alert dispatch

## Anti-Patterns
- Do not use `timezone.utc` — use `datetime.UTC` (Python 3.11+)
- Do not use `str, Enum` — use `StrEnum`
- Never commit `*.db` files
- No WAL pragma on in-memory SQLite (use `StaticPool` instead)
- Geofence coords are `[[lat, lon], ...]` — do not swap to `[lon, lat]`

## Dependencies
Core: `fastapi`, `uvicorn`, `sqlalchemy`, `pydantic`, `httpx`, `python-dateutil`
Dashboard: `streamlit`, `folium`, `streamlit-folium`, `plotly`, `pandas`
Dev: `pytest`, `pytest-cov`, `pytest-asyncio`, `ruff`

## Git Conventions
- Conventional commits: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`
- Run `pytest` and `ruff check .` before committing
- Tag releases: `v0.2.0` (semantic versioning)

## Domain Context
This tool targets ISR (intelligence, surveillance, reconnaissance) workflows:
- **Detections**: YOLO object detection results from camera feeds (person, vehicle, drone)
- **Intel**: OSINT news summaries from automated pipelines (TheWire-STT format)
- **Telemetry**: Drone/sensor position data (lat/lon, altitude, battery, heading)
- **Entities**: Cross-source resolved objects with timeline drill-down
- **Briefings**: Auto-generated SITREPs (template or Ollama LLM)
- **Geofences**: Named polygonal zones with enter/exit alerts
- **Alerts**: Threshold-based (high confidence, low battery, geofence breach) with Discord delivery
- **Mesh Health**: Device heartbeat tracking (online/stale/offline status)
- **Replay**: Time-windowed post-mission review with animated map

## Design Decisions
- SQLite for zero-config portability (target user runs everything local)
- In-process event bus (asyncio.Queue) for WebSocket — no Redis needed at this scale
- Geofence uses ray-casting point-in-polygon (no external geo library needed)
- Ollama briefings fall back to templates if Ollama unavailable
- YOLO watcher uses polling (not inotify) for cross-platform compatibility

## Integration Points
- **Dossier**: Replace `overwatch.analysis.entities` with Dossier's NER + entity resolver
- **Animus**: Replace template/Ollama briefings with Animus-orchestrated LLM generation
- **TheWire-STT**: Pulls from rp9376's existing API format (GET /api/stories)
- **YOLO**: Accepts ultralytics JSON output via watcher or direct API POST
- **Discord**: Set `OVERWATCH_DISCORD_WEBHOOK` env var to enable alert delivery

## Environment Variables
| Variable | Default | Description |
|----------|---------|-------------|
| `OVERWATCH_DATABASE_URL` | `~/.overwatch/overwatch.db` | SQLite path |
| `OVERWATCH_DISCORD_WEBHOOK` | (empty) | Discord webhook URL |
| `OVERWATCH_ALERT_CONFIDENCE` | `0.9` | High-confidence alert threshold |
| `OVERWATCH_ALERT_BATTERY` | `20.0` | Low battery alert threshold (%) |
| `OVERWATCH_DEVICE_STALE_SECONDS` | `300` | Seconds before device is "stale" |
| `OVERWATCH_DEVICE_OFFLINE_SECONDS` | `900` | Seconds before device is "offline" |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama API URL |
| `OLLAMA_MODEL` | `qwen2.5:14b` | Ollama model for LLM briefings |
| `OLLAMA_ENABLED` | `false` | Enable Ollama briefings |
