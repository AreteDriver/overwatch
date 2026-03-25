# Outreach message for rp9376 (Rok)

## GitHub DM / Issue / Discussion

---

**Subject:** Built you a tactical dashboard for your mesh-net ISR workflow

Hey Rok,

Saw your TheWire-STT project and your FPV drone control stack (ControlSwitch, Joy_over_UDP, YOLO training). Looked like you had all the pieces for a solid ISR pipeline but no unified dashboard tying it together. So I built one.

**Overwatch** — a tactical ISR dashboard that plugs into your existing tools:

🔗 **Repo**: https://github.com/AreteDriver/overwatch
🔗 **Live API**: https://overwatch-isr.fly.dev/docs (Swagger UI)

### What it does

- **Ingests your data**: REST endpoints for YOLO detections, OSINT intel (TheWire-STT format), and drone telemetry
- **YOLO auto-watcher**: CLI tool that monitors a directory for ultralytics JSON output and auto-posts to the API — zero manual work
- **Entity resolution**: Cross-correlates detections with intel mentions (person on camera + named in report = same entity)
- **Auto-briefing**: Generates SITREPs from all ingested data. Template-based by default, or **Ollama-powered** (you already run qwen2.5)
- **Geofencing**: Define zones, get alerts when detections enter/exit
- **Mesh node health**: Tracks device heartbeats from telemetry — shows online/stale/offline status
- **Discord alerts**: Webhook delivery for high-confidence detections, low battery, geofence breaches
- **Real-time WebSocket feed**: `/ws/feed` broadcasts all events as they happen
- **Detection heatmap**: Density visualization over time
- **Replay mode**: Scrub through time windows for post-mission review

### Streamlit dashboard (8 tabs)
Map (dark tiles, heatmap, geofences, draw tools, measurement, device trails), Timeline, Intel Feed, Briefing (with Markdown export), Entities (with per-entity timeline drill-down), Mesh Health, Alerts, Replay.

### Quick start

```bash
git clone https://github.com/AreteDriver/overwatch
cd overwatch
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,dashboard]"

# API
uvicorn overwatch.app:app --reload --port 8080

# Dashboard
streamlit run dashboard/app.py

# Point your YOLO output at it
python tools/yolo_watcher.py --dir /path/to/yolo/runs --lat 46.05 --lon 14.5
```

### Why I built this

I work on similar tooling for EVE Online (game intel/mapping) and have two libraries that would take this further if you're interested:

- **[Dossier](https://github.com/AreteDriver/Dossier)** — ML-backed named entity recognition + entity resolution. Drop-in replacement for the regex-based extraction in Overwatch. 4 entity types, fuzzy matching, dynamic gazetteer.
- **[Animus](https://github.com/AreteDriver/animus)** — AI orchestration with persistent memory, 37 tools, Ollama routing. Would replace the template briefings with context-aware LLM summaries that remember previous sessions.

104 tests, Python 3.11+, FastAPI + SQLite. No external deps beyond what you already run.

Happy to collaborate if this is useful. The architecture is intentionally modular — swap out any piece.

— ARETE

---

## Notes for delivery

- Best sent as a GitHub Discussion on his TheWire-STT repo, or a direct message if available
- Could also open a lightweight issue titled "Thought you might find this useful — tactical dashboard for your ISR workflow"
- Tone is peer-to-peer, not salesy. Shows the work first, mentions Dossier/Animus as natural extensions, not products
