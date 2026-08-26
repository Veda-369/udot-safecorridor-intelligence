from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from src.config import (
    CRASH_MAX_YEAR,
    CRASH_MIN_YEAR,
    CURRENT_MONITOR_YEAR,
    PATHS,
    ROOT,
    SQL_DIR,
    ensure_directories,
)
from src.ingestion.aadt import (
    build_aadt_analysis_frame,
    discover_aadt_year_fields,
    extract_aadt,
)
from src.ingestion.crashes import extract_crashes
from src.quality.checks import validate_bronze

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
LOGGER = logging.getLogger(__name__)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _fail_on_error_checks(checks: list[dict]) -> None:
    failed = [
        c
        for c in checks
        if not bool(c["passed"]) and c.get("severity") == "error"
    ]
    if failed:
        names = ", ".join(c["name"] for c in failed)
        raise RuntimeError(f"Bronze validation failed: {names}")


def _execute_sql(con: duckdb.DuckDBPyConnection, filename: str) -> None:
    sql = (SQL_DIR / filename).read_text(encoding="utf-8")
    LOGGER.info("Executing %s", filename)
    con.execute(sql)


def _export(con: duckdb.DuckDBPyConnection, table: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_path = str(path).replace("'", "''")
    con.execute(
        f"COPY {table} TO '{safe_path}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )


def _records(df: pd.DataFrame) -> list[dict]:
    """Convert a DataFrame to JSON-native records without numpy scalar strings."""
    return json.loads(df.to_json(orient="records"))


def run() -> None:
    ensure_directories()
    started = datetime.now(timezone.utc)

    LOGGER.info(
        "Extracting completed-year historical crashes: %s-%s; current monitor year=%s",
        CRASH_MIN_YEAR,
        CRASH_MAX_YEAR,
        CURRENT_MONITOR_YEAR,
    )

    crashes = extract_crashes()

    LOGGER.info("Extracting AADT")
    aadt = extract_aadt()
    aadt_year_fields = discover_aadt_year_fields(aadt.columns)

    aadt_analysis = build_aadt_analysis_frame(
        aadt,
        CRASH_MIN_YEAR,
        CRASH_MAX_YEAR,
    )
    if aadt_analysis.empty:
        raise RuntimeError("Dynamic AADT analysis frame is empty.")

    checks = validate_bronze(crashes, aadt)
    _write_json(
        PATHS.quality_json,
        {
            "generated_at_utc": started.isoformat(),
            "checks": checks,
        },
    )
    _fail_on_error_checks(checks)

    crashes.to_parquet(PATHS.bronze_crashes, index=False)
    aadt.to_parquet(PATHS.bronze_aadt, index=False)

    con = duckdb.connect(str(PATHS.duckdb))
    try:
        con.execute(
            "CREATE OR REPLACE TABLE bronze_crashes AS "
            "SELECT * FROM read_parquet(?)",
            [str(PATHS.bronze_crashes)],
        )
        con.execute(
            "CREATE OR REPLACE TABLE bronze_aadt AS "
            "SELECT * FROM read_parquet(?)",
            [str(PATHS.bronze_aadt)],
        )

        con.register("aadt_analysis_df", aadt_analysis)
        con.execute(
            "CREATE OR REPLACE TABLE aadt_analysis_source AS "
            "SELECT * FROM aadt_analysis_df"
        )

        _execute_sql(con, "01_silver_crashes.sql")
        _execute_sql(con, "02_silver_aadt.sql")
        _execute_sql(con, "03_gold_risk.sql")
        _execute_sql(con, "04_gold_points.sql")

        _export(con, "silver_crashes", PATHS.silver_crashes)
        _export(con, "silver_aadt_analysis", PATHS.silver_aadt)
        _export(con, "gold_segment_risk", PATHS.gold_segment_risk)
        _export(con, "gold_route_risk", PATHS.gold_route_risk)
        _export(con, "gold_severe_crash_points", PATHS.gold_crash_points)
        _export(con, "gold_quality_summary", PATHS.gold_quality)

        quality_df = con.execute(
            "SELECT * FROM gold_quality_summary"
        ).fetchdf()
        top_routes_df = con.execute(
            """
            SELECT route_key, severe_crashes, severe_crashes_per_100m_vmt,
                   observed_expected_ratio, screening_band
            FROM gold_route_risk
            WHERE severe_crashes >= 3
            ORDER BY observed_expected_ratio DESC NULLS LAST
            LIMIT 10
            """
        ).fetchdf()
    finally:
        con.close()

    finished = datetime.now(timezone.utc)

    available_aadt_years = sorted(aadt_year_fields)
    analysis_proxy_map = (
        aadt_analysis[["analysis_year", "aadt_year"]]
        .drop_duplicates()
        .sort_values("analysis_year")
    )

    _write_json(
        PATHS.pipeline_json,
        {
            "status": "success",
            "started_at_utc": started.isoformat(),
            "finished_at_utc": finished.isoformat(),
            "duration_seconds": (finished - started).total_seconds(),
            "historical_crash_year_min": CRASH_MIN_YEAR,
            "historical_crash_year_max": CRASH_MAX_YEAR,
            "current_monitor_year": CURRENT_MONITOR_YEAR,
            "crash_rows": int(len(crashes)),
            "aadt_rows": int(len(aadt)),
            "aadt_available_source_years": available_aadt_years,
            "aadt_analysis_year_mapping": _records(analysis_proxy_map),
            "quality": _records(quality_df),
            "top_screening_routes": _records(top_routes_df),
        },
    )

    LOGGER.info(
        "Pipeline complete. See %s",
        PATHS.pipeline_json.relative_to(ROOT),
    )


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        LOGGER.exception("Pipeline failed: %s", exc)
        sys.exit(1)
