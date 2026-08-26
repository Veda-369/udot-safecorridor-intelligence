from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

from src.config import (
    ARCGIS_PAGE_SIZE,
    CRASH_MAX_YEAR,
    CRASH_MIN_YEAR,
    CURRENT_CRASH_SERVICE_URL,
    LEGACY_CRASH_SERVICE_URL,
)
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

YEAR_PATTERN = re.compile(
    r"(?:Crash Locations\s+(\d{4})|(\d{4})\s+Crash Locations)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CrashLayer:
    year: int
    layer_id: int
    service_url: str
    source: str


# New FeatureServer field names are mostly lower-case and include a few renamed
# route/mileage fields. Normalize both services to the historical canonical
# schema so downstream SQL does not need service-specific logic.
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "OBJECTID": ("OBJECTID",),
    "CRASH_ID": ("CRASH_ID",),
    "CRASH_DATETIME": ("CRASH_DATETIME",),
    "COUNTY_NAME": ("COUNTY_NAME",),
    "REGION_NAME": ("REGION_NAME",),
    "MAIN_ROAD_NAME": ("MAIN_ROAD_NAME",),
    "ROUTE": ("ROUTE", "ROUTE_ID"),
    "START_ACCUM": ("START_ACCUM", "BEG_MILEAGE"),
    "ROUTE_DIRECTION": ("ROUTE_DIRECTION", "ROUTE_DIR_ID"),
    "ROADWAY_TYPE_CD": ("ROADWAY_TYPE_CD",),
    "LOCATION_DESC": ("LOCATION_DESC",),
    "CRASH_SEVERITY_DESC": ("CRASH_SEVERITY_DESC",),
    "LIGHT_CONDITION_DESC": ("LIGHT_CONDITION_DESC",),
    "WEATHER_CONDITION_DESC": ("WEATHER_CONDITION_DESC",),
    "MANNER_COLLISION_DESC": ("MANNER_COLLISION_DESC",),
    "ROADWAY_SURF_CONDITION_DESC": ("ROADWAY_SURF_CONDITION_DESC",),
    "ROADWAY_JUNCT_FEATURE_DESC": ("ROADWAY_JUNCT_FEATURE_DESC",),
    "ROAD_JURISDICTION_DESC": ("ROAD_JURISDICTION_DESC",),
    "WORK_ZONE_RELATED_YNU": ("WORK_ZONE_RELATED_YNU",),
    "NUMBER_VEHICLES_INVOLVED": (
        "NUMBER_VEHICLES_INVOLVED",
        "NUMBER_VEHICLES_INVOLVED",
    ),
    "NUMBER_FATALITIES": ("NUMBER_FATALITIES",),
    "NUMBER_FOUR_INJURIES": ("NUMBER_FOUR_INJURIES",),
    "PEDESTRIAN_INVOLVED": ("PEDESTRIAN_INVOLVED",),
    "BICYCLIST_INVOLVED": ("BICYCLIST_INVOLVED",),
    "MOTORCYCLE_INVOLVED": ("MOTORCYCLE_INVOLVED",),
    "DUI": ("DUI",),
    "AGGRESSIVE_DRIVING": ("AGGRESSIVE_DRIVING",),
    "DISTRACTED_DRIVING": ("DISTRACTED_DRIVING",),
    "DROWSY_DRIVING": ("DROWSY_DRIVING",),
    "SPEED_RELATED": ("SPEED_RELATED",),
    "ROADWAY_DEPARTURE": ("ROADWAY_DEPARTURE",),
    "OVERTURN_ROLLOVER": ("OVERTURN_ROLLOVER",),
    "COMMERCIAL_MOTOR_VEH_INVOLVED": ("COMMERCIAL_MOTOR_VEH_INVOLVED",),
    "TEENAGE_DRIVER_INVOLVED": ("TEENAGE_DRIVER_INVOLVED",),
    "OLDER_DRIVER_INVOLVED": ("OLDER_DRIVER_INVOLVED",),
    "SINGLE_VEHICLE": ("SINGLE_VEHICLE",),
    "HIT_AND_RUN": ("HIT_AND_RUN",),
    "DIVIDED_HIGHWAY": ("DIVIDED_HIGHWAY",),
    "FUNCTIONAL_CLASS": ("FUNCTIONAL_CLASS",),
    "CURRENT_AS_OF_DATE": ("CURRENT_AS_OF_DATE",),
}


def _discover_service_layers(
    service_url: str,
    *,
    source: str,
    min_year: int,
    max_year: int,
) -> dict[int, CrashLayer]:
    metadata = service_metadata(service_url)
    found: dict[int, CrashLayer] = {}
    for layer in metadata.get("layers", []):
        name = str(layer.get("name", ""))
        match = YEAR_PATTERN.fullmatch(name.strip())
        if not match:
            continue
        year = int(match.group(1) or match.group(2))
        if min_year <= year <= max_year:
            found[year] = CrashLayer(
                year=year,
                layer_id=int(layer["id"]),
                service_url=service_url,
                source=source,
            )
    return found


def discover_crash_layers(
    min_year: int | None = None,
    max_year: int | None = None,
    *,
    prefer_current_service: bool = False,
) -> list[CrashLayer]:
    """Discover annual crash layers across both public UDOT services.

    Historical runs prefer the legacy service when the same year exists there,
    preserving continuity with the validated 2018-2025 analysis. Missing years
    are filled from the nightly FeatureServer. Current-year monitoring reverses
    the priority and prefers the nightly FeatureServer.
    """
    min_year = CRASH_MIN_YEAR if min_year is None else int(min_year)
    max_year = CRASH_MAX_YEAR if max_year is None else int(max_year)

    legacy = _discover_service_layers(
        LEGACY_CRASH_SERVICE_URL,
        source="legacy_mapserver",
        min_year=min_year,
        max_year=max_year,
    )
    current = _discover_service_layers(
        CURRENT_CRASH_SERVICE_URL,
        source="nightly_featureserver",
        min_year=min_year,
        max_year=max_year,
    )

    selected: dict[int, CrashLayer] = {}
    years = range(min_year, max_year + 1)
    for year in years:
        if prefer_current_service:
            layer = current.get(year) or legacy.get(year)
        else:
            layer = legacy.get(year) or current.get(year)
        if layer is not None:
            selected[year] = layer

    return [selected[y] for y in sorted(selected)]


def _canonical_attributes(attributes: dict) -> dict:
    upper = {str(k).upper(): v for k, v in attributes.items()}
    result: dict[str, object] = {}
    for canonical in CRASH_FIELDS:
        aliases = FIELD_ALIASES.get(canonical, (canonical,))
        value = None
        for alias in aliases:
            if alias.upper() in upper:
                value = upper[alias.upper()]
                break
        result[canonical] = value
    return result


def _features_to_frame(
    features: list[dict],
    source_year: int,
    source_name: str,
) -> pd.DataFrame:
    rows: list[dict] = []
    for feature in features:
        row = _canonical_attributes(feature.get("attributes") or {})
        geometry = feature.get("geometry") or {}
        # outSR=4326 makes x=longitude and y=latitude for point layers.
        row["LONGITUDE"] = geometry.get("x")
        row["LATITUDE"] = geometry.get("y")
        row["SOURCE_YEAR"] = source_year
        row["SOURCE_SERVICE"] = source_name
        rows.append(row)
    return pd.DataFrame(rows)


def extract_crashes(
    min_year: int | None = None,
    max_year: int | None = None,
    *,
    prefer_current_service: bool = False,
    allow_empty: bool = False,
) -> pd.DataFrame:
    min_year = CRASH_MIN_YEAR if min_year is None else int(min_year)
    max_year = CRASH_MAX_YEAR if max_year is None else int(max_year)

    layers = discover_crash_layers(
        min_year,
        max_year,
        prefer_current_service=prefer_current_service,
    )
    if not layers:
        if allow_empty:
            return pd.DataFrame(columns=CRASH_FIELDS + [
                "LONGITUDE",
                "LATITUDE",
                "SOURCE_YEAR",
                "SOURCE_SERVICE",
                "EXTRACTED_AT_UTC",
            ])
        raise RuntimeError(
            f"No crash layers discovered for {min_year}-{max_year}. "
            "Inspect the UDOT service metadata before proceeding."
        )

    discovered_years = {layer.year for layer in layers}
    missing_years = [
        year for year in range(min_year, max_year + 1)
        if year not in discovered_years
    ]
    if missing_years:
        LOGGER.warning("Crash layers not available for years: %s", missing_years)

    frames: list[pd.DataFrame] = []
    for layer in layers:
        LOGGER.info(
            "Extracting UDOT crash layer %s (id=%s, source=%s)",
            layer.year,
            layer.layer_id,
            layer.source,
        )
        # Legacy service accepts the validated canonical field list. The newer
        # FeatureServer has a few renamed fields, so request all fields and then
        # normalize them to the canonical schema.
        out_fields: list[str] | str = (
            CRASH_FIELDS if layer.source == "legacy_mapserver" else "*"
        )
        features = query_all_features(
            f"{layer.service_url}/{layer.layer_id}",
            out_fields=out_fields,
            return_geometry=True,
            out_sr=4326,
            page_size=ARCGIS_PAGE_SIZE,
        )
        frames.append(_features_to_frame(features, layer.year, layer.source))

    result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    result["EXTRACTED_AT_UTC"] = datetime.now(timezone.utc).isoformat()
    return result
