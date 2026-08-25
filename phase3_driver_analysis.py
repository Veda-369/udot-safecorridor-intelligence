from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "warehouse" / "udot_safecorridor.duckdb"
OUT_PARQUET = ROOT / "data" / "gold" / "corridor_driver_analysis_v1.parquet"
OUT_REPORT = ROOT / "reports" / "phase3_driver_analysis.json"

DRIVER_COLUMNS = {
    "speed_related": "speed_related_flag",
    "dui": "dui_flag",
    "distracted_driving": "distracted_driving_flag",
    "roadway_departure": "roadway_departure_flag",
}


def pct(n: float, d: float) -> float:
    return 100.0 * n / d if d else 0.0


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"Database not found: {DB_PATH}")

    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
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
                    'silver_crash_spatial_lrs',
                    'gold_executive_corridors_v4'
                )
                """
            ).fetchall()
        }
        missing = {
            "silver_crash_spatial_lrs",
            "gold_executive_corridors_v4",
        } - required
        if missing:
            raise SystemExit(
                "Required tables are missing: " + ", ".join(sorted(missing))
            )

        # Statewide baseline among severe crashes that were spatially matched
        # to numeric UDOT routes.
        baseline = con.execute(
            """
            SELECT
                COUNT(*) AS severe_crashes,
                SUM(speed_related_flag) AS speed_related,
                SUM(dui_flag) AS dui,
                SUM(distracted_driving_flag) AS distracted_driving,
                SUM(roadway_departure_flag) AS roadway_departure
            FROM silver_crash_spatial_lrs
            WHERE spatial_match_valid = 1
              AND severe_crash_flag = 1
              AND route_num BETWEEN 1 AND 999
            """
        ).fetchdf().iloc[0].to_dict()

        baseline_total = float(baseline["severe_crashes"] or 0)

        baseline_pct = {
            driver: pct(float(baseline[driver] or 0), baseline_total)
            for driver in DRIVER_COLUMNS
        }

        corridors = con.execute(
            """
            SELECT
                executive_rank,
                route_num,
                route_name,
                corridor_label,
                dominant_county,
                start_mp,
                end_mp,
                severe_crashes,
                fatal_crashes,
                expected_severe,
                oe_ratio,
                excess_severe
            FROM gold_executive_corridors_v4
            ORDER BY executive_rank
            """
        ).fetchdf()

        results = []

        for _, corridor in corridors.iterrows():
            route_num = int(corridor["route_num"])
            start_mp = float(corridor["start_mp"])
            end_mp = float(corridor["end_mp"])

            stats = con.execute(
                """
                SELECT
                    COUNT(*) AS severe_crashes,
                    SUM(speed_related_flag) AS speed_related,
                    SUM(dui_flag) AS dui,
                    SUM(distracted_driving_flag) AS distracted_driving,
                    SUM(roadway_departure_flag) AS roadway_departure
                FROM silver_crash_spatial_lrs
                WHERE spatial_match_valid = 1
                  AND severe_crash_flag = 1
                  AND route_num = ?
                  AND derived_milepoint >= ?
                  AND derived_milepoint < ?
                """,
                [route_num, start_mp, end_mp],
            ).fetchdf().iloc[0].to_dict()

            total = float(stats["severe_crashes"] or 0)

            row = {
                "executive_rank": int(corridor["executive_rank"]),
                "route_num": route_num,
                "route_name": corridor["route_name"],
                "corridor_label": corridor["corridor_label"],
                "dominant_county": corridor["dominant_county"],
                "start_mp": start_mp,
                "end_mp": end_mp,
                "severe_crashes": int(total),
                "fatal_crashes": int(corridor["fatal_crashes"]),
                "expected_severe": float(corridor["expected_severe"]),
                "oe_ratio": float(corridor["oe_ratio"]),
                "excess_severe": float(corridor["excess_severe"]),
            }

            for driver in DRIVER_COLUMNS:
                count = float(stats[driver] or 0)
                corridor_pct = pct(count, total)
                state_pct = baseline_pct[driver]

                row[f"{driver}_count"] = int(count)
                row[f"{driver}_pct"] = corridor_pct
                row[f"{driver}_statewide_pct"] = state_pct
                row[f"{driver}_pp_diff"] = corridor_pct - state_pct
                row[f"{driver}_relative_index"] = (
                    corridor_pct / state_pct if state_pct > 0 else None
                )

            # Identify the two strongest over-represented characteristics.
            diffs = [
                (driver, row[f"{driver}_pp_diff"])
                for driver in DRIVER_COLUMNS
            ]
            diffs.sort(key=lambda x: x[1], reverse=True)

            row["top_driver_1"] = diffs[0][0]
            row["top_driver_1_pp_diff"] = diffs[0][1]
            row["top_driver_2"] = diffs[1][0]
            row["top_driver_2_pp_diff"] = diffs[1][1]

            results.append(row)

        result_df = pd.DataFrame(results)

        con.register("_driver_analysis", result_df)
        con.execute(
            """
            CREATE OR REPLACE TABLE gold_corridor_driver_analysis_v1 AS
            SELECT * FROM _driver_analysis
            """
        )

        safe_out = str(OUT_PARQUET).replace("'", "''")
        con.execute(
            f"COPY gold_corridor_driver_analysis_v1 TO '{safe_out}' "
            "(FORMAT PARQUET, COMPRESSION ZSTD)"
        )

        top_preview = result_df.head(15).copy()

        preview_cols = [
            "executive_rank",
            "corridor_label",
            "severe_crashes",
            "speed_related_pct",
            "speed_related_pp_diff",
            "dui_pct",
            "dui_pp_diff",
            "distracted_driving_pct",
            "distracted_driving_pp_diff",
            "roadway_departure_pct",
            "roadway_departure_pp_diff",
            "top_driver_1",
            "top_driver_1_pp_diff",
        ]

        for col in preview_cols:
            if col in top_preview.columns and pd.api.types.is_numeric_dtype(top_preview[col]):
                top_preview[col] = top_preview[col].round(2)

        report = {
            "status": "success",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "method": (
                "For each statistically supported executive corridor, crash-level "
                "characteristics are calculated among severe crashes and compared "
                "with the statewide severe-crash share among spatially matched "
                "numeric UDOT routes."
            ),
            "statewide_severe_crash_baseline": {
                "severe_crashes": int(baseline_total),
                **{
                    f"{driver}_pct": round(value, 3)
                    for driver, value in baseline_pct.items()
                },
            },
            "important_limitation": (
                "These are descriptive associations, not causal effects. A positive "
                "percentage-point difference means the characteristic is more common "
                "among severe crashes in that corridor than in the statewide severe-"
                "crash baseline. It does not prove the characteristic caused the "
                "elevated corridor risk."
            ),
            "top_corridors_preview": top_preview[preview_cols].to_dict(
                orient="records"
            ),
        }

        OUT_REPORT.write_text(
            json.dumps(report, indent=2, default=str),
            encoding="utf-8",
        )

        print("\nPHASE 3 DRIVER ANALYSIS COMPLETE")
        print("================================")
        print(
            f"Statewide severe-crash baseline: {int(baseline_total):,} crashes"
        )
        print("\nStatewide characteristic shares:")
        for driver, value in baseline_pct.items():
            print(f"  {driver:22s} {value:6.2f}%")

        print("\nTop corridor characteristic comparison")
        print("--------------------------------------")
        print(top_preview[preview_cols].to_string(index=False))

        print(
            "\nInterpretation: positive 'pp_diff' means that characteristic "
            "appears more often among severe crashes in the corridor than in "
            "the statewide severe-crash baseline."
        )
        print(
            "Do not interpret these differences as causal effects."
        )

        print(f"\nSaved: {OUT_PARQUET.relative_to(ROOT)}")
        print(f"Saved: {OUT_REPORT.relative_to(ROOT)}")

    finally:
        con.close()


if __name__ == "__main__":
    main()
