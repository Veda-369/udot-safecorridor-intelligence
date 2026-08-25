from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd


@dataclass
class Check:
    name: str
    passed: bool
    value: float | int | str
    threshold: str
    severity: str = "error"


def _pct(value: float) -> float:
    return round(float(value) * 100.0, 3)


def validate_bronze(crashes: pd.DataFrame, aadt: pd.DataFrame) -> list[dict]:
    checks: list[Check] = []

    crash_count = len(crashes)
    aadt_count = len(aadt)
    checks.append(Check("crash_rows_present", crash_count > 0, crash_count, "> 0"))
    checks.append(Check("aadt_rows_present", aadt_count > 0, aadt_count, "> 0"))

    if crash_count:
        crash_id_missing = crashes.get("CRASH_ID", pd.Series(dtype="object")).isna().mean()
        crash_id_dup = crashes.get("CRASH_ID", pd.Series(dtype="object")).duplicated().mean()
        severity_missing = crashes.get("CRASH_SEVERITY_DESC", pd.Series(dtype="object")).isna().mean()
        coords = crashes[["LATITUDE", "LONGITUDE"]].copy() if {"LATITUDE", "LONGITUDE"}.issubset(crashes.columns) else pd.DataFrame()
        if not coords.empty:
            plausible = (
                coords["LATITUDE"].between(36.8, 42.2, inclusive="both")
                & coords["LONGITUDE"].between(-114.3, -108.7, inclusive="both")
            )
            coordinate_valid_rate = plausible.fillna(False).mean()
        else:
            coordinate_valid_rate = 0.0

        checks.extend(
            [
                Check("crash_id_missing_pct", crash_id_missing <= 0.01, _pct(crash_id_missing), "<= 1%"),
                Check("crash_id_duplicate_pct", crash_id_dup <= 0.01, _pct(crash_id_dup), "<= 1%"),
                Check("severity_missing_pct", severity_missing <= 0.01, _pct(severity_missing), "<= 1%"),
                Check("plausible_coordinate_pct", coordinate_valid_rate >= 0.95, _pct(coordinate_valid_rate), ">= 95%", "warning"),
            ]
        )

    if aadt_count:
        route_missing = aadt.get("RouteID", pd.Series(dtype="object")).isna().mean()
        segment_missing = aadt.get("SectionLength", pd.Series(dtype="object")).isna().mean()
        checks.extend(
            [
                Check("aadt_route_missing_pct", route_missing <= 0.01, _pct(route_missing), "<= 1%"),
                Check("aadt_segment_length_missing_pct", segment_missing <= 0.05, _pct(segment_missing), "<= 5%"),
            ]
        )

    return [asdict(check) for check in checks]
