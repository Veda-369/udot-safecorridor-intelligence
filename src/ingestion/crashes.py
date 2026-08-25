from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import pandas as pd

from src.config import ARCGIS_PAGE_SIZE, CRASH_MAX_YEAR, CRASH_MIN_YEAR, CRASH_SERVICE_URL
from src.ingestion.arcgis import query_all_features, service_metadata

LOGGER = logging.getLogger(__name__)

CRASH_FIELDS = [
    "OBJECTID",
    "CRASH_ID",
    "CRASH_DATETIME",
    "COUNTY_NAME",
    "REGION_NAME",
    "MAIN_ROAD_NAME",
    "ROUTE",
    "START_ACCUM",
    "ROUTE_DIRECTION",
    "ROADWAY_TYPE_CD",
    "LOCATION_DESC",
    "CRASH_SEVERITY_DESC",
    "LIGHT_CONDITION_DESC",
    "WEATHER_CONDITION_DESC",
    "MANNER_COLLISION_DESC",
    "ROADWAY_SURF_CONDITION_DESC",
    "ROADWAY_JUNCT_FEATURE_DESC",
    "ROAD_JURISDICTION_DESC",
    "WORK_ZONE_RELATED_YNU",
    "NUMBER_VEHICLES_INVOLVED",
    "NUMBER_FATALITIES",
    "NUMBER_FOUR_INJURIES",
    "PEDESTRIAN_INVOLVED",
    "BICYCLIST_INVOLVED",
    "MOTORCYCLE_INVOLVED",
    "DUI",
    "AGGRESSIVE_DRIVING",
    "DISTRACTED_DRIVING",
    "DROWSY_DRIVING",
    "SPEED_RELATED",
    "ROADWAY_DEPARTURE",
    "OVERTURN_ROLLOVER",
    "COMMERCIAL_MOTOR_VEH_INVOLVED",
    "TEENAGE_DRIVER_INVOLVED",
    "OLDER_DRIVER_INVOLVED",
    "SINGLE_VEHICLE",
    "HIT_AND_RUN",
    "DIVIDED_HIGHWAY",
    "FUNCTIONAL_CLASS",
    "CURRENT_AS_OF_DATE",
]

YEAR_PATTERN = re.compile(r"Crash Locations\s+(\d{4})", re.IGNORECASE)


def discover_crash_layers() -> list[tuple[int, int]]:
    metadata = service_metadata(CRASH_SERVICE_URL)
    discovered: list[tuple[int, int]] = []
    for layer in metadata.get("layers", []):
        name = str(layer.get("name", ""))
        match = YEAR_PATTERN.fullmatch(name.strip())
        if not match:
            continue
        year = int(match.group(1))
        if CRASH_MIN_YEAR <= year <= CRASH_MAX_YEAR:
            discovered.append((year, int(layer["id"])))
    return sorted(discovered)


def _features_to_frame(features: list[dict], source_year: int) -> pd.DataFrame:
    rows: list[dict] = []
    for feature in features:
        row = dict(feature.get("attributes") or {})
        geometry = feature.get("geometry") or {}
        # outSR=4326 makes x=longitude and y=latitude for point layers.
        row["LONGITUDE"] = geometry.get("x")
        row["LATITUDE"] = geometry.get("y")
        row["SOURCE_YEAR"] = source_year
        rows.append(row)
    return pd.DataFrame(rows)


def extract_crashes() -> pd.DataFrame:
    layers = discover_crash_layers()
    if not layers:
        raise RuntimeError(
            f"No crash layers discovered for {CRASH_MIN_YEAR}-{CRASH_MAX_YEAR}. "
            "Inspect the UDOT service metadata before proceeding."
        )

    frames: list[pd.DataFrame] = []
    for year, layer_id in layers:
        LOGGER.info("Extracting UDOT crash layer %s (id=%s)", year, layer_id)
        features = query_all_features(
            f"{CRASH_SERVICE_URL}/{layer_id}",
            out_fields=CRASH_FIELDS,
            return_geometry=True,
            out_sr=4326,
            page_size=ARCGIS_PAGE_SIZE,
        )
        frames.append(_features_to_frame(features, year))

    result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    result["EXTRACTED_AT_UTC"] = datetime.now(timezone.utc).isoformat()
    return result
