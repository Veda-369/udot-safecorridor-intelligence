from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
BRONZE_DIR = DATA_DIR / "bronze"
SILVER_DIR = DATA_DIR / "silver"
GOLD_DIR = DATA_DIR / "gold"
REPORTS_DIR = ROOT / "reports"
WAREHOUSE_DIR = ROOT / "warehouse"
SQL_DIR = ROOT / "sql"

# Legacy MapServer retained because it contains the 2018 layer used by the
# historical model. The newer public FeatureServer is refreshed nightly and
# contains the current-year layer.
LEGACY_CRASH_SERVICE_URL = (
    "https://central.udot.utah.gov/central/rest/services/"
    "TrafficAndSafety/Crash_Locations/MapServer"
)

CURRENT_CRASH_SERVICE_URL = (
    "https://services.arcgis.com/pA2nEVnB6tquxgOW/ArcGIS/rest/services/"
    "Utah_Crash_Locations/FeatureServer"
)

# Backward-compatible name used by earlier code.
CRASH_SERVICE_URL = LEGACY_CRASH_SERVICE_URL

AADT_LAYER_URL = (
    "https://services.arcgis.com/pA2nEVnB6tquxgOW/ArcGIS/rest/services/"
    "AADT2024_Unrounded/FeatureServer/3"
)

# Dynamic year rollover:
# - completed years feed the historical prioritization model
# - the calendar current year is handled separately as YTD/preliminary data
CALENDAR_CURRENT_YEAR = int(
    os.getenv("UDOT_CURRENT_YEAR", str(datetime.now(timezone.utc).year))
)
CRASH_MIN_YEAR = int(os.getenv("UDOT_CRASH_MIN_YEAR", "2018"))
CRASH_MAX_YEAR = int(
    os.getenv("UDOT_CRASH_MAX_YEAR", str(CALENDAR_CURRENT_YEAR - 1))
)
CURRENT_MONITOR_YEAR = int(
    os.getenv("UDOT_CURRENT_MONITOR_YEAR", str(CALENDAR_CURRENT_YEAR))
)
CURRENT_MONITOR_COMPARE_YEARS = int(
    os.getenv("UDOT_CURRENT_MONITOR_COMPARE_YEARS", "5")
)
ARCGIS_PAGE_SIZE = int(os.getenv("ARCGIS_PAGE_SIZE", "2000"))


@dataclass(frozen=True)
class Paths:
    bronze_crashes: Path = BRONZE_DIR / "crashes_raw.parquet"
    bronze_aadt: Path = BRONZE_DIR / "aadt_raw.parquet"
    silver_crashes: Path = SILVER_DIR / "crashes_clean.parquet"
    silver_aadt: Path = SILVER_DIR / "aadt_analysis.parquet"
    gold_segment_risk: Path = GOLD_DIR / "segment_risk.parquet"
    gold_route_risk: Path = GOLD_DIR / "route_risk.parquet"
    gold_crash_points: Path = GOLD_DIR / "severe_crash_points.parquet"
    gold_quality: Path = GOLD_DIR / "quality_summary.parquet"
    gold_current_year_crashes: Path = GOLD_DIR / "current_year_crashes.parquet"
    gold_current_year_county: Path = GOLD_DIR / "current_year_county_summary.parquet"
    gold_current_year_route: Path = GOLD_DIR / "current_year_route_summary.parquet"
    gold_current_year_compare: Path = GOLD_DIR / "current_year_ytd_comparison.parquet"
    gold_current_year_monthly: Path = GOLD_DIR / "current_year_monthly_trend.parquet"
    duckdb: Path = WAREHOUSE_DIR / "udot_safecorridor.duckdb"
    quality_json: Path = REPORTS_DIR / "quality_report.json"
    pipeline_json: Path = REPORTS_DIR / "pipeline_run.json"
    current_year_json: Path = REPORTS_DIR / "phase3c_current_year_monitor.json"


PATHS = Paths()


def ensure_directories() -> None:
    for path in (BRONZE_DIR, SILVER_DIR, GOLD_DIR, REPORTS_DIR, WAREHOUSE_DIR):
        path.mkdir(parents=True, exist_ok=True)
