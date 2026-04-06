# Overwatch — Tactical ISR Dashboard

## Project Overview
Tactical dashboard that unifies YOLO object detections, OSINT intel feeds (TheWire-STT), and drone telemetry into a single operational picture. Features real-time WebSocket feed, entity resolution, auto-briefing (template + Ollama LLM), geofencing, mesh node health, Discord alerts, detection heatmaps, entity timelines, replay mode, and briefing export. Built for rp9376's mesh-net ISR workflow, with Dossier and Animus integration points.

## Current State

- **Version**: 0.3.0
- **Language**: Python 3.11+
- **Tests**: 251
- **Coverage**: 89%
- **Live**: API (`overwatch-isr.fly.dev`) + Dashboard (`overwatch-dashboard.fly.dev`)

## Architecture
- **Backend**: FastAPI + SQLAlchemy + SQLite (WAL mode) + WebSocket event bus
- **Dashboard**: Streamlit with Folium maps (heatmap, geofences, draw tools, measure, minimap) + Plotly
- **Analysis**: Entity resolution, briefing (template + Ollama), alerts + rules engine, geofencing, mesh health, replay with filtering
- **Ingest**: REST endpoints + YOLO file watcher CLI
- **Real-time**: WebSocket `/ws/feed` broadcasts all ingest events + webhook subscriptions
- **Admin**: Multi-user scoped API keys, data retention/purge, bulk export (CSV/GeoJSON)

```
overwatch/
├── overwatch/
│   ├── api/routes.py          # 40+ REST endpoints
│   ├── app.py                 # FastAPI + WebSocket + health + retention loop
│   ├── config.py              # Env-driven configuration (21 vars)
│   ├── database.py            # Engine + session factory
│   ├── events.py              # In-process async event bus
│   ├── models.py              # ORM + Pydantic (25+ models)
│   ├── security.py            # Auth, rate-limit, headers, scoped API keys
│   ├── crypto.py              # Optional Fernet field encryption
│   ├── retention.py           # Data retention / auto-purge
│   ├── ingest/
│   │   ├── detections.py      # YOLO detection ingestion
│   │   ├── intel.py           # OSINT intel ingestion
│   │   ├── telemetry.py       # Drone/sensor telemetry
│   │   └── thewire_adapter.py # TheWire-STT format adapter
│   └── analysis/
│       ├── alerts.py          # Threshold alerts + Discord webhook
│       ├── briefing.py        # Template briefing generator
│       ├── ollama_briefing.py # LLM briefing via local Ollama
│       ├── entities.py        # Entity extraction + resolution
│       ├── geofence.py        # Geofence CRUD + point-in-polygon
│       ├── mesh_health.py     # Device heartbeat tracking
│       ├── replay.py          # Time-windowed data retrieval + filtering
│       └── rules.py           # Configurable alerting rules engine
├── dashboard/app.py           # Streamlit (8 tabs), reads API_URL + API_KEY from env
├── tools/yolo_watcher.py      # CLI: watch dir for YOLO output, --api-key flag
├── tests/                     # 251 tests, 89% coverage
│   ├── conftest.py            # Shared fixtures (engine, session, now)
│   ├── test_api.py            # REST endpoint tests
│   ├── test_api_keys.py       # Multi-user API key tests
│   ├── test_briefing.py       # Briefing generation tests
│   ├── test_entities.py       # Entity resolution tests
│   ├── test_export.py         # Bulk export + retention + health tests
│   ├── test_ingest.py         # Data ingestion tests
│   ├── test_models.py         # ORM + Pydantic schema tests
│   ├── test_new_features.py   # New feature tests
│   ├── test_replay_v2.py      # Replay filtering + speed + summary tests
│   ├── test_retention.py      # Data retention/purge tests
│   ├── test_rules.py          # Alert rules engine tests
│   ├── test_rules_edge.py     # Rules edge case + compare tests
│   ├── test_events_dispatch.py # Webhook dispatch + HMAC tests
│   ├── test_security.py       # Auth, encryption, rate-limit tests
│   ├── test_smoke.py          # Full write-path integration tests
│   ├── test_webhooks.py       # Webhook subscription tests
│   ├── test_websocket.py      # WebSocket feed tests
│   └── test_yolo_watcher.py   # YOLO watcher CLI tests
├── Dockerfile                 # API container (python:3.12-slim + uvicorn)
├── Dockerfile.dashboard       # Dashboard container (python:3.12-slim + streamlit)
├── fly.toml                   # Fly.io config — API (overwatch-isr)
├── fly.dashboard.toml         # Fly.io config — Dashboard (overwatch-dashboard)
├── pyproject.toml             # Build config, dependencies, ruff, pytest
├── .github/workflows/ci.yml   # CI: pytest + ruff + 80% coverage gate
└── .gitleaks.toml             # Secrets scanning config
```

## Common Commands
```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,dashboard]"

# Run API server
uvicorn overwatch.app:app --reload --port 8080

# Run dashboard (local, points at localhost:8080 by default)
streamlit run dashboard/app.py --server.port 8520

# Run dashboard pointed at production
OVERWATCH_API_URL=https://overwatch-isr.fly.dev/api OVERWATCH_API_KEY=<key> streamlit run dashboard/app.py

# YOLO watcher
python tools/yolo_watcher.py --dir /path/to/yolo/output --lat 46.05 --lon 14.5
python tools/yolo_watcher.py --dir ./runs --api-key <key>

# Tests
pytest                       # All 251 tests
pytest -m smoke              # Smoke/integration tests only
pytest --cov=overwatch       # With coverage report

# Lint (always run BOTH)
ruff check . && ruff format .

# Deploy
flyctl deploy -a overwatch-isr --wait-timeout 600           # API
flyctl deploy --config fly.dashboard.toml --wait-timeout 600 # Dashboard
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

## CI/CD
- **GitHub Actions** (`.github/workflows/ci.yml`): pytest + ruff check + ruff format + 80% coverage gate
- **Matrix**: Python 3.11, 3.12
- **Deployment**: Fly.io — API (`overwatch-isr.fly.dev`), Dashboard (`overwatch-dashboard.fly.dev`)
- **Deploy API**: `flyctl deploy -a overwatch-isr --wait-timeout 600`
- **Deploy Dashboard**: `flyctl deploy --config fly.dashboard.toml --wait-timeout 600`
- **Secrets scanning**: `.gitleaks.toml` configured

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

## Security
- **API key auth**: Set `OVERWATCH_API_KEY` env var. Supports `Authorization: Bearer <key>` and `X-API-Key` headers. Empty = open mode.
- **WebSocket auth**: Pass `?key=<api_key>` query param on `/ws/feed`
- **Dashboard auth**: Reads `OVERWATCH_API_KEY` from env, passes Bearer header on all API requests
- **YOLO watcher auth**: `--api-key` flag or `OVERWATCH_API_KEY` env var
- **Security headers**: X-Content-Type-Options, X-Frame-Options, XSS-Protection, HSTS, Referrer-Policy, Permissions-Policy
- **Rate limiting**: Sliding window per IP. Configure via `OVERWATCH_RATE_LIMIT` (requests) and `OVERWATCH_RATE_WINDOW` (seconds)
- **CORS lockdown**: Set `OVERWATCH_CORS_ORIGINS` (JSON array on Fly.io, comma-separated locally)
- **Field encryption**: Optional Fernet (AES-128-CBC) via `OVERWATCH_ENCRYPTION_KEY`. Install `cryptography` package to enable
- **Scoped API keys**: `POST /api/admin/keys` creates keys with scopes (read, write, admin). Raw key returned once; only SHA-256 hash stored. `verify_api_key_scoped()` checks both master key and DB keys
- **Health endpoint**: `/health` is always public (no auth required), enriched with DB size, event counts, WS connections
- Security module: `overwatch/security.py`, crypto: `overwatch/crypto.py`

## Design Decisions
- SQLite for zero-config portability (target user runs everything local)
- In-process event bus (asyncio.Queue) for WebSocket — no Redis needed at this scale
- Geofence uses ray-casting point-in-polygon (no external geo library needed)
- Ollama briefings fall back to templates if Ollama unavailable
- YOLO watcher uses polling (not inotify) for cross-platform compatibility
- Security is opt-in: no API_KEY = open mode (dev-friendly), set key for production
- Multi-user API keys: scoped (read/write/admin), master key has all scopes, DB-stored keys with SHA-256 hash
- Webhook subscriptions: HMAC-SHA256 signed payloads, auto-disable after 10 consecutive failures
- Alert rules engine: 4 rule types (geofence_entity, detection_count, entity_new, custom_field), evaluated on each detection ingest
- Data retention: background purge loop + manual `/api/admin/purge` endpoint, configurable TTL
- Bulk export: CSV + GeoJSON endpoints for detections, intel, telemetry (up to 50K rows)
- Replay filtering: event_types param, speed multiplier, summary endpoint for timeline UI
- Scoped auth: middleware accepts both master + DB keys; endpoint deps enforce scope (write for ingest, admin for management)
- Litestream: SQLite WAL replication to Tigris S3, 10s sync, 168h retention, restore-on-boot via run.sh
- Alert→webhook pipeline: alerts publish to event bus → webhooks auto-dispatch (detection → alert → webhook in one flow)
- YOLO watcher `--model` flag records model version in detection meta for audit trail
- Dashboard deployed as separate Fly.io app (512MB for Streamlit + Folium rendering)

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
| `OVERWATCH_API_KEY` | (empty) | API key for auth (empty = open mode) |
| `OVERWATCH_API_URL` | `http://localhost:8080/api` | API URL (dashboard only) |
| `OVERWATCH_DISCORD_WEBHOOK` | (empty) | Discord webhook URL |
| `OVERWATCH_ALERT_CONFIDENCE` | `0.9` | High-confidence alert threshold |
| `OVERWATCH_ALERT_BATTERY` | `20.0` | Low battery alert threshold (%) |
| `OVERWATCH_DEVICE_STALE_SECONDS` | `300` | Seconds before device is "stale" |
| `OVERWATCH_DEVICE_OFFLINE_SECONDS` | `900` | Seconds before device is "offline" |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama API URL |
| `OLLAMA_MODEL` | `qwen2.5:14b` | Ollama model for LLM briefings |
| `OLLAMA_ENABLED` | `false` | Enable Ollama briefings |
| `OVERWATCH_ENCRYPTION_KEY` | (empty) | Fernet key for field encryption |
| `OVERWATCH_CORS_ORIGINS` | `*` | Allowed origins (JSON array on Fly.io) |
| `OVERWATCH_RATE_LIMIT` | `120` | Max requests per window per IP |
| `OVERWATCH_RATE_WINDOW` | `60` | Rate limit window in seconds |
| `OVERWATCH_RETENTION_DAYS` | `30` | Auto-purge records older than N days (0 = keep forever) |
| `OVERWATCH_PURGE_INTERVAL_HOURS` | `6` | How often to run background purge (hours) |
