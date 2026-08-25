from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import geopandas as gpd
import numpy as np
import pandas as pd
import requests
import shapely

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "warehouse" / "udot_safecorridor.duckdb"
ROUTES_CACHE = ROOT / "data" / "reference" / "udot_routes.geojson"
MATCH_PARQUET = ROOT / "data" / "silver" / "crash_spatial_lrs.parquet"
OUT_PARQUET = ROOT / "data" / "gold" / "corridor_candidates_spatial_v2.parquet"
OUT_REPORT = ROOT / "reports" / "phase2b_spatial.json"

ROUTES_URL = (
    "https://roads.udot.utah.gov/server/rest/services/"
    "Public/UDOT_Routes/MapServer/0/query"
)

CORRIDOR_MILES = 5
MAX_ROUTE_DISTANCE_M = 150.0
MIN_SEVERE_CRASHES = 3
MIN_TOTAL_VMT = 20_000_000
MIN_EXPECTED_PEER = 2.0


def parse_route_number(row: pd.Series) -> float:
    """Return numeric route number from UDOT route aliases/IDs."""
    for field in ("ROUTE_ALIAS_COMMON", "ROUTE_ID", "SUB_ROUTE_ID"):
        value = row.get(field)
        if value is None or (isinstance(value, float) and math.isnan(value)):
            continue
        s = str(value).strip()

        # Preferred forms: I-15, US-89, SR-126.
        m = re.search(r"(?:^|[^0-9])(\d{1,4})(?:[^0-9]|$)", s)
        if m:
            try:
                n = int(m.group(1))
                if 1 <= n <= 999:
                    return float(n)
            except ValueError:
                pass

        # Fallback for zero-padded UDOT IDs such as 0015P / 0015N.
        m = re.match(r"0*(\d{1,4})", s)
        if m:
            try:
                n = int(m.group(1))
                if 1 <= n <= 999:
                    return float(n)
            except ValueError:
                pass

    return np.nan


def fetch_udot_routes(refresh: bool = False) -> gpd.GeoDataFrame:
    ROUTES_CACHE.parent.mkdir(parents=True, exist_ok=True)

    if ROUTES_CACHE.exists() and not refresh:
        print(f"Using cached UDOT route geometry: {ROUTES_CACHE.relative_to(ROOT)}")
        return gpd.read_file(ROUTES_CACHE)

    print("Downloading official UDOT route geometry (small reference dataset)...")
    params = {
        "where": "ROUTE_TYPE='M' AND CARTO_CODE IN ('1','2','3')",
        "outFields": (
            "OBJECTID,ROUTE_ID,ROUTE_DIRECTION,ROUTE_TYPE,"
            "BEG_MILEAGE,END_MILEAGE,CARTO_CODE,"
            "ROUTE_ALIAS_COMMON,ROUTE_ALIAS_STD_DIR,ROUTE_DESC,SUB_ROUTE_ID"
        ),
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
        "resultRecordCount": "10000",
    }
    response = requests.get(ROUTES_URL, params=params, timeout=120)
    response.raise_for_status()
    payload = response.json()

    if "features" not in payload or not payload["features"]:
        raise RuntimeError(
            "UDOT Routes service returned no features. "
            f"Response keys: {list(payload.keys())}"
        )

    routes = gpd.GeoDataFrame.from_features(payload["features"], crs="EPSG:4326")
    routes["route_num"] = routes.apply(parse_route_number, axis=1)
    routes = routes[routes["route_num"].between(1, 999, inclusive="both")].copy()
    routes["route_num"] = routes["route_num"].astype(int)

    # Save in WGS84 for transparency/reuse.
    routes.to_file(ROUTES_CACHE, driver="GeoJSON")
    print(f"Cached {len(routes):,} route features.")
    return routes


def load_crashes(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute(
        """
        SELECT
            crash_id,
            route_key,
            county_name,
            latitude,
            longitude,
            severe_crash_flag,
            fatal_crash_flag,
            speed_related_flag,
            dui_flag,
            distracted_driving_flag,
            roadway_departure_flag
        FROM silver_crashes
        WHERE TRY_CAST(route_key AS INTEGER) BETWEEN 1 AND 999
          AND latitude BETWEEN 36.5 AND 42.5
          AND longitude BETWEEN -114.5 AND -108.5
        """
    ).fetchdf()


def spatial_linear_reference(
    crashes_df: pd.DataFrame,
    routes_wgs84: gpd.GeoDataFrame,
) -> pd.DataFrame:
    print(f"Spatially referencing {len(crashes_df):,} crash records...")

    crashes = gpd.GeoDataFrame(
        crashes_df.copy(),
        geometry=gpd.points_from_xy(
            crashes_df["longitude"],
            crashes_df["latitude"],
        ),
        crs="EPSG:4326",
    )
    crashes["route_num"] = pd.to_numeric(
        crashes["route_key"], errors="coerce"
    ).astype("Int64")

    # Work in UDOT's native projected CRS so distance is measured in meters.
    crashes = crashes.to_crs("EPSG:26912")
    routes = routes_wgs84.to_crs("EPSG:26912").copy()
    routes = routes.reset_index(drop=True)
    routes["route_feature_index"] = routes.index

    result_parts: list[pd.DataFrame] = []
    route_numbers = sorted(set(crashes["route_num"].dropna().astype(int)))

    for pos, route_num in enumerate(route_numbers, start=1):
        cg = crashes[crashes["route_num"] == route_num].copy()
        rg = routes[routes["route_num"] == route_num].copy()

        if rg.empty:
            temp = pd.DataFrame(cg.drop(columns="geometry"))
            temp["route_name"] = None
            temp["official_begin_mileage"] = np.nan
            temp["official_end_mileage"] = np.nan
            temp["route_distance_m"] = np.nan
            temp["derived_milepoint"] = np.nan
            temp["spatial_match_valid"] = 0
            result_parts.append(temp)
            continue

        right = rg[
            [
                "route_feature_index",
                "ROUTE_ALIAS_COMMON",
                "BEG_MILEAGE",
                "END_MILEAGE",
                "geometry",
            ]
        ].rename(
            columns={
                "ROUTE_ALIAS_COMMON": "route_name",
                "BEG_MILEAGE": "official_begin_mileage",
                "END_MILEAGE": "official_end_mileage",
            }
        )

        joined = gpd.sjoin_nearest(
            cg,
            right,
            how="left",
            max_distance=1000.0,
            distance_col="route_distance_m",
        )

        # Parallel directions can occasionally tie. Keep the nearest single feature.
        joined = (
            joined.reset_index()
            .rename(columns={"index": "_crash_row_index"})
            .sort_values(
                ["_crash_row_index", "route_distance_m"],
                na_position="last",
            )
            .drop_duplicates("_crash_row_index", keep="first")
        )

        valid_right = joined["route_feature_index"].notna()
        joined["derived_milepoint"] = np.nan

        if valid_right.any():
            right_ids = joined.loc[valid_right, "route_feature_index"].astype(int)
            line_geoms = routes.loc[right_ids, "geometry"].array
            point_geoms = joined.loc[valid_right, "geometry"].array

            fractions = shapely.line_locate_point(
                line_geoms,
                point_geoms,
                normalized=True,
            )
            beg = pd.to_numeric(
                joined.loc[valid_right, "official_begin_mileage"],
                errors="coerce",
            ).to_numpy()
            end = pd.to_numeric(
                joined.loc[valid_right, "official_end_mileage"],
                errors="coerce",
            ).to_numpy()

            joined.loc[valid_right, "derived_milepoint"] = (
                beg + fractions * (end - beg)
            )

        joined["spatial_match_valid"] = (
            joined["route_distance_m"].notna()
            & (joined["route_distance_m"] <= MAX_ROUTE_DISTANCE_M)
            & joined["derived_milepoint"].notna()
        ).astype(int)

        keep_cols = [
            "crash_id",
            "route_key",
            "route_num",
            "county_name",
            "latitude",
            "longitude",
            "severe_crash_flag",
            "fatal_crash_flag",
            "speed_related_flag",
            "dui_flag",
            "distracted_driving_flag",
            "roadway_departure_flag",
            "route_name",
            "official_begin_mileage",
            "official_end_mileage",
            "route_distance_m",
            "derived_milepoint",
            "spatial_match_valid",
        ]
        result_parts.append(pd.DataFrame(joined[keep_cols]))

        if pos % 25 == 0 or pos == len(route_numbers):
            print(f"  routes processed: {pos}/{len(route_numbers)}")

    result = pd.concat(result_parts, ignore_index=True)
    return result


CORRIDOR_SQL = f"""
CREATE OR REPLACE TABLE gold_corridor_candidates_spatial_v2 AS
WITH aadt_state AS (
    SELECT
        route_key,
        analysis_year,
        aadt,
        LEAST(begin_point, end_point) AS lo_mp,
        GREATEST(begin_point, end_point) AS hi_mp
    FROM silver_aadt_analysis
    WHERE TRY_CAST(route_key AS INTEGER) BETWEEN 1 AND 999
      AND aadt > 0
      AND begin_point IS NOT NULL
      AND end_point IS NOT NULL
),
aadt_expanded AS (
    SELECT
        a.route_key,
        a.analysis_year,
        a.aadt,
        bin_idx,
        bin_idx * {CORRIDOR_MILES}.0 AS corridor_start_mp,
        (bin_idx + 1) * {CORRIDOR_MILES}.0 AS corridor_end_mp,
        GREATEST(
            0.0,
            LEAST(a.hi_mp, (bin_idx + 1) * {CORRIDOR_MILES}.0)
              - GREATEST(a.lo_mp, bin_idx * {CORRIDOR_MILES}.0)
        ) AS overlap_miles
    FROM aadt_state a,
    UNNEST(
        range(
            CAST(FLOOR(a.lo_mp / {CORRIDOR_MILES}.0) AS INTEGER),
            CAST(FLOOR(a.hi_mp / {CORRIDOR_MILES}.0) AS INTEGER) + 1
        )
    ) AS t(bin_idx)
),
corridor_exposure_year AS (
    SELECT
        route_key,
        analysis_year,
        corridor_start_mp,
        corridor_end_mp,
        SUM(overlap_miles) AS covered_miles,
        SUM(aadt * overlap_miles) / NULLIF(SUM(overlap_miles), 0) AS weighted_aadt,
        SUM(aadt * overlap_miles * 365.25) AS annual_vmt
    FROM aadt_expanded
    WHERE overlap_miles > 0
    GROUP BY route_key, analysis_year, corridor_start_mp, corridor_end_mp
),
corridor_exposure AS (
    SELECT
        route_key,
        corridor_start_mp,
        corridor_end_mp,
        COUNT(DISTINCT analysis_year) AS analysis_years,
        AVG(covered_miles) AS corridor_miles_covered,
        SUM(weighted_aadt * annual_vmt) / NULLIF(SUM(annual_vmt), 0) AS weighted_aadt,
        SUM(annual_vmt) AS total_vmt
    FROM corridor_exposure_year
    GROUP BY route_key, corridor_start_mp, corridor_end_mp
),
crash_bins AS (
    SELECT
        CAST(route_num AS VARCHAR) AS route_key,
        FLOOR(derived_milepoint / {CORRIDOR_MILES}.0)
            * {CORRIDOR_MILES}.0 AS corridor_start_mp,
        COUNT(*) AS crashes,
        SUM(severe_crash_flag) AS severe_crashes,
        SUM(fatal_crash_flag) AS fatal_crashes,
        SUM(speed_related_flag) AS speed_related_crashes,
        SUM(dui_flag) AS dui_crashes,
        SUM(distracted_driving_flag) AS distracted_driving_crashes,
        SUM(roadway_departure_flag) AS roadway_departure_crashes,
        MEDIAN(route_distance_m) AS median_snap_distance_m
    FROM silver_crash_spatial_lrs
    WHERE spatial_match_valid = 1
    GROUP BY
        CAST(route_num AS VARCHAR),
        FLOOR(derived_milepoint / {CORRIDOR_MILES}.0)
),
combined AS (
    SELECT
        e.route_key,
        e.corridor_start_mp,
        e.corridor_end_mp,
        e.analysis_years,
        e.corridor_miles_covered,
        e.weighted_aadt,
        e.total_vmt,
        COALESCE(c.crashes, 0) AS crashes,
        COALESCE(c.severe_crashes, 0) AS severe_crashes,
        COALESCE(c.fatal_crashes, 0) AS fatal_crashes,
        COALESCE(c.speed_related_crashes, 0) AS speed_related_crashes,
        COALESCE(c.dui_crashes, 0) AS dui_crashes,
        COALESCE(c.distracted_driving_crashes, 0) AS distracted_driving_crashes,
        COALESCE(c.roadway_departure_crashes, 0) AS roadway_departure_crashes,
        c.median_snap_distance_m
    FROM corridor_exposure e
    LEFT JOIN crash_bins c
      ON e.route_key = c.route_key
     AND e.corridor_start_mp = c.corridor_start_mp
),
features AS (
    SELECT
        *,
        severe_crashes * 100000000.0
          / NULLIF(total_vmt, 0) AS severe_rate_per_100m_vmt
    FROM combined
    WHERE severe_crashes >= {MIN_SEVERE_CRASHES}
      AND total_vmt >= {MIN_TOTAL_VMT}
),
eligible AS (
    SELECT
        *,
        NTILE(4) OVER (ORDER BY weighted_aadt) AS traffic_peer_quartile
    FROM features
),
peer_totals AS (
    SELECT
        *,
        SUM(severe_crashes) OVER (
            PARTITION BY traffic_peer_quartile
        ) AS peer_total_severe,
        SUM(total_vmt) OVER (
            PARTITION BY traffic_peer_quartile
        ) AS peer_total_vmt,
        COUNT(*) OVER (
            PARTITION BY traffic_peer_quartile
        ) AS peer_corridor_count
    FROM eligible
),
scored AS (
    SELECT
        *,
        (peer_total_severe - severe_crashes) * 1.0
          / NULLIF(peer_total_vmt - total_vmt, 0) AS leave_one_out_peer_rate,
        ((peer_total_severe - severe_crashes) * 1.0
          / NULLIF(peer_total_vmt - total_vmt, 0))
          * total_vmt AS expected_severe_peer
    FROM peer_totals
)
SELECT
    route_key,
    corridor_start_mp,
    corridor_end_mp,
    analysis_years,
    corridor_miles_covered,
    weighted_aadt,
    total_vmt,
    crashes,
    severe_crashes,
    fatal_crashes,
    speed_related_crashes,
    dui_crashes,
    distracted_driving_crashes,
    roadway_departure_crashes,
    median_snap_distance_m,
    severe_rate_per_100m_vmt,
    traffic_peer_quartile,
    peer_corridor_count,
    expected_severe_peer,
    severe_crashes / NULLIF(expected_severe_peer, 0) AS peer_oe_ratio,
    severe_crashes - expected_severe_peer AS excess_severe_crashes,
    CASE
        WHEN expected_severe_peer < {MIN_EXPECTED_PEER}
            THEN 'INSUFFICIENT EXPECTED EVENTS'
        WHEN severe_crashes / NULLIF(expected_severe_peer, 0) >= 1.75
             AND severe_crashes - expected_severe_peer >= 3
            THEN 'HIGH'
        WHEN severe_crashes / NULLIF(expected_severe_peer, 0) >= 1.35
             AND severe_crashes - expected_severe_peer >= 2
            THEN 'ELEVATED'
        WHEN severe_crashes / NULLIF(expected_severe_peer, 0) >= 1.00
            THEN 'MONITOR'
        ELSE 'BASELINE/LOW'
    END AS screening_band_v2
FROM scored
ORDER BY peer_oe_ratio DESC NULLS LAST;
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--refresh-routes",
        action="store_true",
        help="Redownload the small official UDOT route geometry reference file.",
    )
    args = parser.parse_args()

    if not DB_PATH.exists():
        raise SystemExit(f"Database not found: {DB_PATH}")

    MATCH_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(DB_PATH))
    try:
        crashes_df = load_crashes(con)
        routes = fetch_udot_routes(refresh=args.refresh_routes)

        matched = spatial_linear_reference(crashes_df, routes)

        eligible = len(matched)
        valid = int(matched["spatial_match_valid"].sum())
        match_rate = 100.0 * valid / eligible if eligible else 0.0
        median_distance = float(
            matched.loc[
                matched["spatial_match_valid"] == 1,
                "route_distance_m",
            ].median()
        )

        print("\nSpatial route matching quality")
        print("------------------------------")
        print(f"Eligible numeric-route crashes: {eligible:,}")
        print(f"Matched within {MAX_ROUTE_DISTANCE_M:.0f} m: {valid:,}")
        print(f"Spatial match rate: {match_rate:.2f}%")
        print(f"Median snap distance: {median_distance:.1f} m")

        # Store a compact spatial-LRS table in DuckDB and local Parquet.
        con.register("_spatial_matches", matched)
        con.execute(
            """
            CREATE OR REPLACE TABLE silver_crash_spatial_lrs AS
            SELECT * FROM _spatial_matches
            """
        )
        safe_match = str(MATCH_PARQUET).replace("'", "''")
        con.execute(
            f"COPY silver_crash_spatial_lrs TO '{safe_match}' "
            "(FORMAT PARQUET, COMPRESSION ZSTD)"
        )

        con.execute(CORRIDOR_SQL)
        safe_out = str(OUT_PARQUET).replace("'", "''")
        con.execute(
            f"COPY gold_corridor_candidates_spatial_v2 TO '{safe_out}' "
            "(FORMAT PARQUET, COMPRESSION ZSTD)"
        )

        # Critical validation: I-15 MP 0–5 should now be geographically coherent.
        i15_check = con.execute(
            """
            SELECT
                county_name,
                COUNT(*) AS crashes
            FROM silver_crash_spatial_lrs
            WHERE route_num = 15
              AND spatial_match_valid = 1
              AND derived_milepoint BETWEEN 0 AND 5
            GROUP BY county_name
            ORDER BY crashes DESC
            """
        ).fetchdf()

        top = con.execute(
            """
            SELECT
                route_key,
                ROUND(corridor_start_mp, 1) AS start_mp,
                ROUND(corridor_end_mp, 1) AS end_mp,
                ROUND(corridor_miles_covered, 2) AS covered_miles,
                ROUND(weighted_aadt, 0) AS weighted_aadt,
                crashes,
                severe_crashes,
                fatal_crashes,
                ROUND(total_vmt / 1000000.0, 1) AS million_vmt,
                ROUND(severe_rate_per_100m_vmt, 2) AS severe_rate,
                ROUND(expected_severe_peer, 2) AS expected,
                ROUND(peer_oe_ratio, 2) AS oe_ratio,
                ROUND(excess_severe_crashes, 2) AS excess_severe,
                ROUND(median_snap_distance_m, 1) AS median_snap_m,
                screening_band_v2
            FROM gold_corridor_candidates_spatial_v2
            WHERE expected_severe_peer >= ?
            ORDER BY peer_oe_ratio DESC NULLS LAST
            LIMIT 25
            """,
            [MIN_EXPECTED_PEER],
        ).fetchdf()

        summary = con.execute(
            """
            SELECT
                COUNT(*) AS eligible_corridors,
                SUM(screening_band_v2='HIGH') AS high_corridors,
                SUM(screening_band_v2='ELEVATED') AS elevated_corridors,
                SUM(screening_band_v2='MONITOR') AS monitor_corridors
            FROM gold_corridor_candidates_spatial_v2
            """
        ).fetchdf().to_dict(orient="records")[0]

        report = {
            "status": "success",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "method": (
                "Spatial linear referencing against official UDOT Routes geometry; "
                f"{CORRIDOR_MILES}-mile analytical bins."
            ),
            "spatial_match": {
                "eligible_crashes": eligible,
                "valid_matches": valid,
                "max_route_distance_m": MAX_ROUTE_DISTANCE_M,
                "match_rate_pct": match_rate,
                "median_snap_distance_m": median_distance,
            },
            "i15_mp_0_5_counties": i15_check.to_dict(orient="records"),
            "summary": summary,
            "top_corridors": top.to_dict(orient="records"),
            "warning": (
                "This remains a screening model. Five-mile bins are analytical "
                "units, not official UDOT project limits. Phase 2C will add "
                "formal uncertainty/statistical validation."
            ),
        }
        OUT_REPORT.write_text(
            json.dumps(report, indent=2, default=str),
            encoding="utf-8",
        )

        print("\nI-15 derived MP 0–5 geography check")
        print("-----------------------------------")
        print(i15_check.to_string(index=False) if not i15_check.empty else "No matched crashes")

        print("\nTop spatially referenced 5-mile corridor candidates")
        print("----------------------------------------------------")
        print(top.to_string(index=False))

        print(f"\nSaved: {MATCH_PARQUET.relative_to(ROOT)}")
        print(f"Saved: {OUT_PARQUET.relative_to(ROOT)}")
        print(f"Saved: {OUT_REPORT.relative_to(ROOT)}")

        if match_rate < 90.0:
            print(
                "\nWARNING: spatial match rate is below 90%. "
                "Do not publish corridor rankings yet."
            )
    finally:
        con.close()


if __name__ == "__main__":
    main()
