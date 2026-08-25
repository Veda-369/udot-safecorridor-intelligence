from __future__ import annotations

import logging
from datetime import datetime, timezone

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


def extract_aadt() -> pd.DataFrame:
    metadata = layer_metadata(AADT_LAYER_URL)
    available_fields = {field["name"] for field in metadata.get("fields", [])}
    aadt_fields = sorted(
        (name for name in available_fields if name.upper().startswith("AADT") and name[4:].isdigit()),
        key=lambda name: int(name[4:]),
    )
    fields = [field for field in BASE_FIELDS if field in available_fields] + aadt_fields

    if not aadt_fields:
        raise RuntimeError("No AADT year fields were discovered in the UDOT AADT layer.")

    LOGGER.info("Extracting UDOT AADT with %s historical AADT fields", len(aadt_fields))
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
