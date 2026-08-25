from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "warehouse" / "udot_safecorridor.duckdb"

OUT_POINTS = ROOT / "data" / "gold" / "statewide_severe_crashes.parquet"
OUT_COUNTY = ROOT / "data" / "gold" / "statewide_county_summary.parquet"
OUT_ROUTE = ROOT / "data" / "gold" / "statewide_route_summary.parquet"
OUT_REPORT = ROOT / "reports" / "phase3b_statewide_explorer.json"


def get_columns(con: duckdb.DuckDBPyConnection, table_name: str) -> set[str]:
    rows = con.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = ?
        """,
        [table_name],
    ).fetchall()
    return {r[0] for r in rows}


def choose_year_expression(cols: set[str]) -> str:
    # Prefer already-derived year fields.
    for candidate in (
        "crash_year",
        "year",
        "analysis_year",
    ):
        if candidate in cols:
            return f"TRY_CAST({candidate} AS INTEGER)"

    # Otherwise derive from a timestamp/date field if available.
    for candidate in (
        "crash_datetime",
        "crash_date",
        "crash_dt",
        "datetime",
        "date",
    ):
        if candidate in cols:
            return f"YEAR(TRY_CAST({candidate} AS TIMESTAMP))"

    return "NULL::INTEGER"


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"Database not found: {DB_PATH}")

    OUT_POINTS.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(DB_PATH))
    try:
        required = {
            row[0]
            for row in con.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_name IN (
                    'silver_crashes',
                    'silver_crash_spatial_lrs'
                )
                """
            ).fetchall()
        }
        missing = {"silver_crashes", "silver_crash_spatial_lrs"} - required
        if missing:
            raise SystemExit(
                "Required tables missing: " + ", ".join(sorted(missing))
            )

        crash_cols = get_columns(con, "silver_crashes")
        year_expr = choose_year_expression(crash_cols)

        # Pull all severe crashes with valid Utah coordinates.
        # Spatially matched route information is used when available.
        sql = f"""
        CREATE OR REPLACE TABLE gold_statewide_severe_crashes AS
        SELECT
            c.crash_id,
            {year_expr} AS crash_year,
            COALESCE(s.county_name, c.county_name) AS county_name,
            COALESCE(s.route_num, TRY_CAST(c.route_key AS INTEGER)) AS route_num,
            COALESCE(s.latitude, c.latitude) AS latitude,
            COALESCE(s.longitude, c.longitude) AS longitude,
            c.severe_crash_flag,
            c.fatal_crash_flag,
            c.speed_related_flag,
            c.dui_flag,
            c.distracted_driving_flag,
            c.roadway_departure_flag,
            CASE
                WHEN s.spatial_match_valid = 1 THEN 1
                ELSE 0
            END AS route_spatial_match_valid
        FROM silver_crashes c
        LEFT JOIN silver_crash_spatial_lrs s
          ON c.crash_id = s.crash_id
        WHERE c.severe_crash_flag = 1
          AND COALESCE(s.latitude, c.latitude) BETWEEN 36.5 AND 42.5
          AND COALESCE(s.longitude, c.longitude) BETWEEN -114.5 AND -108.5
        """

        con.execute(sql)

        # County summary.
        con.execute(
            """
            CREATE OR REPLACE TABLE gold_statewide_county_summary AS
            SELECT
                COALESCE(county_name, 'Unknown') AS county_name,
                COUNT(*) AS severe_crashes,
                SUM(fatal_crash_flag) AS fatal_crashes,
                SUM(speed_related_flag) AS speed_related_crashes,
                SUM(dui_flag) AS dui_crashes,
                SUM(distracted_driving_flag) AS distracted_driving_crashes,
                SUM(roadway_departure_flag) AS roadway_departure_crashes
            FROM gold_statewide_severe_crashes
            GROUP BY COALESCE(county_name, 'Unknown')
            ORDER BY severe_crashes DESC
            """
        )

        # Route summary.
        con.execute(
            """
            CREATE OR REPLACE TABLE gold_statewide_route_summary AS
            SELECT
                route_num,
                COUNT(*) AS severe_crashes,
                SUM(fatal_crash_flag) AS fatal_crashes,
                SUM(speed_related_flag) AS speed_related_crashes,
                SUM(dui_flag) AS dui_crashes,
                SUM(distracted_driving_flag) AS distracted_driving_crashes,
                SUM(roadway_departure_flag) AS roadway_departure_crashes
            FROM gold_statewide_severe_crashes
            WHERE route_num IS NOT NULL
            GROUP BY route_num
            ORDER BY severe_crashes DESC
            """
        )

        for table, path in (
            ("gold_statewide_severe_crashes", OUT_POINTS),
            ("gold_statewide_county_summary", OUT_COUNTY),
            ("gold_statewide_route_summary", OUT_ROUTE),
        ):
            safe = str(path).replace("'", "''")
            con.execute(
                f"COPY {table} TO '{safe}' "
                "(FORMAT PARQUET, COMPRESSION ZSTD)"
            )

        summary = con.execute(
            """
            SELECT
                COUNT(*) AS severe_crashes,
                SUM(fatal_crash_flag) AS fatal_crashes,
                COUNT(DISTINCT county_name) AS counties_represented,
                COUNT(DISTINCT route_num) AS routes_represented,
                SUM(route_spatial_match_valid) AS spatially_matched
            FROM gold_statewide_severe_crashes
            """
        ).fetchdf().iloc[0].to_dict()

        years = con.execute(
            """
            SELECT
                crash_year,
                COUNT(*) AS severe_crashes
            FROM gold_statewide_severe_crashes
            WHERE crash_year IS NOT NULL
            GROUP BY crash_year
            ORDER BY crash_year
            """
        ).fetchdf()

        top_counties = con.execute(
            """
            SELECT *
            FROM gold_statewide_county_summary
            LIMIT 15
            """
        ).fetchdf()

        report = {
            "status": "success",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "summary": {
                k: int(v) if pd.notna(v) else None
                for k, v in summary.items()
            },
            "year_field_detected": year_expr,
            "years": years.to_dict(orient="records"),
            "top_counties": top_counties.to_dict(orient="records"),
            "purpose": (
                "Statewide context dataset for severe-crash exploration. "
                "This dataset is separate from the statistically supported "
                "priority-corridor shortlist."
            ),
        }

        OUT_REPORT.write_text(
            json.dumps(report, indent=2, default=str),
            encoding="utf-8",
        )

        print("\nPHASE 3B STATEWIDE EXPLORER DATA COMPLETE")
        print("=========================================")
        print(f"Severe crashes: {int(summary['severe_crashes']):,}")
        print(f"Fatal crashes: {int(summary['fatal_crashes']):,}")
        print(f"Counties represented: {int(summary['counties_represented']):,}")
        print(f"Routes represented: {int(summary['routes_represented']):,}")
        print(
            f"Spatially matched severe crashes: "
            f"{int(summary['spatially_matched']):,}"
        )

        if not years.empty:
            print("\nSevere crashes by year:")
            print(years.to_string(index=False))
        else:
            print(
                "\nNo usable year field was detected. "
                "The statewide explorer will still work without a year filter."
            )

        print("\nTop counties by severe crashes:")
        print(top_counties.to_string(index=False))

        print(f"\nSaved: {OUT_POINTS.relative_to(ROOT)}")
        print(f"Saved: {OUT_COUNTY.relative_to(ROOT)}")
        print(f"Saved: {OUT_ROUTE.relative_to(ROOT)}")
        print(f"Saved: {OUT_REPORT.relative_to(ROOT)}")

    finally:
        con.close()


if __name__ == "__main__":
    main()
