"""Streamlit dashboard for Overwatch tactical ISR."""

from __future__ import annotations

import os

import folium
import folium.plugins as folium_plugins
import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from streamlit_folium import st_folium

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

API_BASE = os.environ.get("OVERWATCH_API_URL", "http://localhost:8080/api").rstrip("/")
API_KEY = os.environ.get("OVERWATCH_API_KEY", "")

st.set_page_config(
    page_title="Overwatch — Tactical Dashboard",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------


def _headers() -> dict[str, str]:
    if API_KEY:
        return {"Authorization": f"Bearer {API_KEY}"}
    return {}


def api_get(path: str, params: dict | None = None):
    try:
        resp = requests.get(f"{API_BASE}{path}", params=params, headers=_headers(), timeout=5)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        return None


def api_post(path: str, json_data=None, params: dict | None = None):
    try:
        resp = requests.post(
            f"{API_BASE}{path}", json=json_data, params=params, headers=_headers(), timeout=10
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        return None


def api_delete(path: str):
    try:
        resp = requests.delete(f"{API_BASE}{path}", headers=_headers(), timeout=5)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        return None


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("Overwatch")
    st.caption("Tactical ISR Dashboard v0.2.0")

    st.divider()

    if st.button("Generate Briefing", use_container_width=True):
        result = api_post("/briefings/generate", params={"lookback_hours": 24})
        if result:
            st.success("Briefing generated")
        else:
            st.error("Failed — is the API running?")

    if st.button("Generate LLM Briefing", use_container_width=True):
        result = api_post(
            "/briefings/generate",
            params={"lookback_hours": 24, "use_ollama": True},
        )
        if result:
            st.success("LLM Briefing generated")
        else:
            st.error("Failed — Ollama may not be running")

    if st.button("Resolve Entities", use_container_width=True):
        result = api_post("/entities/resolve")
        if result is not None:
            st.success(f"Resolved {len(result)} entities")
        else:
            st.error("Failed — is the API running?")

    st.divider()

    # Geofence quick-add
    st.markdown("**Quick Geofence**")
    gf_name = st.text_input("Zone name", key="gf_name")
    gf_coords_str = st.text_area(
        "Coords (lat,lon per line)",
        placeholder="46.05,14.50\n46.06,14.50\n46.06,14.52\n46.05,14.52",
        key="gf_coords",
        height=80,
    )
    if st.button("Add Geofence", use_container_width=True):
        if gf_name and gf_coords_str:
            coords = []
            for line in gf_coords_str.strip().split("\n"):
                parts = line.strip().split(",")
                if len(parts) == 2:
                    coords.append([float(parts[0]), float(parts[1])])
            if len(coords) >= 3:
                result = api_post(
                    "/geofences",
                    json_data={
                        "name": gf_name,
                        "coords": coords,
                    },
                )
                if result:
                    st.success(f"Geofence '{gf_name}' created")

    st.divider()
    st.markdown("**Integration Ready:**")
    st.markdown("- [Dossier](https://github.com/AreteDriver/Dossier) — NER + entity resolution")
    st.markdown("- [Animus](https://github.com/AreteDriver/animus) — LLM briefings + memory")


# ---------------------------------------------------------------------------
# Main content
# ---------------------------------------------------------------------------

stats = api_get("/dashboard/stats")

if stats is None:
    st.error("Cannot reach Overwatch API at " + API_BASE)
    st.info("Start the API: `uvicorn overwatch.app:app --reload --port 8080`")
    st.stop()

# --- KPI row ---
cols = st.columns(7)
cols[0].metric("Detections", stats["total_detections"])
cols[1].metric("Intel", stats["total_intel_reports"])
cols[2].metric("Telemetry", stats["total_telemetry_points"])
cols[3].metric("Entities", stats["total_entities"])
cols[4].metric("Briefings", stats["total_briefings"])
cols[5].metric("Alerts", stats.get("total_alerts", 0))
cols[6].metric("Geofences", stats.get("total_geofences", 0))

# --- Tabs ---
(
    tab_map,
    tab_timeline,
    tab_intel,
    tab_briefing,
    tab_entities,
    tab_mesh,
    tab_alerts,
    tab_replay,
) = st.tabs(
    [
        "Map",
        "Timeline",
        "Intel Feed",
        "Briefing",
        "Entities",
        "Mesh Health",
        "Alerts",
        "Replay",
    ]
)


# ---- MAP TAB (expanded with heatmap, geofences, tools) ----
with tab_map:
    detections = api_get("/detections", {"limit": 500}) or []
    telemetry = api_get("/telemetry", {"limit": 500}) or []
    geofences = api_get("/geofences") or []

    geo_dets = [d for d in detections if d.get("lat") and d.get("lon")]
    geo_telem = [t for t in telemetry if t.get("lat") and t.get("lon")]

    if geo_dets or geo_telem:
        all_lats = [d["lat"] for d in geo_dets] + [t["lat"] for t in geo_telem]
        all_lons = [d["lon"] for d in geo_dets] + [t["lon"] for t in geo_telem]
        center = [
            sum(all_lats) / len(all_lats),
            sum(all_lons) / len(all_lons),
        ]
    else:
        center = [46.05, 14.5]

    m = folium.Map(location=center, zoom_start=12, tiles="CartoDB dark_matter")

    # Map controls
    map_col1, map_col2, map_col3 = st.columns(3)
    show_heatmap = map_col1.checkbox("Heatmap", value=False)
    show_geofences = map_col2.checkbox("Geofences", value=True)
    show_labels = map_col3.checkbox("Labels", value=True)

    # Detection markers
    det_group = folium.FeatureGroup(name="Detections")
    for d in geo_dets:
        color = "red" if d["confidence"] > 0.8 else "orange" if d["confidence"] > 0.5 else "yellow"
        popup_text = (
            f"<b>{d['label']}</b> ({d['confidence']:.0%})<br>"
            f"Source: {d['source_name']}<br>"
            f"Time: {d['detected_at'][:19]}<br>"
            f"Pos: ({d['lat']:.4f}, {d['lon']:.4f})"
        )
        folium.CircleMarker(
            location=[d["lat"], d["lon"]],
            radius=6,
            color=color,
            fill=True,
            popup=folium.Popup(popup_text, max_width=250),
            tooltip=d["label"] if show_labels else "",
        ).add_to(det_group)
    det_group.add_to(m)

    # Telemetry markers with trails
    telem_group = folium.FeatureGroup(name="Assets")
    device_points: dict[str, list] = {}
    for t in geo_telem:
        name = t["device_name"]
        if name not in device_points:
            device_points[name] = []
        device_points[name].append([t["lat"], t["lon"]])

    for t in geo_telem:
        batt = t.get("battery_pct")
        batt_str = f"{batt:.0f}%" if batt is not None else "?"
        icon_color = "red" if batt is not None and batt < 20 else "blue"
        popup_text = (
            f"<b>{t['device_name']}</b><br>"
            f"Alt: {t.get('altitude', '?')}m<br>"
            f"Speed: {t.get('speed', '?')} m/s<br>"
            f"Heading: {t.get('heading', '?')}°<br>"
            f"Battery: {batt_str}<br>"
            f"Time: {t['recorded_at'][:19]}"
        )
        folium.Marker(
            location=[t["lat"], t["lon"]],
            icon=folium.Icon(color=icon_color, icon="plane", prefix="fa"),
            popup=folium.Popup(popup_text, max_width=250),
            tooltip=t["device_name"],
        ).add_to(telem_group)

    # Device trails
    for name, points in device_points.items():
        if len(points) > 1:
            folium.PolyLine(points, color="cyan", weight=2, opacity=0.6).add_to(telem_group)
    telem_group.add_to(m)

    # Heatmap layer
    if show_heatmap and geo_dets:
        heat_data = [[d["lat"], d["lon"]] for d in geo_dets]
        folium_plugins.HeatMap(
            heat_data,
            radius=20,
            blur=15,
            max_zoom=15,
            name="Detection Heatmap",
        ).add_to(m)

    # Geofence overlays
    if show_geofences:
        for gf in geofences:
            coords = gf.get("coords", [])
            if len(coords) >= 3:
                folium.Polygon(
                    locations=coords,
                    color="lime",
                    fill=True,
                    fill_opacity=0.1,
                    weight=2,
                    popup=gf["name"],
                    tooltip=f"Zone: {gf['name']}",
                ).add_to(m)

    # Map tools
    folium_plugins.MeasureControl(
        position="topleft",
        primary_length_unit="meters",
        secondary_length_unit="kilometers",
    ).add_to(m)
    folium_plugins.Draw(
        export=True,
        position="topleft",
        draw_options={
            "polyline": True,
            "polygon": True,
            "circle": True,
            "marker": True,
            "circlemarker": False,
            "rectangle": True,
        },
    ).add_to(m)
    folium_plugins.Fullscreen().add_to(m)
    folium_plugins.MiniMap(tile_layer="CartoDB positron", toggle_display=True).add_to(m)
    folium.LayerControl().add_to(m)
    folium_plugins.MousePosition().add_to(m)

    st_folium(m, use_container_width=True, height=600)


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
            color_discrete_map={
                "detection": "#ff4444",
                "intel": "#44aaff",
            },
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
        st.info("No events yet.")


# ---- INTEL FEED TAB ----
with tab_intel:
    intel = api_get("/intel", {"limit": 20}) or []
    if intel:
        for report in intel:
            with st.expander(
                f"[{report['source_name']}] {report['title']}",
                expanded=False,
            ):
                st.caption(f"Published: {report['published_at'][:19]} UTC")
                st.markdown(report["summary"])
                if report.get("source_url"):
                    st.markdown(f"[Source]({report['source_url']})")
    else:
        st.info("No intel reports yet.")


# ---- BRIEFING TAB (with export) ----
with tab_briefing:
    briefing = api_get("/briefings/latest")
    if briefing:
        st.markdown(f"### {briefing['title']}")
        st.caption(f"Generated: {briefing['created_at'][:19]} UTC")
        st.markdown(briefing["body"])

        # Export button
        st.download_button(
            label="Download Briefing (.md)",
            data=briefing["body"],
            file_name=f"sitrep-{briefing['created_at'][:10]}.md",
            mime="text/markdown",
        )

        # History
        all_briefings = api_get("/briefings", {"limit": 5}) or []
        if len(all_briefings) > 1:
            st.divider()
            st.markdown("**Recent Briefings:**")
            for b in all_briefings:
                st.caption(f"- {b['title']} ({b['created_at'][:19]})")
    else:
        st.info("No briefings yet. Click 'Generate Briefing' in sidebar.")


# ---- ENTITIES TAB (with timeline drill-down) ----
with tab_entities:
    entities = api_get("/entities", {"limit": 50}) or []
    if entities:
        df_ent = pd.DataFrame(entities)
        display_cols = [
            "canonical_name",
            "entity_type",
            "sighting_count",
            "first_seen",
            "last_seen",
        ]
        df_display = df_ent[display_cols].copy()
        df_display.columns = [
            "Name",
            "Type",
            "Sightings",
            "First Seen",
            "Last Seen",
        ]
        st.dataframe(df_display, use_container_width=True, hide_index=True)

        # Entity timeline drill-down
        st.divider()
        st.markdown("**Entity Timeline**")
        entity_names = {e["id"]: e["canonical_name"] for e in entities}
        selected = st.selectbox(
            "Select entity",
            options=list(entity_names.keys()),
            format_func=lambda x: entity_names[x],
        )
        if selected:
            timeline = api_get(f"/entities/{selected}/timeline") or []
            if timeline:
                df_tl = pd.DataFrame(timeline)
                df_tl["timestamp"] = pd.to_datetime(df_tl["timestamp"])
                fig = px.scatter(
                    df_tl,
                    x="timestamp",
                    y="source_type",
                    color="source_type",
                    hover_data=["label", "source_id"],
                    title=f"Timeline: {entity_names[selected]}",
                    color_discrete_map={
                        "detection": "#ff4444",
                        "intel": "#44aaff",
                    },
                )
                fig.update_layout(
                    template="plotly_dark",
                    height=300,
                    yaxis_title="",
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No timeline data for this entity.")
    else:
        st.info("No entities yet.")


# ---- MESH HEALTH TAB ----
with tab_mesh:
    devices = api_get("/mesh/health") or []
    if devices:
        for dev in devices:
            status = dev["status"]
            icon = "🟢" if status == "online" else "🟡" if status == "stale" else "🔴"
            batt = dev.get("battery_pct")
            batt_str = f"{batt:.0f}%" if batt is not None else "?"
            staleness = dev["staleness_seconds"]

            if staleness < 60:
                stale_str = f"{staleness:.0f}s ago"
            elif staleness < 3600:
                stale_str = f"{staleness / 60:.0f}m ago"
            else:
                stale_str = f"{staleness / 3600:.1f}h ago"

            col_a, col_b, col_c, col_d = st.columns([3, 2, 2, 2])
            col_a.markdown(f"{icon} **{dev['device_name']}**")
            col_b.caption(f"Battery: {batt_str}")
            col_c.caption(f"Last seen: {stale_str}")
            col_d.caption(f"({dev['lat']:.4f}, {dev['lon']:.4f})")
    else:
        st.info("No devices reporting telemetry yet.")


# ---- ALERTS TAB ----
with tab_alerts:
    alerts = api_get("/alerts", {"limit": 50}) or []
    if alerts:
        for alert in alerts:
            sev = alert["severity"]
            icon = "🔴" if sev == "critical" else "🟡" if sev == "warning" else "🔵"
            acked = alert.get("acknowledged", False)
            prefix = "~~" if acked else ""
            suffix = "~~ *(ack)*" if acked else ""

            st.markdown(f"{icon} {prefix}**[{alert['alert_type']}]** {alert['title']}{suffix}")
            st.caption(
                f"{alert['created_at'][:19]} UTC"
                + (f" | ({alert['lat']:.4f}, {alert['lon']:.4f})" if alert.get("lat") else "")
            )
    else:
        st.info("No alerts yet.")


# ---- REPLAY TAB ----
with tab_replay:
    time_range = api_get("/replay/range")
    if time_range and time_range.get("earliest") and time_range.get("latest"):
        st.markdown("**Mission Replay**")
        st.caption(f"Data range: {time_range['earliest'][:19]} to {time_range['latest'][:19]} UTC")

        replay_start = st.text_input("Start (ISO)", value=time_range["earliest"][:19])
        replay_end = st.text_input("End (ISO)", value=time_range["latest"][:19])

        if st.button("Load Replay Frame"):
            frame = api_get(
                "/replay/frame",
                {"start": replay_start, "end": replay_end},
            )
            if frame:
                dets = frame.get("detections", [])
                telem = frame.get("telemetry", [])

                st.metric("Detections in frame", len(dets))
                st.metric("Telemetry in frame", len(telem))

                # Replay map
                geo = [d for d in dets if d.get("lat") and d.get("lon")] + [
                    t for t in telem if t.get("lat") and t.get("lon")
                ]
                if geo:
                    lats = [g.get("lat") for g in geo]
                    lons = [g.get("lon") for g in geo]
                    center = [
                        sum(lats) / len(lats),
                        sum(lons) / len(lons),
                    ]
                    rm = folium.Map(
                        location=center,
                        zoom_start=13,
                        tiles="CartoDB dark_matter",
                    )
                    for d in dets:
                        if d.get("lat") and d.get("lon"):
                            folium.CircleMarker(
                                [d["lat"], d["lon"]],
                                radius=5,
                                color="red",
                                fill=True,
                                tooltip=d.get("label", ""),
                            ).add_to(rm)
                    for t in telem:
                        if t.get("lat") and t.get("lon"):
                            folium.Marker(
                                [t["lat"], t["lon"]],
                                icon=folium.Icon(
                                    color="blue",
                                    icon="plane",
                                    prefix="fa",
                                ),
                                tooltip=t.get("device_name", ""),
                            ).add_to(rm)
                    st_folium(rm, use_container_width=True, height=400)
            else:
                st.error("Failed to load replay frame.")
    else:
        st.info("No data available for replay.")
