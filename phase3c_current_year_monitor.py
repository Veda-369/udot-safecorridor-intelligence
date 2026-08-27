from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from src.config import (
    CURRENT_MONITOR_COMPARE_YEARS,
    CURRENT_MONITOR_YEAR,
    PATHS,
    ROOT,
    ensure_directories,
)
from src.ingestion.incremental import load_current_year_crashes

OUT_CRASHES = PATHS.gold_current_year_crashes
OUT_COUNTY = PATHS.gold_current_year_county
OUT_ROUTE = PATHS.gold_current_year_route
OUT_COMPARE = PATHS.gold_current_year_compare
OUT_MONTHLY = PATHS.gold_current_year_monthly
OUT_REPORT = PATHS.current_year_json

SEVERE_VALUES = {"Fatal", "Suspected Serious Injury"}
TRUE_VALUES = {"Y", "YES", "1", "TRUE", "T"}
UTAH_TZ = ZoneInfo("America/Denver")

# Plausible epoch bounds. Values outside these ranges are treated as invalid
# rather than passed to pandas where overflow may occur.
MIN_EPOCH_SECONDS = 631152000      # 1990-01-01 UTC
MAX_EPOCH_SECONDS = 7258118400     # 2200-01-01 UTC
MIN_EPOCH_MILLISECONDS = MIN_EPOCH_SECONDS * 1000
MAX_EPOCH_MILLISECONDS = MAX_EPOCH_SECONDS * 1000


def _column(df: pd.DataFrame, name: str, default=None) -> pd.Series:
    if name in df.columns:
        return df[name]
    return pd.Series(default, index=df.index, dtype="object")


def _flag(series: pd.Series) -> pd.Series:
    return (
        series.fillna("")
        .astype(str)
        .str.strip()
        .str.upper()
        .isin(TRUE_VALUES)
        .astype("int8")
    )


def _parse_datetime(series: pd.Series | None) -> pd.Series:
    """
    Parse UDOT date values safely.

    Supports:
    - ArcGIS TimestampOffset / ISO-8601 strings
    - epoch milliseconds
    - epoch seconds
    - null/invalid values

    Returns timezone-aware UTC timestamps. Numeric values are range-checked
    before conversion to prevent pandas/numpy overflow.
    """
    if series is None:
        return pd.Series(dtype="datetime64[ns, UTC]")

    s = pd.Series(series).copy()
    result = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns, UTC]")

    numeric = pd.to_numeric(s, errors="coerce")
    numeric_mask = numeric.notna()

    # Parse non-numeric values as ISO/timestamp-offset text.
    text_mask = ~numeric_mask & s.notna()
    if text_mask.any():
        result.loc[text_mask] = pd.to_datetime(
            s.loc[text_mask],
            errors="coerce",
            utc=True,
            format="mixed",
        )

    # Guarded epoch-ms parsing.
    ms_mask = (
        numeric_mask
        & numeric.between(
            MIN_EPOCH_MILLISECONDS,
            MAX_EPOCH_MILLISECONDS,
            inclusive="both",
        )
    )
    if ms_mask.any():
        result.loc[ms_mask] = pd.to_datetime(
            numeric.loc[ms_mask],
            unit="ms",
            errors="coerce",
            utc=True,
        )

    # Guarded epoch-seconds parsing.
    sec_mask = (
        numeric_mask
        & ~ms_mask
        & numeric.between(
            MIN_EPOCH_SECONDS,
            MAX_EPOCH_SECONDS,
            inclusive="both",
        )
    )
    if sec_mask.any():
        result.loc[sec_mask] = pd.to_datetime(
            numeric.loc[sec_mask],
            unit="s",
            errors="coerce",
            utc=True,
        )

    return result


def _to_utah_local(series: pd.Series) -> pd.Series:
    if series.empty:
        return series
    return series.dt.tz_convert(UTAH_TZ)


def _route_num(series: pd.Series) -> pd.Series:
    extracted = series.fillna("").astype(str).str.extract(r"(\d+)", expand=False)
    return pd.to_numeric(extracted, errors="coerce").astype("Int64")


def _normalize_current(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(
            columns=[
                "crash_id",
                "crash_datetime",
                "crash_date",
                "crash_year",
                "current_as_of_datetime",
                "county_name",
                "route_num",
                "latitude",
                "longitude",
                "severity",
                "severe_crash_flag",
                "fatal_crash_flag",
                "speed_related_flag",
                "dui_flag",
                "distracted_driving_flag",
                "roadway_departure_flag",
                "valid_crash_date_flag",
                "monitor_year_date_flag",
            ]
        )

    df = pd.DataFrame(index=raw.index)
    df["_source_order"] = np.arange(len(raw), dtype="int64")
    df["crash_id"] = pd.to_numeric(_column(raw, "CRASH_ID"), errors="coerce").astype("Int64")

    crash_utc = _parse_datetime(_column(raw, "CRASH_DATETIME"))
    asof_utc = _parse_datetime(_column(raw, "CURRENT_AS_OF_DATE"))

    df["crash_datetime"] = _to_utah_local(crash_utc)
    df["current_as_of_datetime"] = _to_utah_local(asof_utc)
    df["crash_date"] = df["crash_datetime"].dt.date
    df["crash_year"] = CURRENT_MONITOR_YEAR

    df["county_name"] = (
        _column(raw, "COUNTY_NAME", "Unknown")
        .fillna("Unknown")
        .astype(str)
        .str.strip()
        .str.upper()
    )
    df["route_num"] = _route_num(_column(raw, "ROUTE"))
    df["latitude"] = pd.to_numeric(_column(raw, "LATITUDE"), errors="coerce")
    df["longitude"] = pd.to_numeric(_column(raw, "LONGITUDE"), errors="coerce")
    df["severity"] = (
        _column(raw, "CRASH_SEVERITY_DESC")
        .fillna("")
        .astype(str)
        .str.strip()
    )
    df["severe_crash_flag"] = df["severity"].isin(SEVERE_VALUES).astype("int8")
    df["fatal_crash_flag"] = (df["severity"] == "Fatal").astype("int8")
    df["speed_related_flag"] = _flag(_column(raw, "SPEED_RELATED"))
    df["dui_flag"] = _flag(_column(raw, "DUI"))
    df["distracted_driving_flag"] = _flag(_column(raw, "DISTRACTED_DRIVING"))
    df["roadway_departure_flag"] = _flag(_column(raw, "ROADWAY_DEPARTURE"))

    df["valid_crash_date_flag"] = df["crash_datetime"].notna().astype("int8")
    df["monitor_year_date_flag"] = (
        df["crash_datetime"].notna()
        & (df["crash_datetime"].dt.year == CURRENT_MONITOR_YEAR)
    ).astype("int8")

    # Deduplicate only non-null IDs. Multiple rows with null crash IDs must not
    # collapse into one synthetic duplicate group.
    with_id = (
        df[df["crash_id"].notna()]
        .sort_values("_source_order")
        .drop_duplicates(subset=["crash_id"], keep="last")
    )
    without_id = df[df["crash_id"].isna()]
    df = pd.concat([with_id, without_id], ignore_index=True)
    df = df.sort_values("_source_order").drop(columns=["_source_order"]).reset_index(drop=True)

    return df


def _within_month_day(ts: pd.Series, month: int, day: int) -> pd.Series:
    return (ts.dt.month < month) | ((ts.dt.month == month) & (ts.dt.day <= day))


def _year_counts(df: pd.DataFrame, year: int) -> dict[str, int]:
    subset = df[df["crash_year"] == year]
    return {
        "year": int(year),
        "crashes": int(len(subset)),
        "severe_crashes": int(subset["severe_crash_flag"].sum()),
        "fatal_crashes": int(subset["fatal_crash_flag"].sum()),
    }


def _safe_pct_delta(current: pd.Series, baseline: pd.Series) -> pd.Series:
    baseline = pd.to_numeric(baseline, errors="coerce")
    current = pd.to_numeric(current, errors="coerce")
    return np.where(
        baseline > 0,
        (current - baseline) / baseline * 100.0,
        np.nan,
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _empty_outputs(status: str, message: str) -> None:
    ensure_directories()
    empty_crashes = _normalize_current(pd.DataFrame())
    empty_county = pd.DataFrame(
        columns=[
            "county_name",
            "current_crashes",
            "current_severe_crashes",
            "current_fatal_crashes",
            "historical_avg_severe_crashes",
            "historical_avg_fatal_crashes",
            "severe_vs_history_pct",
        ]
    )
    empty_route = pd.DataFrame(
        columns=[
            "route_num",
            "current_crashes",
            "current_severe_crashes",
            "current_fatal_crashes",
            "historical_avg_severe_crashes",
            "historical_avg_fatal_crashes",
            "severe_vs_history_pct",
        ]
    )
    empty_compare = pd.DataFrame(
        columns=["year", "crashes", "severe_crashes", "fatal_crashes", "is_current_year"]
    )
    empty_monthly = pd.DataFrame(
        columns=[
            "month",
            "month_name",
            "current_severe_crashes",
            "historical_avg_severe_crashes",
            "current_fatal_crashes",
            "historical_avg_fatal_crashes",
        ]
    )

    for df, path in (
        (empty_crashes, OUT_CRASHES),
        (empty_county, OUT_COUNTY),
        (empty_route, OUT_ROUTE),
        (empty_compare, OUT_COMPARE),
        (empty_monthly, OUT_MONTHLY),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False)

    _write_json(
        OUT_REPORT,
        {
            "status": status,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "current_year": CURRENT_MONITOR_YEAR,
            "message": message,
        },
    )


def _resolve_cutoff(current: pd.DataFrame) -> tuple[datetime.date, datetime.date | None]:
    today_utah = datetime.now(UTAH_TZ).date()

    asof = current["current_as_of_datetime"].dropna()
    if not asof.empty:
        data_as_of = asof.max().date()
    else:
        valid_crash_dates = current["crash_datetime"].dropna()
        data_as_of = valid_crash_dates.max().date() if not valid_crash_dates.empty else None

    if data_as_of is None:
        return today_utah, None

    return min(today_utah, data_as_of), data_as_of


def main() -> None:
    ensure_directories()

    incremental_load = load_current_year_crashes(CURRENT_MONITOR_YEAR)
    if incremental_load.layer is None:
        _empty_outputs(
            "current_layer_unavailable",
            f"UDOT has not published a {CURRENT_MONITOR_YEAR} crash layer yet.",
        )
        print(f"No {CURRENT_MONITOR_YEAR} crash layer is available yet; monitor outputs are empty.")
        return

    layer = incremental_load.layer
    raw = incremental_load.frame
    current_all = _normalize_current(raw)

    if current_all.empty:
        _empty_outputs(
            "current_layer_empty",
            f"The {CURRENT_MONITOR_YEAR} crash layer exists but returned no records.",
        )
        return

    cutoff, data_as_of = _resolve_cutoff(current_all)

    # Same-period YTD outputs use only records with a valid Utah-local crash date
    # inside the monitor year. Invalid/undated rows remain visible in QA metrics.
    current = current_all[
        (current_all["valid_crash_date_flag"] == 1)
        & (current_all["monitor_year_date_flag"] == 1)
        & (current_all["crash_datetime"].dt.date <= cutoff)
    ].copy()

    if not PATHS.silver_crashes.exists():
        raise SystemExit(
            f"Historical Silver dataset not found: {PATHS.silver_crashes}. "
            "Run python -m src.pipeline first."
        )

    hist = pd.read_parquet(PATHS.silver_crashes)
    hist["crash_year"] = pd.to_numeric(hist["crash_year"], errors="coerce").astype("Int64")

    # Historical epoch timestamps represent UTC instants. Convert them to Utah
    # local time before month/day same-period comparisons.
    hist_utc = pd.to_datetime(hist["crash_timestamp"], errors="coerce", utc=True)
    hist["crash_datetime"] = hist_utc.dt.tz_convert(UTAH_TZ)

    hist["county_name"] = (
        hist["county_name"].fillna("Unknown").astype(str).str.strip().str.upper()
    )
    hist["route_num"] = pd.to_numeric(hist["route_key"], errors="coerce").astype("Int64")

    available_hist_years = sorted(
        int(y)
        for y in hist["crash_year"].dropna().unique().tolist()
        if int(y) < CURRENT_MONITOR_YEAR
    )
    comparison_years = available_hist_years[-CURRENT_MONITOR_COMPARE_YEARS:]

    hist_ytd = hist[
        hist["crash_year"].isin(comparison_years)
        & hist["crash_datetime"].notna()
        & _within_month_day(hist["crash_datetime"], cutoff.month, cutoff.day)
    ].copy()

    current.to_parquet(OUT_CRASHES, index=False)

    comparison_rows = [_year_counts(hist_ytd, year) for year in comparison_years]
    current_counts = {
        "year": CURRENT_MONITOR_YEAR,
        "crashes": int(len(current)),
        "severe_crashes": int(current["severe_crash_flag"].sum()),
        "fatal_crashes": int(current["fatal_crash_flag"].sum()),
    }
    comparison_rows.append(current_counts)
    compare = pd.DataFrame(comparison_rows)
    compare["is_current_year"] = (compare["year"] == CURRENT_MONITOR_YEAR).astype("int8")
    compare.to_parquet(OUT_COMPARE, index=False)

    curr_county = (
        current.groupby("county_name", dropna=False)
        .agg(
            current_crashes=("severe_crash_flag", "size"),
            current_severe_crashes=("severe_crash_flag", "sum"),
            current_fatal_crashes=("fatal_crash_flag", "sum"),
        )
        .reset_index()
    )

    if comparison_years:
        hist_county_year = (
            hist_ytd.groupby(["crash_year", "county_name"], dropna=False)
            .agg(
                severe_crashes=("severe_crash_flag", "sum"),
                fatal_crashes=("fatal_crash_flag", "sum"),
            )
            .reset_index()
        )
        all_counties = sorted(
            set(curr_county["county_name"]) | set(hist_county_year["county_name"])
        )
        grid = pd.MultiIndex.from_product(
            [comparison_years, all_counties],
            names=["crash_year", "county_name"],
        ).to_frame(index=False)
        hist_county_year = grid.merge(
            hist_county_year,
            on=["crash_year", "county_name"],
            how="left",
        ).fillna({"severe_crashes": 0, "fatal_crashes": 0})
        hist_county_avg = (
            hist_county_year.groupby("county_name")
            .agg(
                historical_avg_severe_crashes=("severe_crashes", "mean"),
                historical_avg_fatal_crashes=("fatal_crashes", "mean"),
            )
            .reset_index()
        )
    else:
        hist_county_avg = pd.DataFrame(
            columns=[
                "county_name",
                "historical_avg_severe_crashes",
                "historical_avg_fatal_crashes",
            ]
        )

    county = curr_county.merge(hist_county_avg, on="county_name", how="left")
    county["severe_vs_history_pct"] = _safe_pct_delta(
        county["current_severe_crashes"],
        county["historical_avg_severe_crashes"],
    )
    county = county.sort_values("current_severe_crashes", ascending=False)
    county.to_parquet(OUT_COUNTY, index=False)

    curr_route = (
        current[current["route_num"].notna()]
        .groupby("route_num")
        .agg(
            current_crashes=("severe_crash_flag", "size"),
            current_severe_crashes=("severe_crash_flag", "sum"),
            current_fatal_crashes=("fatal_crash_flag", "sum"),
        )
        .reset_index()
    )

    if comparison_years:
        hist_route_year = (
            hist_ytd[hist_ytd["route_num"].notna()]
            .groupby(["crash_year", "route_num"])
            .agg(
                severe_crashes=("severe_crash_flag", "sum"),
                fatal_crashes=("fatal_crash_flag", "sum"),
            )
            .reset_index()
        )
        routes = sorted(
            set(curr_route["route_num"].dropna().astype(int).tolist())
            | set(hist_route_year["route_num"].dropna().astype(int).tolist())
        )
        grid = pd.MultiIndex.from_product(
            [comparison_years, routes],
            names=["crash_year", "route_num"],
        ).to_frame(index=False)
        hist_route_year = grid.merge(
            hist_route_year,
            on=["crash_year", "route_num"],
            how="left",
        ).fillna({"severe_crashes": 0, "fatal_crashes": 0})
        hist_route_avg = (
            hist_route_year.groupby("route_num")
            .agg(
                historical_avg_severe_crashes=("severe_crashes", "mean"),
                historical_avg_fatal_crashes=("fatal_crashes", "mean"),
            )
            .reset_index()
        )
    else:
        hist_route_avg = pd.DataFrame(
            columns=[
                "route_num",
                "historical_avg_severe_crashes",
                "historical_avg_fatal_crashes",
            ]
        )

    route = curr_route.merge(hist_route_avg, on="route_num", how="left")
    route["severe_vs_history_pct"] = _safe_pct_delta(
        route["current_severe_crashes"],
        route["historical_avg_severe_crashes"],
    )
    route = route.sort_values("current_severe_crashes", ascending=False)
    route.to_parquet(OUT_ROUTE, index=False)

    current_monthly = (
        current.assign(month=current["crash_datetime"].dt.month)
        .groupby("month")
        .agg(
            current_severe_crashes=("severe_crash_flag", "sum"),
            current_fatal_crashes=("fatal_crash_flag", "sum"),
        )
        .reset_index()
    )

    if comparison_years:
        hist_month_year = (
            hist_ytd.assign(month=hist_ytd["crash_datetime"].dt.month)
            .groupby(["crash_year", "month"])
            .agg(
                severe_crashes=("severe_crash_flag", "sum"),
                fatal_crashes=("fatal_crash_flag", "sum"),
            )
            .reset_index()
        )
        month_grid = pd.MultiIndex.from_product(
            [comparison_years, range(1, cutoff.month + 1)],
            names=["crash_year", "month"],
        ).to_frame(index=False)
        hist_month_year = month_grid.merge(
            hist_month_year,
            on=["crash_year", "month"],
            how="left",
        ).fillna({"severe_crashes": 0, "fatal_crashes": 0})
        hist_month_avg = (
            hist_month_year.groupby("month")
            .agg(
                historical_avg_severe_crashes=("severe_crashes", "mean"),
                historical_avg_fatal_crashes=("fatal_crashes", "mean"),
            )
            .reset_index()
        )
    else:
        hist_month_avg = pd.DataFrame(
            columns=[
                "month",
                "historical_avg_severe_crashes",
                "historical_avg_fatal_crashes",
            ]
        )

    monthly = pd.DataFrame({"month": range(1, cutoff.month + 1)})
    monthly = monthly.merge(current_monthly, on="month", how="left").merge(
        hist_month_avg,
        on="month",
        how="left",
    )
    monthly = monthly.fillna(0)
    monthly["month_name"] = monthly["month"].map(
        {i: pd.Timestamp(2000, i, 1).strftime("%b") for i in range(1, 13)}
    )
    monthly.to_parquet(OUT_MONTHLY, index=False)

    historical_avg = compare.loc[
        compare["is_current_year"] == 0,
        ["crashes", "severe_crashes", "fatal_crashes"],
    ].mean(numeric_only=True)

    valid_ids = current_all["crash_id"].dropna()
    quality = {
        "source_records": int(len(raw)),
        "normalized_records": int(len(current_all)),
        "dated_monitor_year_records": int(len(current)),
        "missing_crash_id_records": int(current_all["crash_id"].isna().sum()),
        "invalid_or_missing_crash_datetime_records": int(
            (current_all["valid_crash_date_flag"] == 0).sum()
        ),
        "crash_dates_outside_monitor_year_records": int(
            (
                (current_all["valid_crash_date_flag"] == 1)
                & (current_all["monitor_year_date_flag"] == 0)
            ).sum()
        ),
        "duplicate_non_null_ids_after_normalization": int(valid_ids.duplicated().sum()),
    }

    report = {
        "status": "success",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "current_year": CURRENT_MONITOR_YEAR,
        "data_as_of_date": data_as_of.isoformat() if data_as_of else None,
        "data_through_date": cutoff.isoformat(),
        "comparison_years": comparison_years,
        "source_layer": {
            "year": layer.year,
            "source": layer.source,
            "service_url": layer.service_url,
            "layer_id": layer.layer_id,
        },
        "summary": current_counts,
        "incremental_refresh": incremental_load.stats,
        "quality": quality,
        "historical_same_period_average": {
            key: (round(float(value), 2) if pd.notna(value) else None)
            for key, value in historical_avg.items()
        },
        "notes": [
            "Current-year data are preliminary year-to-date observations.",
            "Recent crashes can be delayed or revised as UDOT completes entry and review.",
            "TimestampOffset values are normalized to America/Denver before date-based comparisons.",
            "Undated/current-year-invalid records are excluded from same-period YTD comparisons and reported in quality metrics.",
            "The current year is excluded from the historical O/E/FDR prioritization model until the calendar year is complete.",
        ],
    }
    _write_json(OUT_REPORT, report)

    print("\nPHASE 3C CURRENT-YEAR MONITOR COMPLETE")
    print("======================================")
    print(f"Current monitor year: {CURRENT_MONITOR_YEAR}")
    print(f"Data as of: {report['data_as_of_date']}")
    print(f"Comparison cutoff: {cutoff.isoformat()}")
    print(f"YTD dated crash records: {len(current):,}")
    print(f"Severe crashes: {int(current['severe_crash_flag'].sum()):,}")
    print(f"Fatal crashes: {int(current['fatal_crash_flag'].sum()):,}")
    print(f"Comparison years: {comparison_years}")
    print(f"Saved: {OUT_CRASHES.relative_to(ROOT)}")
    print(f"Saved: {OUT_COUNTY.relative_to(ROOT)}")
    print(f"Saved: {OUT_ROUTE.relative_to(ROOT)}")
    print(f"Saved: {OUT_COMPARE.relative_to(ROOT)}")
    print(f"Saved: {OUT_MONTHLY.relative_to(ROOT)}")
    print(f"Saved: {OUT_REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
