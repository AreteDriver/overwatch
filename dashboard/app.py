"""Streamlit dashboard for Overwatch tactical ISR."""

from __future__ import annotations

import folium
import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from streamlit_folium import st_folium

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

API_BASE = "http://localhost:8000/api"

st.set_page_config(
    page_title="Overwatch — Tactical Dashboard",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------


def api_get(path: str, params: dict | None = None) -> dict | list | None:
    try:
        resp = requests.get(f"{API_BASE}{path}", params=params, timeout=5)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        return None


def api_post(path: str, json_data: dict | None = None, params: dict | None = None):
    try:
        resp = requests.post(f"{API_BASE}{path}", json=json_data, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        return None


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("Overwatch")
    st.caption("Tactical ISR Dashboard v0.1.0")

    st.divider()

    if st.button("Generate Briefing", use_container_width=True):
        result = api_post("/briefings/generate", params={"lookback_hours": 24})
        if result:
            st.success("Briefing generated")
        else:
            st.error("Failed — is the API running?")

    if st.button("Resolve Entities", use_container_width=True):
        result = api_post("/entities/resolve")
        if result is not None:
            st.success(f"Resolved {len(result)} entities")
        else:
            st.error("Failed — is the API running?")

    st.divider()
    st.markdown("**Integration Ready:**")
    st.markdown("- [Dossier](https://github.com/AreteDriver/Dossier) — NER + entity resolution")
    st.markdown("- [Animus](https://github.com/AreteDriver/animus) — LLM briefings + memory")

    st.divider()
    st.markdown(
        "*Built for mesh-net ISR workflows.*\n\n"
        "Feed YOLO detections, OSINT intel, and drone telemetry into one operational picture."
    )


# ---------------------------------------------------------------------------
# Main content
# ---------------------------------------------------------------------------

stats = api_get("/dashboard/stats")

if stats is None:
    st.error("Cannot reach Overwatch API at " + API_BASE)
    st.info("Start the API: `uvicorn overwatch.app:app --reload --port 8000`")
    st.stop()

# --- KPI row ---
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Detections", stats["total_detections"])
col2.metric("Intel Reports", stats["total_intel_reports"])
col3.metric("Telemetry", stats["total_telemetry_points"])
col4.metric("Entities", stats["total_entities"])
col5.metric("Briefings", stats["total_briefings"])

# --- Tabs ---
tab_map, tab_timeline, tab_intel, tab_briefing, tab_entities = st.tabs(
    ["Map", "Timeline", "Intel Feed", "Briefing", "Entities"]
)

# ---- MAP TAB ----
with tab_map:
    detections = api_get("/detections", {"limit": 200}) or []
    telemetry = api_get("/telemetry", {"limit": 200}) or []

    geo_dets = [d for d in detections if d.get("lat") and d.get("lon")]
    geo_telem = [t for t in telemetry if t.get("lat") and t.get("lon")]

    if geo_dets or geo_telem:
        all_lats = [d["lat"] for d in geo_dets] + [t["lat"] for t in geo_telem]
        all_lons = [d["lon"] for d in geo_dets] + [t["lon"] for t in geo_telem]
        center = [sum(all_lats) / len(all_lats), sum(all_lons) / len(all_lons)]
    else:
        center = [46.05, 14.5]  # Ljubljana default (Rok's area)

    m = folium.Map(location=center, zoom_start=10, tiles="CartoDB dark_matter")

    for d in geo_dets:
        color = "red" if d["confidence"] > 0.8 else "orange" if d["confidence"] > 0.5 else "yellow"
        folium.CircleMarker(
            location=[d["lat"], d["lon"]],
            radius=6,
            color=color,
            fill=True,
            popup=f"{d['label']} ({d['confidence']:.0%})<br>{d['detected_at'][:19]}",
            tooltip=d["label"],
        ).add_to(m)

    for t in geo_telem:
        folium.Marker(
            location=[t["lat"], t["lon"]],
            icon=folium.Icon(color="blue", icon="plane", prefix="fa"),
            popup=(
                f"{t['device_name']}<br>"
                f"Alt: {t.get('altitude', '?')}m | Batt: {t.get('battery_pct', '?')}%"
            ),
            tooltip=t["device_name"],
        ).add_to(m)

    st_folium(m, use_container_width=True, height=500)

# ---- TIMELINE TAB ----
with tab_timeline:
    events = []
    for d in detections:
        events.append(
            {
                "time": d["detected_at"],
                "type": "detection",
                "label": d["label"],
                "source": d["source_name"],
            }
        )

    intel = api_get("/intel", {"limit": 100}) or []
    for r in intel:
        events.append(
            {
                "time": r["published_at"],
                "type": "intel",
                "label": r["title"][:50],
                "source": r["source_name"],
            }
        )

    if events:
        df = pd.DataFrame(events)
        df["time"] = pd.to_datetime(df["time"])
        df = df.sort_values("time", ascending=False)

        fig = px.scatter(
            df,
            x="time",
            y="type",
            color="type",
            hover_data=["label", "source"],
            title="Event Timeline",
            color_discrete_map={"detection": "#ff4444", "intel": "#44aaff"},
        )
        fig.update_layout(
            template="plotly_dark",
            height=400,
            yaxis_title="",
            xaxis_title="",
        )
        st.plotly_chart(fig, use_container_width=True)

        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No events yet. Ingest data via the API to see the timeline.")

# ---- INTEL FEED TAB ----
with tab_intel:
    intel = api_get("/intel", {"limit": 20}) or []
    if intel:
        for report in intel:
            with st.expander(f"[{report['source_name']}] {report['title']}", expanded=False):
                st.caption(f"Published: {report['published_at'][:19]} UTC")
                st.markdown(report["summary"])
                if report.get("source_url"):
                    st.markdown(f"[Source]({report['source_url']})")
    else:
        st.info("No intel reports yet. Feed data from TheWire-STT or post to `/api/ingest/intel`.")

# ---- BRIEFING TAB ----
with tab_briefing:
    briefing = api_get("/briefings/latest")
    if briefing:
        st.markdown(f"### {briefing['title']}")
        st.caption(f"Generated: {briefing['created_at'][:19]} UTC")
        st.markdown(briefing["body"])
    else:
        st.info("No briefings yet. Click 'Generate Briefing' in the sidebar.")

# ---- ENTITIES TAB ----
with tab_entities:
    entities = api_get("/entities", {"limit": 50}) or []
    if entities:
        df_ent = pd.DataFrame(entities)
        df_ent = df_ent[
            ["canonical_name", "entity_type", "sighting_count", "first_seen", "last_seen"]
        ]
        df_ent.columns = ["Name", "Type", "Sightings", "First Seen", "Last Seen"]
        st.dataframe(df_ent, use_container_width=True, hide_index=True)
    else:
        st.info("No entities yet. Click 'Resolve Entities' in the sidebar after ingesting data.")
