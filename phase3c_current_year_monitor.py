from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from src.config import (
    CURRENT_MONITOR_COMPARE_YEARS,
    CURRENT_MONITOR_YEAR,
    PATHS,
    ROOT,
    ensure_directories,
)
from src.ingestion.crashes import discover_crash_layers, extract_crashes

OUT_CRASHES = PATHS.gold_current_year_crashes
OUT_COUNTY = PATHS.gold_current_year_county
OUT_ROUTE = PATHS.gold_current_year_route
OUT_COMPARE = PATHS.gold_current_year_compare
OUT_MONTHLY = PATHS.gold_current_year_monthly
OUT_REPORT = PATHS.current_year_json

SEVERE_VALUES = {"Fatal", "Suspected Serious Injury"}
TRUE_VALUES = {"Y", "YES", "1", "TRUE", "T"}


def _flag(series: pd.Series) -> pd.Series:
    return (
        series.fillna("")
        .astype(str)
        .str.strip()
        .str.upper()
        .isin(TRUE_VALUES)
        .astype("int8")
    )


def _parse_datetime(series: pd.Series) -> pd.Series:
    """Parse either ArcGIS epoch-ms values or ISO/timestamp-offset strings."""
    numeric = pd.to_numeric(series, errors="coerce")
    from_epoch = pd.to_datetime(numeric, unit="ms", errors="coerce", utc=True)
    from_text = pd.to_datetime(series, errors="coerce", utc=True)
    return from_epoch.fillna(from_text)


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
            ]
        )

    df = pd.DataFrame(index=raw.index)
    df["crash_id"] = pd.to_numeric(raw.get("CRASH_ID"), errors="coerce").astype("Int64")
    df["crash_datetime"] = _parse_datetime(raw.get("CRASH_DATETIME"))
    df["crash_date"] = df["crash_datetime"].dt.date
    df["crash_year"] = CURRENT_MONITOR_YEAR
    df["county_name"] = raw.get("COUNTY_NAME").fillna("Unknown").astype(str).str.strip().str.upper()
    df["route_num"] = _route_num(raw.get("ROUTE"))
    df["latitude"] = pd.to_numeric(raw.get("LATITUDE"), errors="coerce")
    df["longitude"] = pd.to_numeric(raw.get("LONGITUDE"), errors="coerce")
    df["severity"] = raw.get("CRASH_SEVERITY_DESC").fillna("").astype(str).str.strip()
    df["severe_crash_flag"] = df["severity"].isin(SEVERE_VALUES).astype("int8")
    df["fatal_crash_flag"] = (df["severity"] == "Fatal").astype("int8")
    df["speed_related_flag"] = _flag(raw.get("SPEED_RELATED"))
    df["dui_flag"] = _flag(raw.get("DUI"))
    df["distracted_driving_flag"] = _flag(raw.get("DISTRACTED_DRIVING"))
    df["roadway_departure_flag"] = _flag(raw.get("ROADWAY_DEPARTURE"))

    # Remove duplicate crash IDs, preferring the latest row in source order.
    df = df.drop_duplicates(subset=["crash_id"], keep="last")
    return df.reset_index(drop=True)


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

    OUT_REPORT.write_text(
        json.dumps(
            {
                "status": status,
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "current_year": CURRENT_MONITOR_YEAR,
                "message": message,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    ensure_directories()

    layers = discover_crash_layers(
        CURRENT_MONITOR_YEAR,
        CURRENT_MONITOR_YEAR,
        prefer_current_service=True,
    )
    if not layers:
        _empty_outputs(
            "current_layer_unavailable",
            f"UDOT has not published a {CURRENT_MONITOR_YEAR} crash layer yet.",
        )
        print(f"No {CURRENT_MONITOR_YEAR} crash layer is available yet; monitor outputs are empty.")
        return

    raw = extract_crashes(
        CURRENT_MONITOR_YEAR,
        CURRENT_MONITOR_YEAR,
        prefer_current_service=True,
        allow_empty=True,
    )
    current = _normalize_current(raw)

    if current.empty:
        _empty_outputs(
            "current_layer_empty",
            f"The {CURRENT_MONITOR_YEAR} crash layer exists but returned no records.",
        )
        return

    valid_dates = current["crash_datetime"].dropna()
    if valid_dates.empty:
        cutoff = datetime.now(timezone.utc).date()
    else:
        cutoff = valid_dates.max().date()

    # Keep only records through the observed data cutoff for consistent YTD comparisons.
    current = current[
        current["crash_datetime"].isna()
        | (current["crash_datetime"].dt.date <= cutoff)
    ].copy()

    if not PATHS.silver_crashes.exists():
        raise SystemExit(
            f"Historical Silver dataset not found: {PATHS.silver_crashes}. "
            "Run python -m src.pipeline first."
        )

    hist = pd.read_parquet(PATHS.silver_crashes)
    hist["crash_year"] = pd.to_numeric(hist["crash_year"], errors="coerce").astype("Int64")
    hist["crash_datetime"] = pd.to_datetime(hist["crash_timestamp"], errors="coerce", utc=True)
    hist["county_name"] = hist["county_name"].fillna("Unknown").astype(str).str.strip().str.upper()
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

    # ------------------------------------------------------------------
    # Statewide same-period comparison
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # County comparison
    # ------------------------------------------------------------------
    curr_county = (
        current.groupby("county_name", dropna=False)
        .agg(
            current_crashes=("crash_id", "count"),
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
        # Reindex year/county combinations so a zero-crash prior year is included
        # in the average rather than silently dropped.
        all_counties = sorted(set(curr_county["county_name"]) | set(hist_county_year["county_name"]))
        grid = pd.MultiIndex.from_product(
            [comparison_years, all_counties], names=["crash_year", "county_name"]
        ).to_frame(index=False)
        hist_county_year = grid.merge(
            hist_county_year, on=["crash_year", "county_name"], how="left"
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
            columns=["county_name", "historical_avg_severe_crashes", "historical_avg_fatal_crashes"]
        )

    county = curr_county.merge(hist_county_avg, on="county_name", how="left")
    county["severe_vs_history_pct"] = _safe_pct_delta(
        county["current_severe_crashes"], county["historical_avg_severe_crashes"]
    )
    county = county.sort_values("current_severe_crashes", ascending=False)
    county.to_parquet(OUT_COUNTY, index=False)

    # ------------------------------------------------------------------
    # Route comparison
    # ------------------------------------------------------------------
    curr_route = (
        current[current["route_num"].notna()]
        .groupby("route_num")
        .agg(
            current_crashes=("crash_id", "count"),
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
            [comparison_years, routes], names=["crash_year", "route_num"]
        ).to_frame(index=False)
        hist_route_year = grid.merge(
            hist_route_year, on=["crash_year", "route_num"], how="left"
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
            columns=["route_num", "historical_avg_severe_crashes", "historical_avg_fatal_crashes"]
        )

    route = curr_route.merge(hist_route_avg, on="route_num", how="left")
    route["severe_vs_history_pct"] = _safe_pct_delta(
        route["current_severe_crashes"], route["historical_avg_severe_crashes"]
    )
    route = route.sort_values("current_severe_crashes", ascending=False)
    route.to_parquet(OUT_ROUTE, index=False)

    # ------------------------------------------------------------------
    # Monthly severe/fatal trend versus same-period historical average
    # ------------------------------------------------------------------
    current_monthly = (
        current[current["crash_datetime"].notna()]
        .assign(month=lambda x: x["crash_datetime"].dt.month)
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
            hist_month_year, on=["crash_year", "month"], how="left"
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
            columns=["month", "historical_avg_severe_crashes", "historical_avg_fatal_crashes"]
        )

    monthly = pd.DataFrame({"month": range(1, cutoff.month + 1)})
    monthly = monthly.merge(current_monthly, on="month", how="left").merge(
        hist_month_avg, on="month", how="left"
    )
    monthly = monthly.fillna(0)
    monthly["month_name"] = monthly["month"].map(
        {i: pd.Timestamp(2000, i, 1).strftime("%b") for i in range(1, 13)}
    )
    monthly.to_parquet(OUT_MONTHLY, index=False)

    historical_avg = compare.loc[compare["is_current_year"] == 0, [
        "crashes", "severe_crashes", "fatal_crashes"
    ]].mean(numeric_only=True)

    report = {
        "status": "success",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "current_year": CURRENT_MONITOR_YEAR,
        "data_through_date": cutoff.isoformat(),
        "comparison_years": comparison_years,
        "source_layer": {
            "year": layers[0].year,
            "source": layers[0].source,
            "service_url": layers[0].service_url,
            "layer_id": layers[0].layer_id,
        },
        "summary": current_counts,
        "historical_same_period_average": {
            key: (round(float(value), 2) if pd.notna(value) else None)
            for key, value in historical_avg.items()
        },
        "notes": [
            "Current-year data are preliminary year-to-date observations.",
            "Recent crashes can be delayed or revised as UDOT completes entry and review.",
            "The current year is excluded from the historical O/E/FDR prioritization model until the calendar year is complete.",
            "At year rollover, the completed year automatically becomes eligible for the historical model and the new calendar year becomes the YTD monitor year.",
        ],
    }
    OUT_REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print("\nPHASE 3C CURRENT-YEAR MONITOR COMPLETE")
    print("======================================")
    print(f"Current monitor year: {CURRENT_MONITOR_YEAR}")
    print(f"Data through: {cutoff.isoformat()}")
    print(f"Crash records: {len(current):,}")
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
