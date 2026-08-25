from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy.stats import chi2, poisson

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "warehouse" / "udot_safecorridor.duckdb"
ROUTES_CACHE = ROOT / "data" / "reference" / "udot_routes.geojson"
OUT_PARQUET = ROOT / "data" / "gold" / "executive_corridors_v4.parquet"
OUT_REPORT = ROOT / "reports" / "phase2d_executive_corridors.json"

ALPHA = 0.05
FDR_ALPHA = 0.05
MAX_EXECUTIVE_ROWS = 15


def poisson_oe_ci(observed: float, expected: float, alpha: float = 0.05) -> tuple[float, float]:
    if expected <= 0:
        return (math.nan, math.nan)

    if observed > 0:
        lower_count = 0.5 * chi2.ppf(alpha / 2.0, 2.0 * observed)
    else:
        lower_count = 0.0

    upper_count = 0.5 * chi2.ppf(
        1.0 - alpha / 2.0,
        2.0 * (observed + 1.0),
    )
    return (lower_count / expected, upper_count / expected)


def bh_fdr(p_values: np.ndarray) -> np.ndarray:
    p = np.asarray(p_values, dtype=float)
    n = len(p)
    if n == 0:
        return np.array([], dtype=float)

    order = np.argsort(p)
    ranked = p[order]
    adjusted_ranked = ranked * n / np.arange(1, n + 1)
    adjusted_ranked = np.minimum.accumulate(adjusted_ranked[::-1])[::-1]
    adjusted_ranked = np.clip(adjusted_ranked, 0.0, 1.0)

    adjusted = np.empty(n, dtype=float)
    adjusted[order] = adjusted_ranked
    return adjusted


def parse_route_num_from_props(props: dict) -> int | None:
    for field in ("ROUTE_ALIAS_COMMON", "ROUTE_ID", "SUB_ROUTE_ID"):
        value = props.get(field)
        if value is None:
            continue
        s = str(value).strip()

        m = re.search(r"(?:^|[^0-9])(\d{1,4})(?:[^0-9]|$)", s)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 999:
                return n

        m = re.match(r"0*(\d{1,4})", s)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 999:
                return n
    return None


def load_route_aliases() -> dict[int, str]:
    aliases: dict[int, list[str]] = defaultdict(list)
    if not ROUTES_CACHE.exists():
        return {}

    payload = json.loads(ROUTES_CACHE.read_text(encoding="utf-8"))
    for feature in payload.get("features", []):
        props = feature.get("properties", {}) or {}
        route_num = parse_route_num_from_props(props)
        alias = props.get("ROUTE_ALIAS_COMMON")
        if route_num is not None and alias:
            aliases[route_num].append(str(alias).strip())

    out: dict[int, str] = {}
    for route_num, vals in aliases.items():
        cleaned = [v for v in vals if v]
        if cleaned:
            out[route_num] = Counter(cleaned).most_common(1)[0][0]
    return out


def merge_contiguous_bins(df: pd.DataFrame) -> list[dict]:
    """Merge adjacent statistically supported 5-mile bins on the same route.

    This is a presentation consolidation step, not an independent discovery test.
    """
    df = df.copy()
    df["route_num"] = pd.to_numeric(df["route_key"], errors="coerce").astype("Int64")
    df = df.dropna(subset=["route_num", "corridor_start_mp", "corridor_end_mp"])
    df = df.sort_values(["route_num", "corridor_start_mp", "corridor_end_mp"])

    clusters: list[dict] = []

    for route_num, group in df.groupby("route_num", sort=True):
        current: list[pd.Series] = []
        current_end: float | None = None

        for _, row in group.iterrows():
            start = float(row["corridor_start_mp"])
            end = float(row["corridor_end_mp"])

            if not current:
                current = [row]
                current_end = end
                continue

            # Merge only directly touching/overlapping analytical bins.
            if start <= float(current_end) + 1e-9:
                current.append(row)
                current_end = max(float(current_end), end)
            else:
                clusters.append(_aggregate_cluster(int(route_num), current))
                current = [row]
                current_end = end

        if current:
            clusters.append(_aggregate_cluster(int(route_num), current))

    return clusters


def _aggregate_cluster(route_num: int, rows: list[pd.Series]) -> dict:
    frame = pd.DataFrame(rows)

    observed = float(frame["severe_crashes"].sum())
    expected = float(frame["expected_severe_peer"].sum())
    excess = observed - expected
    oe = observed / expected if expected > 0 else math.nan
    ci_low, ci_high = poisson_oe_ci(observed, expected, ALPHA)
    p_value = float(poisson.sf(observed - 1.0, expected)) if expected > 0 else math.nan

    return {
        "route_num": route_num,
        "start_mp": float(frame["corridor_start_mp"].min()),
        "end_mp": float(frame["corridor_end_mp"].max()),
        "source_bins": int(len(frame)),
        "crashes": int(frame["crashes"].sum()),
        "severe_crashes": int(observed),
        "fatal_crashes": int(frame["fatal_crashes"].sum()),
        "million_vmt": float(frame["total_vmt"].sum()) / 1_000_000.0,
        "expected_severe": expected,
        "oe_ratio": oe,
        "ci95_low": ci_low,
        "ci95_high": ci_high,
        "excess_severe": excess,
        "p_value": p_value,
    }


def add_geographic_context(
    con: duckdb.DuckDBPyConnection,
    clusters: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for _, r in clusters.iterrows():
        route_num = int(r["route_num"])
        start_mp = float(r["start_mp"])
        end_mp = float(r["end_mp"])

        geo = con.execute(
            """
            WITH corridor_crashes AS (
                SELECT
                    county_name,
                    latitude,
                    longitude,
                    severe_crash_flag
                FROM silver_crash_spatial_lrs
                WHERE route_num = ?
                  AND spatial_match_valid = 1
                  AND derived_milepoint >= ?
                  AND derived_milepoint < ?
            ),
            county_counts AS (
                SELECT
                    county_name,
                    COUNT(*) AS n
                FROM corridor_crashes
                WHERE county_name IS NOT NULL
                GROUP BY county_name
                ORDER BY n DESC
            )
            SELECT
                (SELECT county_name FROM county_counts LIMIT 1) AS dominant_county,
                (SELECT n FROM county_counts LIMIT 1) AS dominant_county_crashes,
                MEDIAN(CASE WHEN severe_crash_flag = 1 THEN latitude END) AS severe_center_lat,
                MEDIAN(CASE WHEN severe_crash_flag = 1 THEN longitude END) AS severe_center_lon
            FROM corridor_crashes
            """,
            [route_num, start_mp, end_mp],
        ).fetchdf()

        if geo.empty:
            rows.append(
                {
                    "dominant_county": None,
                    "dominant_county_crashes": None,
                    "severe_center_lat": None,
                    "severe_center_lon": None,
                }
            )
        else:
            rows.append(geo.iloc[0].to_dict())

    geo_df = pd.DataFrame(rows)
    return pd.concat([clusters.reset_index(drop=True), geo_df], axis=1)


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"Database not found: {DB_PATH}")

    OUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(DB_PATH))
    try:
        table_exists = con.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_name = 'gold_corridor_candidates_statistical_v3'
            """
        ).fetchone()[0]

        if not table_exists:
            raise SystemExit(
                "gold_corridor_candidates_statistical_v3 not found. "
                "Run phase2c_statistical.py first."
            )

        bins = con.execute(
            """
            SELECT *
            FROM gold_corridor_candidates_statistical_v3
            WHERE evidence_band_v3 IN ('PRIORITY SIGNAL', 'ELEVATED SIGNAL')
            ORDER BY TRY_CAST(route_key AS INTEGER), corridor_start_mp
            """
        ).fetchdf()

        if bins.empty:
            raise SystemExit("No statistically supported bins available to consolidate.")

        clusters = pd.DataFrame(merge_contiguous_bins(bins))
        clusters["q_value_bh"] = bh_fdr(clusters["p_value"].to_numpy(dtype=float))
        clusters["statistically_supported_after_merge"] = (
            (clusters["q_value_bh"] <= FDR_ALPHA)
            & (clusters["ci95_low"] > 1.0)
        )

        # Keep only merged corridors that remain statistically supported.
        clusters = clusters.loc[
            clusters["statistically_supported_after_merge"]
        ].copy()

        clusters = add_geographic_context(con, clusters)

        aliases = load_route_aliases()
        clusters["route_name"] = clusters["route_num"].map(aliases)
        clusters["route_name"] = clusters.apply(
            lambda r: (
                r["route_name"]
                if isinstance(r["route_name"], str) and r["route_name"].strip()
                else f"Route {int(r['route_num'])}"
            ),
            axis=1,
        )

        clusters["corridor_label"] = clusters.apply(
            lambda r: (
                f"{r['route_name']} | MP {r['start_mp']:.0f}-{r['end_mp']:.0f}"
                + (
                    f" | {r['dominant_county']} County"
                    if isinstance(r["dominant_county"], str)
                    and r["dominant_county"].strip()
                    else ""
                )
            ),
            axis=1,
        )

        # Executive priority: excess burden first, then relative elevation.
        clusters = clusters.sort_values(
            ["excess_severe", "oe_ratio"],
            ascending=[False, False],
        ).reset_index(drop=True)
        clusters["executive_rank"] = np.arange(1, len(clusters) + 1)

        # Persist full supported cluster table.
        con.register("_phase2d_clusters", clusters)
        con.execute(
            """
            CREATE OR REPLACE TABLE gold_executive_corridors_v4 AS
            SELECT * FROM _phase2d_clusters
            """
        )

        safe_out = str(OUT_PARQUET).replace("'", "''")
        con.execute(
            f"COPY gold_executive_corridors_v4 TO '{safe_out}' "
            "(FORMAT PARQUET, COMPRESSION ZSTD)"
        )

        display_cols = [
            "executive_rank",
            "corridor_label",
            "source_bins",
            "crashes",
            "severe_crashes",
            "fatal_crashes",
            "million_vmt",
            "expected_severe",
            "oe_ratio",
            "ci95_low",
            "ci95_high",
            "excess_severe",
            "q_value_bh",
            "severe_center_lat",
            "severe_center_lon",
        ]
        top = clusters.head(MAX_EXECUTIVE_ROWS)[display_cols].copy()

        for col in [
            "million_vmt",
            "expected_severe",
            "oe_ratio",
            "ci95_low",
            "ci95_high",
            "excess_severe",
            "q_value_bh",
            "severe_center_lat",
            "severe_center_lon",
        ]:
            top[col] = pd.to_numeric(top[col], errors="coerce").round(4)

        report = {
            "status": "success",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "method": {
                "purpose": (
                    "Consolidate adjacent statistically supported 5-mile bins into "
                    "human-readable executive corridor clusters."
                ),
                "important_note": (
                    "This is a presentation consolidation step. The underlying "
                    "Phase 2C bin-level tests remain the analytical evidence base."
                ),
                "rerun_after_merge": (
                    "Poisson O/E interval and BH-FDR were recomputed on the merged "
                    "corridor totals as a robustness check."
                ),
                "ranking": (
                    "Executive ranking prioritizes excess severe-crash burden, "
                    "then observed/expected ratio."
                ),
            },
            "supported_bins_before_merge": int(len(bins)),
            "supported_corridors_after_merge": int(len(clusters)),
            "top_executive_corridors": top.to_dict(orient="records"),
        }
        OUT_REPORT.write_text(
            json.dumps(report, indent=2, default=str),
            encoding="utf-8",
        )

        print("\nPHASE 2D COMPLETE")
        print("=================")
        print(f"Supported 5-mile bins before consolidation: {len(bins)}")
        print(f"Supported corridor clusters after consolidation: {len(clusters)}")

        print("\nTop executive corridor clusters")
        print("-------------------------------")
        print(top.to_string(index=False))

        print(
            "\nImportant: merging is for executive presentation. "
            "Phase 2C bin-level results remain the analytical evidence base."
        )
        print(f"\nSaved: {OUT_PARQUET.relative_to(ROOT)}")
        print(f"Saved: {OUT_REPORT.relative_to(ROOT)}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
