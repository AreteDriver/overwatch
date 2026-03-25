# Overwatch — Tactical ISR Dashboard

## Project Overview
Lightweight tactical dashboard that unifies YOLO object detections, OSINT intel feeds (TheWire-STT), and drone telemetry into a single operational picture with entity resolution and auto-briefing. Built as a demo/gift for rp9376's mesh-net ISR workflow, showcasing Dossier and Animus integration points.

## Architecture
- **Backend**: FastAPI + SQLAlchemy + SQLite (WAL mode)
- **Dashboard**: Streamlit with Folium maps + Plotly timeline
- **Analysis**: Entity extraction, cross-source correlation, briefing generation
- **Ingest**: REST endpoints accepting YOLO detections, TheWire intel, drone telemetry

```
overwatch/
├── overwatch/           # Main package
│   ├── api/             # FastAPI routes
│   ├── ingest/          # Data source adapters
│   ├── analysis/        # Entity resolution + briefing engine
│   ├── models.py        # SQLAlchemy + Pydantic models
│   ├── database.py      # Database setup
│   └── config.py        # Configuration
├── dashboard/           # Streamlit app
├── tests/               # pytest suite
└── pyproject.toml
```

## Common Commands
```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,dashboard]"

# Run API server
uvicorn overwatch.app:app --reload --port 8000

# Run dashboard
streamlit run dashboard/app.py

# Tests
pytest                       # All tests
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

## Anti-Patterns
- Do not use `timezone.utc` — use `datetime.UTC` (Python 3.11+)
- Do not use `str, Enum` — use `StrEnum`
- Never commit `*.db` files
- No WAL pragma on in-memory SQLite (use `StaticPool` instead)

## Dependencies
Core: `fastapi`, `uvicorn`, `sqlalchemy`, `pydantic`, `httpx`, `python-dateutil`
Dashboard: `streamlit`, `folium`, `streamlit-folium`, `plotly`, `pandas`
Dev: `pytest`, `pytest-cov`, `pytest-asyncio`, `ruff`

## Git Conventions
- Conventional commits: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`
- Run `pytest` and `ruff check .` before committing
- Tag releases: `v0.1.0` (semantic versioning)

## Domain Context
This tool targets ISR (intelligence, surveillance, reconnaissance) workflows:
- **Detections**: YOLO object detection results from camera feeds (person, vehicle, drone)
- **Intel**: OSINT news summaries from automated pipelines (TheWire-STT format)
- **Telemetry**: Drone/sensor position data (lat/lon, altitude, battery, heading)
- **Entities**: Cross-source resolved objects (person seen on camera + mentioned in intel)
- **Briefings**: Auto-generated situation reports (SITREP) from aggregated data

## Design Decisions
- SQLite for zero-config portability (target user runs everything local)
- Entity resolution is rule-based (fuzzy string matching + label correlation) — designed to show where Dossier's NER would plug in
- Briefing generation uses templates with structured data — designed to show where Animus LLM orchestration would enhance

## Integration Points
- **Dossier**: Replace `overwatch.analysis.entities` with Dossier's NER + entity resolver for production-grade entity extraction
- **Animus**: Replace template briefings with Animus-orchestrated LLM briefing generation, add persistent memory across sessions
- **TheWire-STT**: Pulls from rp9376's existing API format (GET /api/stories)
- **YOLO**: Accepts standard detection JSON (class, confidence, bbox, timestamp, source)
