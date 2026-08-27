from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import altair as alt
import pandas as pd
import pydeck as pdk
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]

STATEWIDE_POINTS = ROOT / "data" / "gold" / "statewide_severe_crashes.parquet"
STATEWIDE_COUNTY = ROOT / "data" / "gold" / "statewide_county_summary.parquet"
STATEWIDE_ROUTE = ROOT / "data" / "gold" / "statewide_route_summary.parquet"
EXECUTIVE = ROOT / "data" / "gold" / "executive_corridors_v4.parquet"
DRIVERS = ROOT / "data" / "gold" / "corridor_driver_analysis_v1.parquet"

PHASE2B_REPORT = ROOT / "reports" / "phase2b_spatial.json"
PHASE2C_REPORT = ROOT / "reports" / "phase2c_statistical_validation.json"
PHASE3B_REPORT = ROOT / "reports" / "phase3b_statewide_explorer.json"
CURRENT_YEAR_CRASHES = ROOT / "data" / "gold" / "current_year_crashes.parquet"
CURRENT_YEAR_COUNTY = ROOT / "data" / "gold" / "current_year_county_summary.parquet"
CURRENT_YEAR_ROUTE = ROOT / "data" / "gold" / "current_year_route_summary.parquet"
CURRENT_YEAR_COMPARE = ROOT / "data" / "gold" / "current_year_ytd_comparison.parquet"
CURRENT_YEAR_MONTHLY = ROOT / "data" / "gold" / "current_year_monthly_trend.parquet"
PHASE3C_REPORT = ROOT / "reports" / "phase3c_current_year_monitor.json"
PIPELINE_REPORT = ROOT / "reports" / "pipeline_run.json"
INCREMENTAL_HIST_REPORT = ROOT / "reports" / "incremental_historical_refresh.json"
INCREMENTAL_CURRENT_REPORT = ROOT / "reports" / "incremental_current_refresh.json"

st.set_page_config(
    page_title="UDOT SafeCorridor Intelligence",
    page_icon="🛣️",
    layout="wide",
)

# -------------------------------------------------------------------
# Color accessibility
# -------------------------------------------------------------------
COLOR_THEMES = {
    "Standard Utah palette": {
        "primary": "#0B2444",     # Utah-inspired navy
        "danger": "#AF1F24",      # Utah-inspired red
        "accent": "#FBB217",      # Utah-inspired gold
        "background": "#FFFFFF",
        "surface": "#F5F7FA",
        "text_muted": "#44546A",
        "border": "#D7DEE8",
        "pale_primary": "#EAF0F7",
        "pale_accent": "#FFF6D8",
        "pale_danger": "#FCEBEC",
    },
    "Color-accessible palette": {
        # Okabe-Ito-inspired high-separation colors.
        "primary": "#0072B2",     # blue
        "danger": "#D55E00",      # vermillion
        "accent": "#CC79A7",      # reddish purple
        "background": "#FFFFFF",
        "surface": "#F7F7F7",
        "text_muted": "#3F3F3F",
        "border": "#C8C8C8",
        "pale_primary": "#E8F3F8",
        "pale_accent": "#F6EAF2",
        "pale_danger": "#FBEDE7",
    },
    "High contrast": {
        "primary": "#000000",
        "danger": "#8B0000",
        "accent": "#E3A400",
        "background": "#FFFFFF",
        "surface": "#F2F2F2",
        "text_muted": "#202020",
        "border": "#707070",
        "pale_primary": "#ECECEC",
        "pale_accent": "#FFF4C2",
        "pale_danger": "#F7E3E3",
    },
}

color_mode = st.sidebar.selectbox(
    "Color accessibility",
    options=list(COLOR_THEMES.keys()),
    index=0,
    help=(
        "Choose a viewing palette. Charts also use numeric labels, legends, "
        "marker size, and outlines so important information is not communicated "
        "by color alone."
    ),
)

theme = COLOR_THEMES[color_mode]

UTAH_NAVY = theme["primary"]
UTAH_RED = theme["danger"]
UTAH_GOLD = theme["accent"]
UTAH_WHITE = theme["background"]
UTAH_LIGHT = theme["surface"]
UTAH_SLATE = theme["text_muted"]
UTAH_BORDER = theme["border"]
UTAH_PALE_BLUE = theme["pale_primary"]
UTAH_PALE_GOLD = theme["pale_accent"]
UTAH_PALE_RED = theme["pale_danger"]


def hex_to_rgb(hex_color: str, alpha: int | None = None):
    value = hex_color.lstrip("#")
    rgb = [int(value[i:i + 2], 16) for i in (0, 2, 4)]
    return rgb + [alpha] if alpha is not None else rgb


MAP_SEVERE = hex_to_rgb(UTAH_GOLD, 180)
MAP_FATAL = hex_to_rgb(UTAH_RED, 225)
MAP_PRIORITY = hex_to_rgb(UTAH_NAVY, 215)
MAP_OUTLINE = hex_to_rgb(UTAH_GOLD, 245)

st.markdown(
    f"""
    <style>
    /* ---------- Page ---------- */
    .stApp {{
        background-color: {UTAH_WHITE};
    }}

    /* ---------- Headings ---------- */
    h1, h2, h3 {{
        color: {UTAH_NAVY} !important;
    }}

    /* ---------- Horizontal rules ---------- */
    hr {{
        border-color: {UTAH_BORDER} !important;
    }}

    /* ---------- Tabs ---------- */
    button[data-baseweb="tab"] {{
        color: {UTAH_SLATE} !important;
        font-weight: 600;
    }}
    button[data-baseweb="tab"][aria-selected="true"] {{
        color: {UTAH_NAVY} !important;
    }}
    div[data-baseweb="tab-highlight"] {{
        background-color: {UTAH_GOLD} !important;
    }}

    /* ---------- Metric cards ---------- */
    div[data-testid="stMetric"] {{
        background: {UTAH_LIGHT};
        border: 1px solid {UTAH_BORDER};
        border-top: 4px solid {UTAH_NAVY};
        border-radius: 10px;
        padding: 0.8rem 0.9rem;
    }}
    div[data-testid="stMetricLabel"] {{
        color: {UTAH_SLATE};
    }}
    div[data-testid="stMetricValue"] {{
        color: {UTAH_NAVY};
    }}

    /* ---------- Info / success / warning ---------- */
    div[data-testid="stAlert"] {{
        border-radius: 8px;
    }}

    /* ---------- Inputs ---------- */
    div[data-baseweb="select"] > div {{
        border-color: {UTAH_BORDER} !important;
    }}

    /* ---------- Dataframes ---------- */
    div[data-testid="stDataFrame"] {{
        border: 1px solid {UTAH_BORDER};
        border-radius: 8px;
        overflow: hidden;
    }}

    /* ---------- Captions ---------- */
    .stCaption {{
        color: {UTAH_SLATE} !important;
    }}

    /* ---------- Links ---------- */
    a {{
        color: {UTAH_NAVY};
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("UDOT SafeCorridor Intelligence")
st.caption(
    "Independent analytical proof-of-concept using publicly available UDOT data. "
    "Not affiliated with or endorsed by UDOT."
)

st.caption(
    f"Viewing palette: **{color_mode}**. Critical values are also communicated "
    "with text labels, marker size, outlines, and tables—not color alone."
)

required = [STATEWIDE_POINTS, EXECUTIVE, DRIVERS]
missing = [str(p.relative_to(ROOT)) for p in required if not p.exists()]
if missing:
    st.error(
        "Required Phase 3 datasets are missing:\n\n- "
        + "\n- ".join(missing)
    )
    st.stop()

statewide = pd.read_parquet(STATEWIDE_POINTS)
executive = pd.read_parquet(EXECUTIVE).sort_values("executive_rank")
drivers = pd.read_parquet(DRIVERS).sort_values("executive_rank")

county_summary = (
    pd.read_parquet(STATEWIDE_COUNTY)
    if STATEWIDE_COUNTY.exists()
    else pd.DataFrame()
)
route_summary = (
    pd.read_parquet(STATEWIDE_ROUTE)
    if STATEWIDE_ROUTE.exists()
    else pd.DataFrame()
)

phase2b = (
    json.loads(PHASE2B_REPORT.read_text(encoding="utf-8"))
    if PHASE2B_REPORT.exists()
    else {}
)
phase2c = (
    json.loads(PHASE2C_REPORT.read_text(encoding="utf-8"))
    if PHASE2C_REPORT.exists()
    else {}
)
phase3b = (
    json.loads(PHASE3B_REPORT.read_text(encoding="utf-8"))
    if PHASE3B_REPORT.exists()
    else {}
)
phase3c = (
    json.loads(PHASE3C_REPORT.read_text(encoding="utf-8"))
    if PHASE3C_REPORT.exists()
    else {}
)
pipeline_report = (
    json.loads(PIPELINE_REPORT.read_text(encoding="utf-8"))
    if PIPELINE_REPORT.exists()
    else {}
)
incremental_hist = (
    json.loads(INCREMENTAL_HIST_REPORT.read_text(encoding="utf-8"))
    if INCREMENTAL_HIST_REPORT.exists()
    else {}
)
incremental_current = (
    json.loads(INCREMENTAL_CURRENT_REPORT.read_text(encoding="utf-8"))
    if INCREMENTAL_CURRENT_REPORT.exists()
    else {}
)
current_year_crashes = (
    pd.read_parquet(CURRENT_YEAR_CRASHES)
    if CURRENT_YEAR_CRASHES.exists()
    else pd.DataFrame()
)
current_year_county = (
    pd.read_parquet(CURRENT_YEAR_COUNTY)
    if CURRENT_YEAR_COUNTY.exists()
    else pd.DataFrame()
)
current_year_route = (
    pd.read_parquet(CURRENT_YEAR_ROUTE)
    if CURRENT_YEAR_ROUTE.exists()
    else pd.DataFrame()
)
current_year_compare = (
    pd.read_parquet(CURRENT_YEAR_COMPARE)
    if CURRENT_YEAR_COMPARE.exists()
    else pd.DataFrame()
)
current_year_monthly = (
    pd.read_parquet(CURRENT_YEAR_MONTHLY)
    if CURRENT_YEAR_MONTHLY.exists()
    else pd.DataFrame()
)

# Friendly route labels for statewide explorer.
statewide["route_label"] = statewide["route_num"].apply(
    lambda x: f"Route {int(x)}" if pd.notna(x) else "Unknown"
)
statewide["county_name"] = statewide["county_name"].fillna("Unknown")

if not current_year_crashes.empty:
    current_year_crashes["county_name"] = (
        current_year_crashes["county_name"].fillna("Unknown")
    )
    current_year_crashes["route_label"] = current_year_crashes["route_num"].apply(
        lambda x: f"Route {int(x)}" if pd.notna(x) else "Unknown"
    )
    if "crash_date" in current_year_crashes.columns:
        current_year_crashes["crash_date"] = current_year_crashes["crash_date"].astype(str)

# -------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------
UTAH_TIMEZONE = ZoneInfo("America/Denver")
SCHEDULE_WEEKDAY = 0  # Monday
SCHEDULE_HOUR_UTC = 10
SCHEDULE_MINUTE_UTC = 17


def _parse_utc_timestamp(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_utah_datetime(value):
    parsed = value if isinstance(value, datetime) else _parse_utc_timestamp(value)
    if parsed is None:
        return "Not available yet"
    local = parsed.astimezone(UTAH_TIMEZONE)
    hour = local.strftime("%I").lstrip("0") or "12"
    return f"{local.strftime('%b %d, %Y')} · {hour}:{local.strftime('%M %p %Z')}"


def _next_scheduled_refresh(now_utc=None):
    now_utc = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    days_ahead = (SCHEDULE_WEEKDAY - now_utc.weekday()) % 7
    candidate = (now_utc + timedelta(days=days_ahead)).replace(
        hour=SCHEDULE_HOUR_UTC,
        minute=SCHEDULE_MINUTE_UTC,
        second=0,
        microsecond=0,
    )
    if candidate <= now_utc:
        candidate += timedelta(days=7)
    return candidate


def _latest_successful_refresh():
    candidates = []
    if pipeline_report.get("status") == "success":
        candidates.append(_parse_utc_timestamp(pipeline_report.get("finished_at_utc")))
    if phase3c.get("status") == "success":
        candidates.append(_parse_utc_timestamp(phase3c.get("generated_at_utc")))
    if incremental_hist.get("status") == "success":
        candidates.append(_parse_utc_timestamp(incremental_hist.get("generated_at_utc")))
    if incremental_current.get("status") == "success":
        candidates.append(_parse_utc_timestamp(incremental_current.get("generated_at_utc")))
    candidates = [value for value in candidates if value is not None]
    return max(candidates) if candidates else None


def _refresh_mode_label():
    mode = incremental_current.get("mode")
    labels = {
        "cache_reuse": "Cache reuse",
        "incremental_reconcile": "Incremental reconcile",
        "full_refresh": "Full reconciliation",
        "full_refresh_forced": "Full reconciliation",
        "full_refresh_fallback": "Full fallback refresh",
    }
    if mode:
        return labels.get(mode, str(mode).replace("_", " ").title())
    status = incremental_current.get("status")
    if status == "current_layer_unavailable":
        return "Current layer unavailable"
    return "Awaiting first refresh"


def _historical_cache_label():
    years = incremental_hist.get("years") or []
    if not years:
        return "Awaiting first refresh"
    reused = sum(1 for item in years if item.get("mode") == "cache_reuse")
    refreshed = sum(1 for item in years if item.get("mode") == "full_refresh")
    return f"{reused} reused · {refreshed} refreshed"

def filtered_multiselect(label, options, key, help_text=None, placeholder=None):
    """Native Streamlit multiselect; empty selection means All."""
    return st.multiselect(
        label,
        options=sorted(options),
        default=[],
        key=key,
        help=help_text,
        placeholder=placeholder or f"All {label.lower()}",
    )


def labeled_bar_chart(
    data: pd.DataFrame,
    category: str,
    value: str,
    title: str | None = None,
    value_format: str = ",.0f",
    horizontal: bool = True,
    bar_color: str = UTAH_NAVY,
):
    """Altair bar chart with always-visible value labels."""
    base = alt.Chart(data)

    if horizontal:
        bars = base.mark_bar(color=bar_color).encode(
            y=alt.Y(f"{category}:N", sort="-x", title=None),
            x=alt.X(f"{value}:Q", title=value),
            tooltip=[
                alt.Tooltip(f"{category}:N", title=category),
                alt.Tooltip(f"{value}:Q", title=value, format=value_format),
            ],
        )
        labels = base.mark_text(
            align="left",
            baseline="middle",
            dx=4,
            color=UTAH_NAVY,
        ).encode(
            y=alt.Y(f"{category}:N", sort="-x"),
            x=alt.X(f"{value}:Q"),
            text=alt.Text(f"{value}:Q", format=value_format),
        )
    else:
        bars = base.mark_bar(color=bar_color).encode(
            x=alt.X(f"{category}:N", sort="-y", title=None),
            y=alt.Y(f"{value}:Q", title=value),
            tooltip=[
                alt.Tooltip(f"{category}:N", title=category),
                alt.Tooltip(f"{value}:Q", title=value, format=value_format),
            ],
        )
        labels = base.mark_text(
            align="center",
            baseline="bottom",
            dy=-3,
            color=UTAH_NAVY,
        ).encode(
            x=alt.X(f"{category}:N", sort="-y"),
            y=alt.Y(f"{value}:Q"),
            text=alt.Text(f"{value}:Q", format=value_format),
        )

    chart = (bars + labels).properties(title=title) if title else (bars + labels)
    st.altair_chart(chart, use_container_width=True)


def auto_view(df, default_lat=39.32, default_lon=-111.67, default_zoom=5.3):
    if df.empty:
        return pdk.ViewState(
            latitude=default_lat,
            longitude=default_lon,
            zoom=default_zoom,
            pitch=0,
        )

    lat_min, lat_max = float(df["lat"].min()), float(df["lat"].max())
    lon_min, lon_max = float(df["lon"].min()), float(df["lon"].max())

    center_lat = (lat_min + lat_max) / 2
    center_lon = (lon_min + lon_max) / 2

    span = max(lat_max - lat_min, lon_max - lon_min)

    if len(df) == 1:
        zoom = 9.5
    elif span <= 0.1:
        zoom = 9.5
    elif span <= 0.3:
        zoom = 8.3
    elif span <= 0.7:
        zoom = 7.2
    elif span <= 1.5:
        zoom = 6.4
    elif span <= 3:
        zoom = 5.7
    else:
        zoom = 5.1

    return pdk.ViewState(
        latitude=center_lat,
        longitude=center_lon,
        zoom=zoom,
        pitch=0,
    )


# -------------------------------------------------------------------
# Tabs
# -------------------------------------------------------------------
monitor_year = phase3c.get("current_year")
if monitor_year is None:
    monitor_year = pd.Timestamp.utcnow().year

tab_statewide, tab_current, tab_priority, tab_why, tab_refresh, tab_method = st.tabs(
    [
        "1. Historical Statewide",
        f"2. {monitor_year} YTD Monitor",
        "3. Priority Corridors",
        "4. Why This Corridor?",
        "5. Data Refresh",
        "6. Methodology",
    ]
)

# ===================================================================
# TAB 1 — STATEWIDE EXPLORER
# ===================================================================
with tab_statewide:
    historical_years = sorted(
        int(y) for y in statewide["crash_year"].dropna().unique().tolist()
    )
    historical_window = (
        f"{historical_years[0]}–{historical_years[-1]}"
        if historical_years else "completed years"
    )
    st.header("Historical statewide safety picture")
    st.write(
        f"This view shows severe crashes from **{historical_window} completed years**. "
        "The partial calendar year is intentionally kept out of the historical "
        "priority model and appears in the YTD Monitor instead."
    )

    severe_total = len(statewide)
    fatal_total = int(statewide["fatal_crash_flag"].sum())
    counties_total = statewide["county_name"].nunique()
    routes_total = statewide.loc[
        statewide["route_num"].notna(), "route_num"
    ].nunique()

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Severe crashes", f"{severe_total:,}")
    k2.metric("Fatal crashes", f"{fatal_total:,}")
    k3.metric("Counties represented", f"{counties_total:,}")
    k4.metric("Routes represented", f"{routes_total:,}")

    st.subheader("Explore severe crashes")

    counties = statewide["county_name"].dropna().unique().tolist()

    years = sorted(
        [
            int(y)
            for y in statewide["crash_year"].dropna().unique().tolist()
            if pd.notna(y)
        ]
    )

    f1, f2, f3 = st.columns(3)

    with f1:
        sw_counties = filtered_multiselect(
            "Counties",
            counties,
            "sw_counties",
            help_text=(
                "Use Streamlit's Select all option, select one or more counties, "
                "or leave blank to include all counties."
            ),
            placeholder="All counties",
        )

    # Route choices cascade from the selected county/county set.
    route_scope = statewide
    if sw_counties:
        route_scope = route_scope[
            route_scope["county_name"].isin(sw_counties)
        ]
    available_routes = route_scope["route_label"].dropna().unique().tolist()

    # Clear stale route selections if a County change makes them invalid.
    if "sw_routes" in st.session_state:
        valid_route_values = [
            r for r in st.session_state["sw_routes"]
            if r in available_routes
        ]
        if valid_route_values != st.session_state["sw_routes"]:
            st.session_state["sw_routes"] = valid_route_values

    with f2:
        sw_routes = filtered_multiselect(
            "Routes",
            available_routes,
            "sw_routes",
            help_text=(
                "Route choices update automatically from the selected county. "
                "Use Select all, choose specific routes, or leave blank for all "
                "routes available in the selected county scope."
            ),
            placeholder="All available routes",
        )

    with f3:
        if years:
            selected_years = st.multiselect(
                "Years",
                options=years,
                default=[],
                key="sw_years",
                help=(
                    "Use Streamlit's Select all option, select specific years, "
                    "or leave blank to include all years."
                ),
                placeholder="All years",
            )
        else:
            selected_years = []

    sw_filtered = statewide.copy()

    if sw_counties:
        sw_filtered = sw_filtered[
            sw_filtered["county_name"].isin(sw_counties)
        ]

    if sw_routes:
        sw_filtered = sw_filtered[
            sw_filtered["route_label"].isin(sw_routes)
        ]

    if years and selected_years:
        sw_filtered = sw_filtered[
            sw_filtered["crash_year"].isin(selected_years)
        ]

    if sw_filtered.empty:
        st.warning("No severe crashes match the selected statewide filters.")
    else:
        fm1, fm2, fm3 = st.columns(3)
        fm1.metric("Filtered severe crashes", f"{len(sw_filtered):,}")
        fm2.metric(
            "Filtered fatal crashes",
            f"{int(sw_filtered['fatal_crash_flag'].sum()):,}",
        )
        fm3.metric(
            "Counties in current view",
            f"{sw_filtered['county_name'].nunique():,}",
        )

        st.subheader("Statewide severe-crash map")

        map_points = sw_filtered.rename(
            columns={"latitude": "lat", "longitude": "lon"}
        ).dropna(subset=["lat", "lon"]).copy()

        fatal_pts = map_points[map_points["fatal_crash_flag"] == 1].copy()
        serious_pts = map_points[map_points["fatal_crash_flag"] != 1].copy()

        layers = []

        if not serious_pts.empty:
            layers.append(
                pdk.Layer(
                    "ScatterplotLayer",
                    data=serious_pts,
                    get_position="[lon, lat]",
                    get_radius=450,
                    radius_min_pixels=2,
                    radius_max_pixels=7,
                    get_fill_color=MAP_SEVERE,
                    pickable=True,
                    auto_highlight=True,
                )
            )

        if not fatal_pts.empty:
            layers.append(
                pdk.Layer(
                    "ScatterplotLayer",
                    data=fatal_pts,
                    get_position="[lon, lat]",
                    get_radius=650,
                    radius_min_pixels=3,
                    radius_max_pixels=9,
                    get_fill_color=MAP_FATAL,
                    get_line_color=[255, 255, 255, 235],
                    line_width_min_pixels=1,
                    stroked=True,
                    pickable=True,
                    auto_highlight=True,
                )
            )

        view = auto_view(map_points)

        deck = pdk.Deck(
            map_style=(
                "https://basemaps.cartocdn.com/"
                "gl/positron-gl-style/style.json"
            ),
            initial_view_state=view,
            layers=layers,
            tooltip={
                "html": (
                    "<b>{county_name} County</b><br/>"
                    "Route: {route_label}<br/>"
                    "Year: {crash_year}<br/>"
                    "Fatal crash flag: {fatal_crash_flag}"
                )
            },
        )

        st.pydeck_chart(deck, use_container_width=True)

        st.caption(
            "Orange points represent severe non-fatal crashes; red points represent "
            "fatal crashes. This map answers **where severe crashes occur**, not "
            "whether a corridor is statistically elevated after exposure adjustment."
        )

        if years:
            st.subheader("Severe crashes over time")
            year_chart = (
                sw_filtered.dropna(subset=["crash_year"])
                .groupby("crash_year")
                .agg(
                    Severe_crashes=("crash_id", "count"),
                    Fatal_crashes=("fatal_crash_flag", "sum"),
                )
                .sort_index()
            )
            year_plot = year_chart.reset_index().melt(
                id_vars="crash_year",
                var_name="Series",
                value_name="Crashes",
            )

            year_lines = (
                alt.Chart(year_plot)
                .mark_line(point=True, strokeWidth=3)
                .encode(
                    x=alt.X("crash_year:O", title="Year"),
                    y=alt.Y("Crashes:Q", title="Crash count"),
                    color=alt.Color(
                        "Series:N",
                        title=None,
                        scale=alt.Scale(
                            domain=["Severe_crashes", "Fatal_crashes"],
                            range=[UTAH_NAVY, UTAH_RED],
                        ),
                    ),
                    tooltip=[
                        alt.Tooltip("crash_year:O", title="Year"),
                        alt.Tooltip("Series:N"),
                        alt.Tooltip("Crashes:Q", format=",.0f"),
                    ],
                )
            )
            st.altair_chart(year_lines, use_container_width=True)

        st.subheader("Counties with the most severe crashes")
        county_chart = (
            sw_filtered.groupby("county_name")
            .size()
            .sort_values(ascending=False)
            .head(15)
            .rename("Severe crashes")
            .reset_index()
            .rename(columns={"county_name": "County"})
        )
        labeled_bar_chart(
            county_chart,
            category="County",
            value="Severe crashes",
            value_format=",.0f",
            horizontal=True,
            bar_color=UTAH_NAVY,
        )

# ===================================================================
# TAB 2 — CURRENT-YEAR MONITOR
# ===================================================================
with tab_current:
    current_status = phase3c.get("status", "not_generated")
    current_year = int(phase3c.get("current_year", monitor_year))

    st.header(f"{current_year} year-to-date safety monitor")
    st.write(
        "This view is intentionally separate from the historical corridor model. "
        "It tracks the **partial current year** and compares it with the same "
        "calendar period in completed prior years."
    )

    if current_status != "success" or current_year_crashes.empty:
        message = phase3c.get(
            "message",
            f"The {current_year} current-year monitor has not been generated yet.",
        )
        st.info(message)
        st.caption(
            "When UDOT publishes the current-year layer, the scheduled pipeline "
            "will detect it automatically. No code or year edit is required."
        )
    else:
        data_through = phase3c.get("data_through_date", "—")
        comparison_years = phase3c.get("comparison_years", [])
        summary = phase3c.get("summary", {})
        hist_avg = phase3c.get("historical_same_period_average", {})

        current_total = int(summary.get("crashes", len(current_year_crashes)))
        current_severe = int(
            summary.get(
                "severe_crashes",
                current_year_crashes["severe_crash_flag"].sum(),
            )
        )
        current_fatal = int(
            summary.get(
                "fatal_crashes",
                current_year_crashes["fatal_crash_flag"].sum(),
            )
        )
        avg_severe = hist_avg.get("severe_crashes")
        avg_fatal = hist_avg.get("fatal_crashes")

        delta_severe = None
        if avg_severe not in (None, 0):
            delta_severe = (current_severe - float(avg_severe)) / float(avg_severe) * 100

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("YTD crashes", f"{current_total:,}")
        c2.metric(
            "YTD severe crashes",
            f"{current_severe:,}",
            delta=(f"{delta_severe:+.1f}% vs prior-period avg" if delta_severe is not None else None),
        )
        c3.metric("YTD fatal crashes", f"{current_fatal:,}")
        c4.metric("Data through", str(data_through))

        if comparison_years:
            st.caption(
                "Same-period baseline years: "
                + ", ".join(str(y) for y in comparison_years)
                + "."
            )

        st.warning(
            f"{current_year} data are **preliminary YTD observations**. Recent "
            "crashes can be delayed, corrected, or revised as UDOT completes "
            "entry and investigation. These records are not included in the "
            "historical O/E/FDR prioritization model until the year is complete."
        )

        st.subheader("Explore current-year crashes")
        cy_counties = sorted(
            current_year_crashes["county_name"].dropna().unique().tolist()
        )

        cf1, cf2 = st.columns(2)
        with cf1:
            cy_selected_counties = filtered_multiselect(
                "Counties",
                cy_counties,
                "cy_counties",
                help_text="Select one or more counties, or leave blank for statewide.",
                placeholder="All counties",
            )

        cy_route_scope = current_year_crashes
        if cy_selected_counties:
            cy_route_scope = cy_route_scope[
                cy_route_scope["county_name"].isin(cy_selected_counties)
            ]
        cy_routes = sorted(
            cy_route_scope["route_label"].dropna().unique().tolist()
        )

        if "cy_routes" in st.session_state:
            valid_cy_routes = [
                r for r in st.session_state["cy_routes"] if r in cy_routes
            ]
            if valid_cy_routes != st.session_state["cy_routes"]:
                st.session_state["cy_routes"] = valid_cy_routes

        with cf2:
            cy_selected_routes = filtered_multiselect(
                "Routes",
                cy_routes,
                "cy_routes",
                help_text="Route choices cascade from the selected county scope.",
                placeholder="All available routes",
            )

        cy_filtered = current_year_crashes.copy()
        if cy_selected_counties:
            cy_filtered = cy_filtered[
                cy_filtered["county_name"].isin(cy_selected_counties)
            ]
        if cy_selected_routes:
            cy_filtered = cy_filtered[
                cy_filtered["route_label"].isin(cy_selected_routes)
            ]

        if cy_filtered.empty:
            st.warning("No current-year crashes match those filters.")
        else:
            yf1, yf2, yf3 = st.columns(3)
            yf1.metric("Filtered crashes", f"{len(cy_filtered):,}")
            yf2.metric(
                "Filtered severe crashes",
                f"{int(cy_filtered['severe_crash_flag'].sum()):,}",
            )
            yf3.metric(
                "Filtered fatal crashes",
                f"{int(cy_filtered['fatal_crash_flag'].sum()):,}",
            )

            st.subheader(f"{current_year} YTD severe-crash map")
            cy_map = cy_filtered[
                cy_filtered["severe_crash_flag"] == 1
            ].rename(columns={"latitude": "lat", "longitude": "lon"})
            cy_map = cy_map.dropna(subset=["lat", "lon"]).copy()

            if cy_map.empty:
                st.info("No severe crashes with usable coordinates match the filters.")
            else:
                cy_fatal = cy_map[cy_map["fatal_crash_flag"] == 1]
                cy_serious = cy_map[cy_map["fatal_crash_flag"] != 1]
                cy_layers = []

                if not cy_serious.empty:
                    cy_layers.append(
                        pdk.Layer(
                            "ScatterplotLayer",
                            data=cy_serious,
                            get_position="[lon, lat]",
                            get_radius=500,
                            radius_min_pixels=3,
                            radius_max_pixels=8,
                            get_fill_color=MAP_SEVERE,
                            pickable=True,
                            auto_highlight=True,
                        )
                    )
                if not cy_fatal.empty:
                    cy_layers.append(
                        pdk.Layer(
                            "ScatterplotLayer",
                            data=cy_fatal,
                            get_position="[lon, lat]",
                            get_radius=700,
                            radius_min_pixels=4,
                            radius_max_pixels=10,
                            get_fill_color=MAP_FATAL,
                            get_line_color=[255, 255, 255, 235],
                            line_width_min_pixels=1,
                            stroked=True,
                            pickable=True,
                            auto_highlight=True,
                        )
                    )

                cy_deck = pdk.Deck(
                    map_style=(
                        "https://basemaps.cartocdn.com/"
                        "gl/positron-gl-style/style.json"
                    ),
                    initial_view_state=auto_view(cy_map),
                    layers=cy_layers,
                    tooltip={
                        "html": (
                            "<b>{county_name} County</b><br/>"
                            "Route: {route_label}<br/>"
                            "Severity: {severity}<br/>"
                            "Crash date: {crash_date}"
                        )
                    },
                )
                st.pydeck_chart(cy_deck, use_container_width=True)

        if not current_year_compare.empty:
            st.subheader("Same-period comparison")
            comparison_plot = current_year_compare.copy()
            comparison_plot["Period"] = comparison_plot["year"].astype(str)
            comparison_plot["Series"] = comparison_plot["is_current_year"].map(
                {1: f"{current_year} YTD", 0: "Prior same-period year"}
            )

            bars = (
                alt.Chart(comparison_plot)
                .mark_bar()
                .encode(
                    x=alt.X("Period:N", title="Year"),
                    y=alt.Y("severe_crashes:Q", title="Severe crashes through same cutoff"),
                    color=alt.Color(
                        "Series:N",
                        title=None,
                        scale=alt.Scale(
                            domain=["Prior same-period year", f"{current_year} YTD"],
                            range=[UTAH_GOLD, UTAH_NAVY],
                        ),
                    ),
                    tooltip=[
                        alt.Tooltip("year:O", title="Year"),
                        alt.Tooltip("crashes:Q", title="All crashes", format=",.0f"),
                        alt.Tooltip("severe_crashes:Q", title="Severe", format=",.0f"),
                        alt.Tooltip("fatal_crashes:Q", title="Fatal", format=",.0f"),
                    ],
                )
            )
            labels = (
                alt.Chart(comparison_plot)
                .mark_text(dy=-5, color=UTAH_NAVY)
                .encode(
                    x=alt.X("Period:N"),
                    y=alt.Y("severe_crashes:Q"),
                    text=alt.Text("severe_crashes:Q", format=",.0f"),
                )
            )
            st.altair_chart(bars + labels, use_container_width=True)

        if not current_year_monthly.empty:
            st.subheader("Monthly severe-crash pattern")
            monthly_long = current_year_monthly[
                ["month", "month_name", "current_severe_crashes", "historical_avg_severe_crashes"]
            ].melt(
                id_vars=["month", "month_name"],
                var_name="Series",
                value_name="Severe crashes",
            )
            monthly_long["Series"] = monthly_long["Series"].map(
                {
                    "current_severe_crashes": f"{current_year} YTD",
                    "historical_avg_severe_crashes": "Prior same-period average",
                }
            )
            line = (
                alt.Chart(monthly_long)
                .mark_line(point=True, strokeWidth=3)
                .encode(
                    x=alt.X("month_name:N", sort=list(current_year_monthly["month_name"]), title="Month"),
                    y=alt.Y("Severe crashes:Q"),
                    color=alt.Color(
                        "Series:N",
                        title=None,
                        scale=alt.Scale(
                            domain=[f"{current_year} YTD", "Prior same-period average"],
                            range=[UTAH_NAVY, UTAH_GOLD],
                        ),
                    ),
                    tooltip=[
                        alt.Tooltip("month_name:N", title="Month"),
                        alt.Tooltip("Series:N"),
                        alt.Tooltip("Severe crashes:Q", format=".1f"),
                    ],
                )
            )
            st.altair_chart(line, use_container_width=True)

        if not current_year_county.empty:
            st.subheader("County YTD context")
            county_view = current_year_county.copy()
            county_view = county_view.sort_values(
                "current_severe_crashes", ascending=False
            ).head(15)
            county_table = pd.DataFrame(
                {
                    "County": county_view["county_name"],
                    f"{current_year} YTD severe": county_view["current_severe_crashes"].astype(int),
                    "Prior same-period avg": county_view["historical_avg_severe_crashes"].round(1),
                    "Change vs avg": county_view["severe_vs_history_pct"].map(
                        lambda x: f"{x:+.1f}%" if pd.notna(x) else "—"
                    ),
                    f"{current_year} YTD fatal": county_view["current_fatal_crashes"].astype(int),
                }
            )
            st.dataframe(county_table, hide_index=True, use_container_width=True)

        st.caption(
            "Rollover rule: completed years automatically move into the historical "
            "analysis on January 1; the new calendar year becomes the YTD monitor. "
            "If UDOT has not yet published the new annual layer, the monitor waits "
            "and begins automatically when the layer appears."
        )

# ===================================================================
# TAB 3 — PRIORITY CORRIDORS
# ===================================================================
with tab_priority:
    st.header("Where is severe-crash burden disproportionately elevated?")
    st.write(
        "This view narrows the statewide data to corridors that survived "
        "exposure adjustment, uncertainty screening, and false-discovery-rate control."
    )

    tested = phase2c.get("summary", {}).get("corridors_tested", "—")
    supported = len(executive)
    match_rate = phase2b.get("spatial_match", {}).get("match_rate_pct")
    median_snap = phase2b.get("spatial_match", {}).get(
        "median_snap_distance_m"
    )

    p1, p2, p3, p4 = st.columns(4)
    p1.metric("Corridors tested", f"{tested}")
    p2.metric("Supported clusters", f"{supported:,}")
    p3.metric(
        "Spatial match rate",
        f"{match_rate:.1f}%" if match_rate is not None else "—",
    )
    p4.metric(
        "Median route snap",
        f"{median_snap:.2f} m" if median_snap is not None else "—",
    )

    executive["dominant_county"] = executive["dominant_county"].fillna(
        "Unknown"
    )
    executive["route_name"] = executive["route_name"].fillna(
        executive["route_num"].map(lambda x: f"Route {int(x)}")
    )

    pf1, pf2 = st.columns(2)

    with pf1:
        priority_counties = filtered_multiselect(
            "Counties",
            executive["dominant_county"].unique().tolist(),
            "priority_counties",
            help_text=(
                "Use Select all, choose one or more counties, or leave blank "
                "for all supported counties."
            ),
            placeholder="All counties",
        )

    priority_route_scope = executive
    if priority_counties:
        priority_route_scope = priority_route_scope[
            priority_route_scope["dominant_county"].isin(priority_counties)
        ]
    available_priority_routes = (
        priority_route_scope["route_name"].dropna().unique().tolist()
    )

    if "priority_routes" in st.session_state:
        valid_priority_routes = [
            r for r in st.session_state["priority_routes"]
            if r in available_priority_routes
        ]
        if valid_priority_routes != st.session_state["priority_routes"]:
            st.session_state["priority_routes"] = valid_priority_routes

    with pf2:
        priority_routes = filtered_multiselect(
            "Routes",
            available_priority_routes,
            "priority_routes",
            help_text=(
                "Route choices cascade from County. Use Select all, choose "
                "specific routes, or leave blank for all routes in the county scope."
            ),
            placeholder="All available routes",
        )

    priority_filtered = executive.copy()
    if priority_counties:
        priority_filtered = priority_filtered[
            priority_filtered["dominant_county"].isin(priority_counties)
        ]
    if priority_routes:
        priority_filtered = priority_filtered[
            priority_filtered["route_name"].isin(priority_routes)
        ]

    if priority_filtered.empty:
        st.warning("No supported priority corridors match those filters.")
    else:
        st.subheader("Executive priority shortlist")

        max_n = min(15, len(priority_filtered))
        if max_n <= 5:
            top_n = max_n
            st.caption(
                f"Showing all {top_n} supported corridor"
                f"{'' if top_n == 1 else 's'} in the current filter."
            )
        else:
            top_n = st.slider(
                "Number of priority corridors",
                min_value=5,
                max_value=max_n,
                value=min(10, max_n),
                key="priority_top_n",
            )

        priority_top = priority_filtered.sort_values(
            "executive_rank"
        ).head(top_n)

        table = pd.DataFrame(
            {
                "Rank": priority_top["executive_rank"].astype(int),
                "Corridor": priority_top["corridor_label"],
                "Severe": priority_top["severe_crashes"].astype(int),
                "Expected": priority_top["expected_severe"].round(1),
                "Above expected": priority_top["excess_severe"].round(1),
                "O/E": priority_top["oe_ratio"].round(2),
                "Fatal": priority_top["fatal_crashes"].astype(int),
            }
        )
        st.dataframe(table, hide_index=True, use_container_width=True)

        st.caption(
            "**Above expected** is the easiest executive measure: observed severe "
            "crashes minus the peer-expected severe crashes."
        )

        st.subheader("Excess severe-crash burden")
        burden = (
            priority_top[["corridor_label", "excess_severe"]]
            .rename(
                columns={
                    "corridor_label": "Corridor",
                    "excess_severe": "Above expected",
                }
            )
            .copy()
        )
        burden["Above expected"] = burden["Above expected"].round(1)
        labeled_bar_chart(
            burden,
            category="Corridor",
            value="Above expected",
            value_format=".1f",
            horizontal=True,
            bar_color=UTAH_RED,
        )

        st.subheader("Priority-corridor map")
        pri_map = priority_filtered[
            [
                "severe_center_lat",
                "severe_center_lon",
                "corridor_label",
                "dominant_county",
                "executive_rank",
                "severe_crashes",
                "expected_severe",
                "excess_severe",
            ]
        ].dropna().rename(
            columns={
                "severe_center_lat": "lat",
                "severe_center_lon": "lon",
                "corridor_label": "Corridor",
                "dominant_county": "County",
                "executive_rank": "Rank",
                "severe_crashes": "Severe",
                "expected_severe": "Expected",
                "excess_severe": "Above expected",
            }
        )

        if not pri_map.empty:
            pri_map["radius_m"] = (
                5000
                + pri_map["Above expected"].clip(lower=0)
                / max(float(pri_map["Above expected"].max()), 1.0)
                * 7000
            )

            layer = pdk.Layer(
                "ScatterplotLayer",
                data=pri_map,
                get_position="[lon, lat]",
                get_radius="radius_m",
                radius_min_pixels=7,
                radius_max_pixels=18,
                get_fill_color=MAP_PRIORITY,
                get_line_color=MAP_OUTLINE,
                line_width_min_pixels=1.5,
                stroked=True,
                pickable=True,
                auto_highlight=True,
            )

            deck = pdk.Deck(
                map_style=(
                    "https://basemaps.cartocdn.com/"
                    "gl/positron-gl-style/style.json"
                ),
                initial_view_state=auto_view(pri_map),
                layers=[layer],
                tooltip={
                    "html": (
                        "<b>{Corridor}</b><br/>"
                        "County: {County}<br/>"
                        "Rank: {Rank}<br/>"
                        "Severe: {Severe}<br/>"
                        "Expected: {Expected}<br/>"
                        "Above expected: {Above expected}"
                    )
                },
            )

            st.pydeck_chart(deck, use_container_width=True)

        st.info(
            "This map answers **where severe-crash burden appears disproportionately "
            "elevated after traffic exposure adjustment**. It intentionally does not "
            "show every Utah crash or every county."
        )

# ===================================================================
# TAB 4 — WHY THIS CORRIDOR
# ===================================================================
with tab_why:
    st.header("Why does a priority corridor stand out?")
    st.write(
        "This section compares crash characteristics inside one supported corridor "
        "with the statewide severe-crash baseline."
    )

    # ---------------------------------------------------------------
    # Simplified drill-down UX:
    # Primary task = find/select a corridor.
    # County + Route remain available as optional advanced filters.
    # ---------------------------------------------------------------
    why_scope = drivers.copy()

    with st.expander("Optional filters — county and route", expanded=False):
        why_county_options = sorted(
            why_scope["dominant_county"].dropna().unique().tolist()
        )

        wf1, wf2 = st.columns(2)

        with wf1:
            why_counties = st.multiselect(
                "County",
                options=why_county_options,
                default=[],
                key="why_counties",
                placeholder="All counties",
                help="Select one or multiple counties. Leave blank for all counties.",
            )

        if why_counties:
            why_scope = why_scope[
                why_scope["dominant_county"].isin(why_counties)
            ]

        why_route_options = sorted(
            why_scope["route_name"].dropna().unique().tolist()
        )

        # Clear route selections that are no longer valid after county changes.
        if "why_routes" in st.session_state:
            valid_why_routes = [
                r for r in st.session_state["why_routes"]
                if r in why_route_options
            ]
            if valid_why_routes != st.session_state["why_routes"]:
                st.session_state["why_routes"] = valid_why_routes

        with wf2:
            why_routes = st.multiselect(
                "Route",
                options=why_route_options,
                default=[],
                key="why_routes",
                placeholder="All available routes",
                help="Route choices update from the selected county/county set.",
            )

        if why_routes:
            why_scope = why_scope[
                why_scope["route_name"].isin(why_routes)
            ]

    st.subheader("Find a priority corridor")

    corridor_search = st.text_input(
        "Search",
        value="",
        key="why_corridor_search",
        placeholder="Try: SR 68, US 89, Salt Lake, Weber, MP 45",
        label_visibility="collapsed",
        help="Search by route, county, or milepoint.",
    )

    corridor_options = why_scope["corridor_label"].tolist()

    if corridor_search.strip():
        search_term = corridor_search.strip().lower()
        filtered_corridor_options = [
            label
            for label in corridor_options
            if search_term in str(label).lower()
        ]
    else:
        filtered_corridor_options = corridor_options

    if not filtered_corridor_options:
        st.warning(
            "No priority corridors match that search/filter combination."
        )
        st.stop()

    # Prevent stale selected corridor from conflicting with filtered options.
    if (
        "why_corridor" in st.session_state
        and st.session_state["why_corridor"] not in filtered_corridor_options
    ):
        del st.session_state["why_corridor"]

    selected_corridor = st.selectbox(
        "Priority corridor",
        options=filtered_corridor_options,
        key="why_corridor",
        help="Choose the corridor you want to investigate.",
    )

    selected_row = drivers.loc[
        drivers["corridor_label"] == selected_corridor
    ].iloc[0]

    st.caption(
        f"Showing 1 of {len(filtered_corridor_options)} matching priority corridor"
        f"{'' if len(filtered_corridor_options) == 1 else 's'}."
    )

    st.markdown(
        f"""
        <div style="
            border:1px solid {UTAH_BORDER};
            border-left:5px solid {UTAH_GOLD};
            border-radius:10px;
            padding:12px 14px;
            margin:8px 0 18px 0;
            background:{UTAH_LIGHT};
        ">
            <div style="font-size:0.82rem;color:{UTAH_SLATE};font-weight:600;">
                SELECTED CORRIDOR
            </div>
            <div style="font-size:1.15rem;color:{UTAH_NAVY};font-weight:700;">
                {selected_corridor}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    row = selected_row

    w1, w2, w3, w4 = st.columns(4)
    w1.metric("Severe crashes", f"{int(row['severe_crashes']):,}")
    w2.metric("Expected severe", f"{row['expected_severe']:.1f}")
    w3.metric("Above expected", f"{row['excess_severe']:.1f}")
    w4.metric("Observed / expected", f"{row['oe_ratio']:.2f}×")

    characteristics = [
        ("Speed-related", "speed_related"),
        ("DUI", "dui"),
        ("Distracted driving", "distracted_driving"),
        ("Roadway departure", "roadway_departure"),
    ]

    comparison_rows = []
    for label, prefix in characteristics:
        comparison_rows.append(
            {
                "Characteristic": label,
                "Selected corridor": row[f"{prefix}_pct"],
                "Statewide severe-crash baseline": row[
                    f"{prefix}_statewide_pct"
                ],
                "Difference": row[f"{prefix}_pp_diff"],
            }
        )

    comp = pd.DataFrame(comparison_rows)

    st.subheader("Crash-characteristic comparison")

    chart_long = comp[
        [
            "Characteristic",
            "Selected corridor",
            "Statewide severe-crash baseline",
        ]
    ].melt(
        id_vars="Characteristic",
        var_name="Series",
        value_name="Percent",
    )
    chart_long["Percent"] = chart_long["Percent"].round(1)

    bars = (
        alt.Chart(chart_long)
        .mark_bar()
        .encode(
            x=alt.X("Characteristic:N", title=None),
            y=alt.Y("Percent:Q", title="Percent of severe crashes"),
            xOffset="Series:N",
            color=alt.Color(
                "Series:N",
                title=None,
                scale=alt.Scale(
                    domain=[
                        "Selected corridor",
                        "Statewide severe-crash baseline",
                    ],
                    range=[UTAH_NAVY, UTAH_GOLD],
                ),
            ),
            tooltip=[
                alt.Tooltip("Characteristic:N"),
                alt.Tooltip("Series:N"),
                alt.Tooltip("Percent:Q", format=".1f", title="Percent"),
            ],
        )
    )

    labels = (
        alt.Chart(chart_long)
        .mark_text(dy=-5, color=UTAH_NAVY)
        .encode(
            x=alt.X("Characteristic:N"),
            y=alt.Y("Percent:Q"),
            xOffset="Series:N",
            detail="Series:N",
            text=alt.Text("Percent:Q", format=".1f"),
        )
    )

    st.altair_chart(bars + labels, use_container_width=True)

    difference_table = comp.copy()
    difference_table["Selected corridor"] = (
        difference_table["Selected corridor"].round(1).astype(str) + "%"
    )
    difference_table["Statewide severe-crash baseline"] = (
        difference_table["Statewide severe-crash baseline"].round(1).astype(str)
        + "%"
    )
    difference_table["Difference"] = (
        difference_table["Difference"].round(1).map(
            lambda x: f"{x:+.1f} pp"
        )
    )

    st.dataframe(
        difference_table,
        use_container_width=True,
        hide_index=True,
    )

    readable = {
        "speed_related": "speed-related crashes",
        "dui": "DUI crashes",
        "distracted_driving": "distracted-driving crashes",
        "roadway_departure": "roadway-departure crashes",
    }

    top1 = readable.get(row["top_driver_1"], row["top_driver_1"])
    top1_diff = row["top_driver_1_pp_diff"]

    top2 = readable.get(row["top_driver_2"], row["top_driver_2"])
    top2_diff = row["top_driver_2_pp_diff"]

    st.subheader("What stands out?")

    if top1_diff > 0:
        st.success(
            f"Among the characteristics tested, **{top1}** is the strongest "
            f"over-represented factor in this corridor at **{top1_diff:+.1f} "
            f"percentage points** versus the statewide severe-crash baseline."
        )
    else:
        st.info(
            "None of the four tested crash characteristics is more common than "
            "the statewide severe-crash baseline in this corridor."
        )

    if top2_diff > 0:
        st.write(
            f"The second-largest difference is **{top2}** at "
            f"**{top2_diff:+.1f} percentage points**."
        )

    st.warning(
        "These differences are **descriptive associations**, not causal effects. "
        "They help identify questions for additional engineering or operational "
        "investigation."
    )

# ===================================================================
# TAB 5 — DATA REFRESH
# ===================================================================
with tab_refresh:
    st.header("Data refresh and pipeline status")
    st.write(
        "This view documents the automated publishing cycle behind the dashboard: "
        "when the analytics were last refreshed, when the next scheduled refresh is "
        "expected, and how the incremental ingestion layer handled the latest run."
    )

    last_refresh = _latest_successful_refresh()
    next_refresh = _next_scheduled_refresh()
    current_mode = _refresh_mode_label()
    historical_cache = _historical_cache_label()
    network_rows = incremental_current.get("network_rows_fetched")
    network_note = (
        f"{int(network_rows):,} source rows fetched"
        if isinstance(network_rows, (int, float))
        else "Source-row count unavailable"
    )

    st.markdown(
        f"""
        <div style="
            margin:0.5rem 0 1.15rem 0;
            padding:16px;
            border:1px solid {UTAH_BORDER};
            border-top:4px solid {UTAH_GOLD};
            border-radius:12px;
            background:{UTAH_LIGHT};
        ">
          <div style="font-size:0.88rem;font-weight:800;color:{UTAH_NAVY};letter-spacing:0.04em;margin-bottom:12px;">
            DATA FRESHNESS
          </div>
          <div style="display:grid;grid-template-columns:repeat(2,minmax(220px,1fr));gap:12px;">
            <div style="background:{UTAH_WHITE};border:1px solid {UTAH_BORDER};border-radius:9px;padding:13px 14px;">
              <div style="font-size:0.75rem;color:{UTAH_SLATE};font-weight:700;">LAST SUCCESSFUL REFRESH</div>
              <div style="font-size:1.05rem;color:{UTAH_NAVY};font-weight:800;margin-top:4px;">{_format_utah_datetime(last_refresh)}</div>
            </div>
            <div style="background:{UTAH_WHITE};border:1px solid {UTAH_BORDER};border-radius:9px;padding:13px 14px;">
              <div style="font-size:0.75rem;color:{UTAH_SLATE};font-weight:700;">NEXT SCHEDULED REFRESH</div>
              <div style="font-size:1.05rem;color:{UTAH_NAVY};font-weight:800;margin-top:4px;">{_format_utah_datetime(next_refresh)}</div>
            </div>
            <div style="background:{UTAH_PALE_GOLD};border:1px solid {UTAH_GOLD};border-radius:9px;padding:13px 14px;">
              <div style="font-size:0.75rem;color:{UTAH_SLATE};font-weight:700;">CURRENT-YEAR REFRESH MODE</div>
              <div style="font-size:1.05rem;color:{UTAH_NAVY};font-weight:800;margin-top:4px;">{current_mode}</div>
              <div style="font-size:0.75rem;color:{UTAH_SLATE};margin-top:3px;">{network_note}</div>
            </div>
            <div style="background:{UTAH_PALE_BLUE};border:1px solid {UTAH_BORDER};border-radius:9px;padding:13px 14px;">
              <div style="font-size:0.75rem;color:{UTAH_SLATE};font-weight:700;">HISTORICAL CACHE STATUS</div>
              <div style="font-size:1.05rem;color:{UTAH_NAVY};font-weight:800;margin-top:4px;">{historical_cache}</div>
              <div style="font-size:0.75rem;color:{UTAH_SLATE};margin-top:3px;">Completed years are reused until a reconciliation is required.</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.subheader("How the refresh works")
    st.markdown(
        """
- **Scheduled cloud pipeline:** GitHub Actions runs the ingestion and analytics workflow on its configured schedule.
- **Current year:** the pipeline uses incremental ingestion with a rolling reconciliation window and upsert logic.
- **Completed historical years:** cached data is reused unless reconciliation or a detected source change requires a refresh.
- **Annual rollover:** the completed year receives a final reconciliation before joining the historical model, and the new calendar year becomes the YTD monitor.
- **Safe fallback:** if incremental state or cache is unavailable, the pipeline can rebuild from the source rather than publish a partial dataset.
        """
    )

# ===================================================================
# TAB 6 — METHODOLOGY
# ===================================================================
with tab_method:
    st.header("Methodology and governance")

    st.markdown(
        f"""
        <div style="
            display:flex;
            gap:10px;
            flex-wrap:wrap;
            margin:0.25rem 0 1.25rem 0;
        ">
          <span style="background:{UTAH_NAVY};color:white;padding:6px 10px;border-radius:999px;">Primary / priority</span>
          <span style="background:{UTAH_RED};color:white;padding:6px 10px;border-radius:999px;">Fatal / excess burden</span>
          <span style="background:{UTAH_GOLD};color:{UTAH_NAVY};padding:6px 10px;border-radius:999px;">Highlight / comparison</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.info(
        "Accessibility: users can switch palettes from the sidebar. "
        "The dashboard does not rely on color alone—numeric labels, legends, "
        "marker size, outlines, tables, and descriptive text carry the same meaning."
    )

    st.markdown(
        """
### Analytical workflow

**1. Ingest**
- Public UDOT crash data
- UDOT AADT / traffic-exposure data
- Official UDOT route geometry

**2. Validate**
- Missing IDs and severity fields
- Duplicate crash IDs
- Coordinate plausibility
- AADT completeness
- Cross-source route matching

**3. Spatially reference**
- Match crash coordinates to official route geometry
- Derive route milepoints
- Validate spatial match quality

**4. Normalize exposure**
- Vehicle miles traveled (VMT)
- Severe-crash rate per 100M VMT

**5. Screen corridors**
- 5-mile analytical bins
- Comparable traffic-exposure peer groups
- Observed vs expected severe crashes

**6. Quantify uncertainty**
- Exact Poisson O/E confidence intervals
- Benjamini–Hochberg false-discovery-rate correction

**7. Consolidate**
- Merge adjacent supported bins into executive corridor clusters

**8. Diagnose**
- Compare corridor crash characteristics with statewide severe-crash shares
"""
    )

    st.subheader("Automatic year rollover")
    st.markdown(
        f"""
- **Historical model:** completed calendar years only.
- **Current-year monitor:** {monitor_year} YTD/preliminary data.
- On January 1, the completed year becomes eligible for historical modeling automatically.
- The new calendar year becomes the YTD monitor automatically.
- If the new UDOT annual layer is not published yet, the monitor waits without failing the historical pipeline.
"""
    )

    st.subheader("Important limitations")
    st.markdown(
        """
- This is an independent portfolio proof-of-concept, not an official UDOT analysis.
- The analysis is observational and does not establish causality.
- Five-mile bins and merged corridor clusters are analytical constructs, not official project boundaries.
- Peer-expected counts are estimated from the same dataset and treated as fixed in the screening confidence intervals.
- Crash-characteristic comparisons identify descriptive over-representation only.
- A production safety study should use UDOT-approved engineering, roadway-design, exposure, and crash-modeling methods.
"""
    )

    st.subheader("Data-quality evidence")

    q1, q2 = st.columns(2)

    with q1:
        if phase2b:
            sm = phase2b.get("spatial_match", {})
            st.metric(
                "Spatial route match",
                f"{sm.get('match_rate_pct', 0):.2f}%",
            )
            st.metric(
                "Median snap distance",
                f"{sm.get('median_snap_distance_m', 0):.2f} m",
            )

    with q2:
        summary = phase3b.get("summary", {})
        if summary:
            st.metric(
                "Statewide severe crashes",
                f"{summary.get('severe_crashes', 0):,}",
            )
            st.metric(
                "Counties represented",
                f"{summary.get('counties_represented', 0):,}",
            )

st.divider()
st.caption(
    "Purpose: demonstrate transportation analytics, reproducible pipelines, "
    "spatial integration, statistical screening, data governance, and executive "
    "decision-support using public data."
)
