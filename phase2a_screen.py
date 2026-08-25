from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "warehouse" / "udot_safecorridor.duckdb"
OUT_PARQUET = ROOT / "data" / "gold" / "route_candidates_v2.parquet"
OUT_REPORT = ROOT / "reports" / "phase2a_screening.json"

MIN_SEVERE_CRASHES = 10
MIN_TOTAL_VMT = 50_000_000
MIN_EXPECTED_PEER = 5.0

SQL = f"""
CREATE OR REPLACE TABLE gold_route_candidates_v2 AS
WITH state_route_years AS (
    SELECT *
    FROM gold_segment_risk
    WHERE TRY_CAST(route_key AS INTEGER) BETWEEN 1 AND 999
),
route_rollup AS (
    SELECT
        route_key,
        COUNT(DISTINCT analysis_year) AS analysis_years,
        SUM(crashes) AS crashes,
        SUM(severe_crashes) AS severe_crashes,
        SUM(fatal_crashes) AS fatal_crashes,
        SUM(speed_related_crashes) AS speed_related_crashes,
        SUM(dui_crashes) AS dui_crashes,
        SUM(distracted_crashes) AS distracted_crashes,
        SUM(roadway_departure_crashes) AS roadway_departure_crashes,
        SUM(annual_vmt) AS total_vmt,
        SUM(aadt * section_length) / NULLIF(SUM(section_length), 0) AS weighted_aadt,
        MAX(aadt_proxy_flag) AS uses_aadt_proxy
    FROM state_route_years
    GROUP BY route_key
),
route_miles AS (
    SELECT
        route_key,
        SUM(section_length) AS route_miles
    FROM (
        SELECT DISTINCT route_key, segment_object_id, section_length
        FROM state_route_years
    ) d
    GROUP BY route_key
),
with_features AS (
    SELECT
        r.*,
        m.route_miles,
        r.severe_crashes * 100000000.0 / NULLIF(r.total_vmt, 0) AS severe_rate_per_100m_vmt,
        CASE
            WHEN r.severe_crashes >= {MIN_SEVERE_CRASHES}
             AND r.total_vmt >= {MIN_TOTAL_VMT}
            THEN 1 ELSE 0
        END AS meets_evidence_floor
    FROM route_rollup r
    LEFT JOIN route_miles m USING (route_key)
),
eligible AS (
    SELECT
        *,
        NTILE(4) OVER (ORDER BY weighted_aadt) AS traffic_peer_quartile
    FROM with_features
    WHERE meets_evidence_floor = 1
),
peer_totals AS (
    SELECT
        *,
        SUM(severe_crashes) OVER (PARTITION BY traffic_peer_quartile) AS peer_total_severe,
        SUM(total_vmt) OVER (PARTITION BY traffic_peer_quartile) AS peer_total_vmt,
        COUNT(*) OVER (PARTITION BY traffic_peer_quartile) AS peer_route_count
    FROM eligible
),
peer_adjusted AS (
    SELECT
        *,
        (peer_total_severe - severe_crashes) * 1.0
            / NULLIF(peer_total_vmt - total_vmt, 0) AS leave_one_out_peer_rate,
        ((peer_total_severe - severe_crashes) * 1.0
            / NULLIF(peer_total_vmt - total_vmt, 0)) * total_vmt AS expected_severe_peer
    FROM peer_totals
),
scored AS (
    SELECT
        *,
        severe_crashes / NULLIF(expected_severe_peer, 0) AS peer_observed_expected_ratio,
        severe_crashes - expected_severe_peer AS excess_severe_crashes
    FROM peer_adjusted
)
SELECT
    route_key,
    analysis_years,
    route_miles,
    weighted_aadt,
    total_vmt,
    crashes,
    severe_crashes,
    fatal_crashes,
    speed_related_crashes,
    dui_crashes,
    distracted_crashes,
    roadway_departure_crashes,
    severe_rate_per_100m_vmt,
    traffic_peer_quartile,
    peer_route_count,
    expected_severe_peer,
    peer_observed_expected_ratio,
    excess_severe_crashes,
    uses_aadt_proxy,
    CASE
        WHEN expected_severe_peer < {MIN_EXPECTED_PEER} THEN 'INSUFFICIENT EXPECTED EVENTS'
        WHEN peer_observed_expected_ratio >= 1.50 AND excess_severe_crashes >= 5 THEN 'HIGH'
        WHEN peer_observed_expected_ratio >= 1.25 AND excess_severe_crashes >= 3 THEN 'ELEVATED'
        WHEN peer_observed_expected_ratio >= 1.00 THEN 'MONITOR'
        ELSE 'BASELINE/LOW'
    END AS screening_band_v2
FROM scored
ORDER BY peer_observed_expected_ratio DESC NULLS LAST;
"""


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(
            f"Database not found: {DB_PATH}\n"
            "Keep this file in the project root and make sure the Phase 1 pipeline has already run."
        )

    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(DB_PATH))
    try:
        required = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name='gold_segment_risk'"
        ).fetchone()[0]
        if not required:
            raise SystemExit("gold_segment_risk is missing. Run Phase 1 pipeline first.")

        con.execute(SQL)

        safe_out = str(OUT_PARQUET).replace("'", "''")
        con.execute(
            f"COPY gold_route_candidates_v2 TO '{safe_out}' (FORMAT PARQUET, COMPRESSION ZSTD)"
        )

        summary = con.execute(
            """
            SELECT
                COUNT(*) AS eligible_routes,
                SUM(CASE WHEN screening_band_v2='HIGH' THEN 1 ELSE 0 END) AS high_routes,
                SUM(CASE WHEN screening_band_v2='ELEVATED' THEN 1 ELSE 0 END) AS elevated_routes,
                SUM(CASE WHEN screening_band_v2='MONITOR' THEN 1 ELSE 0 END) AS monitor_routes,
                MIN(analysis_years) AS min_years_present,
                MAX(analysis_years) AS max_years_present
            FROM gold_route_candidates_v2
            """
        ).fetchdf().to_dict(orient="records")[0]

        top = con.execute(
            """
            SELECT
                route_key,
                ROUND(route_miles, 2) AS route_miles,
                ROUND(weighted_aadt, 0) AS weighted_aadt,
                crashes,
                severe_crashes,
                fatal_crashes,
                ROUND(total_vmt / 1000000.0, 1) AS million_vmt,
                ROUND(severe_rate_per_100m_vmt, 2) AS severe_rate_per_100m_vmt,
                traffic_peer_quartile,
                ROUND(expected_severe_peer, 2) AS expected_severe_peer,
                ROUND(peer_observed_expected_ratio, 2) AS peer_oe_ratio,
                ROUND(excess_severe_crashes, 2) AS excess_severe_crashes,
                screening_band_v2
            FROM gold_route_candidates_v2
            WHERE expected_severe_peer >= ?
            ORDER BY peer_observed_expected_ratio DESC NULLS LAST
            LIMIT 20
            """,
            [MIN_EXPECTED_PEER],
        ).fetchdf()

        report = {
            "status": "success",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "method": "Phase 2A peer-adjusted route screening",
            "scope": "Numeric UDOT route keys 1-999 only for the executive candidate screen; other routes are retained in Phase 1 data.",
            "guardrails": {
                "minimum_severe_crashes": MIN_SEVERE_CRASHES,
                "minimum_total_vmt": MIN_TOTAL_VMT,
                "minimum_expected_peer_events_for_band": MIN_EXPECTED_PEER,
            },
            "peer_method": "Eligible routes are split into four traffic-intensity peer groups by exposure-weighted AADT. Expected severe crashes use a leave-one-route-out peer exposure rate so a route does not set its own baseline.",
            "warning": "This is still a screening model, not a causal model or formal safety-performance function. Phase 2B will add roadway characteristics/statistical modeling.",
            "summary": summary,
            "top_candidates": top.to_dict(orient="records"),
        }
        OUT_REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

        print("\nPHASE 2A COMPLETE")
        print("=================")
        print(f"Eligible routes: {summary['eligible_routes']}")
        print(f"HIGH: {summary['high_routes']} | ELEVATED: {summary['elevated_routes']} | MONITOR: {summary['monitor_routes']}")
        print("\nTop candidates (screening only):")
        print(top.to_string(index=False))
        print(f"\nSaved: {OUT_PARQUET.relative_to(ROOT)}")
        print(f"Saved: {OUT_REPORT.relative_to(ROOT)}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
