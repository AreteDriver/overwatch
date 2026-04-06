# Overwatch

Tactical ISR dashboard that unifies YOLO object detections, OSINT intel feeds, and drone telemetry into a single operational picture.

Built for mesh-net ISR workflows — ingest data from cameras, drones, and news pipelines, then visualize, correlate, and act on it from one dashboard.

## Features

- **Multi-source ingestion** — REST endpoints for YOLO detections, OSINT intel (TheWire-STT format), and drone/sensor telemetry
- **YOLO auto-watcher** — CLI monitors a directory for ultralytics JSON output and auto-posts to the API
- **Entity resolution** — Cross-correlates detections with intel mentions (person on camera + named in report = same entity)
- **Auto-briefing** — Generates SITREPs from ingested data. Template-based by default, or Ollama-powered (qwen2.5:14b)
- **Geofencing** — Define polygonal zones, get alerts on enter/exit
- **Mesh health** — Device heartbeat tracking (online/stale/offline status)
- **Discord alerts** — Webhook delivery for high-confidence detections, low battery, geofence breaches
- **Real-time feed** — WebSocket at `/ws/feed` broadcasts all events as they happen
- **Detection heatmap** — Density visualization over time on the map
- **Replay mode** — Scrub through time windows for post-mission review
- **8-tab Streamlit dashboard** — Map, Timeline, Intel Feed, Briefing, Entities, Mesh Health, Alerts, Replay

## Quick Start

```bash
git clone https://github.com/AreteDriver/overwatch
cd overwatch
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,dashboard]"

# Start the API server
uvicorn overwatch.app:app --reload --port 8080

# Start the dashboard (separate terminal)
streamlit run dashboard/app.py --server.port 8520

# Point YOLO output at it (optional)
python tools/yolo_watcher.py --dir /path/to/yolo/runs --lat 46.05 --lon 14.5
```

API docs available at http://localhost:8080/docs (Swagger UI).

## Architecture

```
overwatch/
├── overwatch/
│   ├── app.py               # FastAPI entry point + WebSocket
│   ├── config.py             # Env-driven configuration
│   ├── models.py             # SQLAlchemy ORM + Pydantic schemas
│   ├── database.py           # Engine + session factory
│   ├── events.py             # In-process async event bus
│   ├── security.py           # Auth, rate-limit, headers middleware
│   ├── crypto.py             # Optional Fernet field encryption
│   ├── api/routes.py         # 30+ REST endpoints
│   ├── ingest/               # Detection, intel, telemetry adapters
│   │   ├── detections.py     # YOLO detection ingestion
│   │   ├── intel.py          # OSINT intel ingestion
│   │   ├── telemetry.py      # Drone/sensor telemetry
│   │   └── thewire_adapter.py # TheWire-STT format adapter
│   └── analysis/
│       ├── alerts.py         # Threshold alerts + Discord webhook
│       ├── briefing.py       # Template briefing generator
│       ├── ollama_briefing.py # Local Ollama LLM briefings
│       ├── entities.py       # Entity extraction + resolution
│       ├── geofence.py       # Geofence CRUD + point-in-polygon
│       ├── mesh_health.py    # Device heartbeat tracking
│       └── replay.py         # Time-windowed data retrieval
├── dashboard/app.py          # Streamlit dashboard (8 tabs)
├── tools/yolo_watcher.py     # CLI: watch dir for YOLO output
├── retention.py              # Data retention + auto-purge
└── tests/                    # 132+ tests, 85% coverage
```

**Stack**: FastAPI + SQLAlchemy + SQLite (WAL mode) + Streamlit + Folium + Plotly

## API Endpoints

### Ingestion
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/detections` | Ingest YOLO detection |
| POST | `/api/detections/batch` | Batch ingest detections |
| POST | `/api/intel` | Ingest intel report |
| POST | `/api/intel/batch` | Batch ingest intel |
| POST | `/api/telemetry` | Ingest telemetry reading |
| POST | `/api/telemetry/batch` | Batch ingest telemetry |

### Query
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/detections` | List detections (filterable) |
| GET | `/api/intel` | List intel reports |
| GET | `/api/telemetry` | List telemetry readings |
| GET | `/api/entities` | List resolved entities |
| GET | `/api/entities/{id}/timeline` | Entity event timeline |
| GET | `/api/alerts` | List alerts |
| PATCH | `/api/alerts/{id}/acknowledge` | Acknowledge an alert |

### Analysis
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/briefing/generate` | Generate SITREP briefing |
| GET | `/api/briefing/latest` | Get most recent briefing |
| GET | `/api/mesh/health` | Mesh node health status |
| GET | `/api/replay` | Time-windowed replay data |
| GET | `/api/dashboard/stats` | Dashboard summary stats |

### Geofencing
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/geofences` | Create geofence zone |
| GET | `/api/geofences` | List geofences |
| DELETE | `/api/geofences/{id}` | Delete geofence |

### Export
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/export/detections.csv` | Export detections as CSV |
| GET | `/api/export/detections.geojson` | Export detections as GeoJSON |
| GET | `/api/export/intel.csv` | Export intel reports as CSV |
| GET | `/api/export/telemetry.csv` | Export telemetry as CSV |
| GET | `/api/export/telemetry.geojson` | Export telemetry as GeoJSON |

### Admin
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/admin/purge` | Manually purge old records |

### System
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check (enriched — counts, DB size, WS connections) |
| WS | `/ws/feed` | Real-time event stream |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OVERWATCH_DATABASE_URL` | `~/.overwatch/overwatch.db` | SQLite database path |
| `OVERWATCH_API_KEY` | _(empty = open mode)_ | API key for authentication |
| `OVERWATCH_CORS_ORIGINS` | `*` | Allowed CORS origins (comma-separated) |
| `OVERWATCH_RATE_LIMIT` | `120` | Max requests per window per IP |
| `OVERWATCH_RATE_WINDOW` | `60` | Rate limit window in seconds |
| `OVERWATCH_DISCORD_WEBHOOK` | _(empty)_ | Discord webhook URL for alerts |
| `OVERWATCH_ALERT_CONFIDENCE` | `0.9` | High-confidence detection threshold |
| `OVERWATCH_ALERT_BATTERY` | `20.0` | Low battery alert threshold (%) |
| `OVERWATCH_DEVICE_STALE_SECONDS` | `300` | Seconds before device marked stale |
| `OVERWATCH_DEVICE_OFFLINE_SECONDS` | `900` | Seconds before device marked offline |
| `OVERWATCH_ENCRYPTION_KEY` | _(empty)_ | Fernet key for field encryption |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama API endpoint |
| `OLLAMA_MODEL` | `qwen2.5:14b` | Model for LLM briefings |
| `OLLAMA_ENABLED` | `false` | Enable Ollama-powered briefings |
| `OVERWATCH_RETENTION_DAYS` | `30` | Auto-purge records older than N days (0 = keep forever) |
| `OVERWATCH_PURGE_INTERVAL_HOURS` | `6` | How often to run auto-purge (hours) |

## Security

- **API key auth**: Set `OVERWATCH_API_KEY` to enable. Supports `Authorization: Bearer <key>` header, `X-API-Key` header, or WebSocket `?key=` query param. Empty = open mode (development)
- **Security headers**: HSTS, X-Content-Type-Options, X-Frame-Options, XSS-Protection, Referrer-Policy, Permissions-Policy
- **Rate limiting**: Sliding window per IP
- **CORS**: Configurable allowed origins
- **Field encryption**: Optional Fernet (AES-128-CBC) for sensitive fields. Requires `cryptography` package

## Deployment

Deployed on [Fly.io](https://fly.io) as two apps:

| App | URL | Config |
|-----|-----|--------|
| API | https://overwatch-isr.fly.dev | `fly.toml` |
| Dashboard | https://overwatch-dashboard.fly.dev | `fly.dashboard.toml` |

```bash
# Deploy API
flyctl deploy -a overwatch-isr --wait-timeout 600

# Deploy Dashboard
flyctl deploy --config fly.dashboard.toml --wait-timeout 600
```

Production secrets are set via `flyctl secrets set`. The health endpoint at `/health` is always public for uptime monitoring. Dashboard reads `OVERWATCH_API_URL` and `OVERWATCH_API_KEY` from environment to connect to the API.

## Development

```bash
# Run tests
pytest                          # All tests
pytest -m smoke                 # Smoke/integration tests
pytest --cov=overwatch          # With coverage report

# Lint (always run both)
ruff check .
ruff format .
```

## Integration Points

- **[Dossier](https://github.com/AreteDriver/Dossier)** — Drop-in replacement for regex entity extraction with ML-backed NER + entity resolver
- **[Animus](https://github.com/AreteDriver/animus)** — Replace template/Ollama briefings with AI-orchestrated context-aware generation
- **TheWire-STT** — Pulls from existing OSINT API format (GET `/api/stories`)
- **YOLO** — Accepts ultralytics JSON output via watcher CLI or direct POST
- **Discord** — Webhook alerts for high-confidence detections, low battery, geofence breaches

## License

Private repository.
