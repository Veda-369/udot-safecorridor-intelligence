from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Iterable

import pandas as pd

from src.config import AADT_LAYER_URL, ARCGIS_PAGE_SIZE
from src.ingestion.arcgis import layer_metadata, query_all_features

LOGGER = logging.getLogger(__name__)

BASE_FIELDS = [
    "OBJECTID",
    "Station",
    "RouteID",
    "BeginPoint",
    "EndPoint",
    "SectionLength",
    "DESC_",
]

AADT_FIELD_PATTERN = re.compile(r"^AADT(\d{4})$", re.IGNORECASE)


def discover_aadt_year_fields(columns: Iterable[str]) -> dict[int, str]:
    """Return {year: actual_column_name} for AADTYYYY columns."""
    result: dict[int, str] = {}
    for column in columns:
        match = AADT_FIELD_PATTERN.fullmatch(str(column).strip())
        if match:
            result[int(match.group(1))] = str(column)
    return dict(sorted(result.items()))


def extract_aadt() -> pd.DataFrame:
    metadata = layer_metadata(AADT_LAYER_URL)
    available_fields = {field["name"] for field in metadata.get("fields", [])}
    year_fields = discover_aadt_year_fields(available_fields)
    aadt_fields = [year_fields[year] for year in sorted(year_fields)]

    fields = [field for field in BASE_FIELDS if field in available_fields] + aadt_fields
    if not aadt_fields:
        raise RuntimeError("No AADT year fields were discovered in the UDOT AADT layer.")

    LOGGER.info(
        "Extracting UDOT AADT with years %s",
        sorted(year_fields),
    )
    features = query_all_features(
        AADT_LAYER_URL,
        out_fields=fields,
        return_geometry=False,
        page_size=ARCGIS_PAGE_SIZE,
    )
    rows = [dict(feature.get("attributes") or {}) for feature in features]
    result = pd.DataFrame(rows)
    result["EXTRACTED_AT_UTC"] = datetime.now(timezone.utc).isoformat()
    return result


def _series(df: pd.DataFrame, name: str) -> pd.Series:
    if name in df.columns:
        return df[name]
    # ArcGIS field casing can vary. Fall back case-insensitively.
    lookup = {str(col).upper(): col for col in df.columns}
    actual = lookup.get(name.upper())
    if actual is not None:
        return df[actual]
    return pd.Series(pd.NA, index=df.index, dtype="object")


def build_aadt_analysis_frame(
    raw: pd.DataFrame,
    min_analysis_year: int,
    max_analysis_year: int,
) -> pd.DataFrame:
    """
    Build one exposure row per roadway segment per historical analysis year.

    For each analysis year:
      - use same-year AADT when available;
      - otherwise use the latest available AADT year <= analysis year.

    This allows a newly completed crash year to move into the historical model
    automatically even when UDOT has not yet published same-year AADT. Proxy use
    is explicit via analysis_year vs aadt_year.
    """
    if raw.empty:
        raise RuntimeError("AADT source returned no rows.")

    year_fields = discover_aadt_year_fields(raw.columns)
    if not year_fields:
        raise RuntimeError("No AADTYYYY columns are available in the extracted AADT data.")

    available_years = sorted(year_fields)
    frames: list[pd.DataFrame] = []

    route_raw = _series(raw, "RouteID").astype("string").str.strip()
    route_numeric = pd.to_numeric(
        route_raw.str.extract(r"([0-9]+)", expand=False),
        errors="coerce",
    ).astype("Int64")

    common = pd.DataFrame(index=raw.index)
    common["segment_object_id"] = pd.to_numeric(
        _series(raw, "OBJECTID"), errors="coerce"
    ).astype("Int64")
    common["station"] = _series(raw, "Station").astype("string").str.strip()
    common["route_id_raw"] = route_raw
    common["route_key"] = route_numeric.astype("string")
    common["begin_point"] = pd.to_numeric(_series(raw, "BeginPoint"), errors="coerce")
    common["end_point"] = pd.to_numeric(_series(raw, "EndPoint"), errors="coerce")
    common["section_length"] = pd.to_numeric(
        _series(raw, "SectionLength"), errors="coerce"
    )
    common["segment_description"] = (
        _series(raw, "DESC_").astype("string").str.strip()
    )

    for analysis_year in range(int(min_analysis_year), int(max_analysis_year) + 1):
        eligible = [year for year in available_years if year <= analysis_year]
        if not eligible:
            raise RuntimeError(
                f"No AADT field is available at or before historical analysis year "
                f"{analysis_year}. Available AADT years: {available_years}"
            )

        aadt_year = max(eligible)
        aadt_field = year_fields[aadt_year]

        frame = common.copy()
        frame["analysis_year"] = int(analysis_year)
        frame["aadt_year"] = int(aadt_year)
        frame["aadt"] = pd.to_numeric(_series(raw, aadt_field), errors="coerce")
        frames.append(frame)

    result = pd.concat(frames, ignore_index=True)

    LOGGER.info(
        "Built dynamic AADT analysis years %s-%s using source AADT years %s",
        min_analysis_year,
        max_analysis_year,
        available_years,
    )
    proxy_years = sorted(
        result.loc[result["analysis_year"] != result["aadt_year"], "analysis_year"]
        .dropna()
        .astype(int)
        .unique()
        .tolist()
    )
    if proxy_years:
        LOGGER.warning(
            "AADT proxy exposure is used for analysis years: %s",
            proxy_years,
        )

    return result
