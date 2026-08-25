from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
BRONZE_DIR = DATA_DIR / "bronze"
SILVER_DIR = DATA_DIR / "silver"
GOLD_DIR = DATA_DIR / "gold"
REPORTS_DIR = ROOT / "reports"
WAREHOUSE_DIR = ROOT / "warehouse"
SQL_DIR = ROOT / "sql"

CRASH_SERVICE_URL = (
    "https://central.udot.utah.gov/central/rest/services/"
    "TrafficAndSafety/Crash_Locations/MapServer"
)

AADT_LAYER_URL = (
    "https://services.arcgis.com/pA2nEVnB6tquxgOW/ArcGIS/rest/services/"
    "AADT2024_Unrounded/FeatureServer/3"
)

CRASH_MIN_YEAR = int(os.getenv("UDOT_CRASH_MIN_YEAR", "2018"))
CRASH_MAX_YEAR = int(os.getenv("UDOT_CRASH_MAX_YEAR", str(datetime.now().year)))
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
    duckdb: Path = WAREHOUSE_DIR / "udot_safecorridor.duckdb"
    quality_json: Path = REPORTS_DIR / "quality_report.json"
    pipeline_json: Path = REPORTS_DIR / "pipeline_run.json"


PATHS = Paths()


def ensure_directories() -> None:
    for path in (BRONZE_DIR, SILVER_DIR, GOLD_DIR, REPORTS_DIR, WAREHOUSE_DIR):
        path.mkdir(parents=True, exist_ok=True)
