from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy.stats import chi2, poisson

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "warehouse" / "udot_safecorridor.duckdb"
OUT_PARQUET = ROOT / "data" / "gold" / "corridor_candidates_statistical_v3.parquet"
OUT_REPORT = ROOT / "reports" / "phase2c_statistical_validation.json"

ALPHA = 0.05
FDR_ALPHA = 0.05
MIN_EXPECTED = 2.0
MIN_EXCESS = 3.0


def poisson_oe_ci(observed: np.ndarray, expected: np.ndarray, alpha: float = 0.05):
    """Exact Poisson CI for the standardized observed/expected ratio.

    Expected values are treated as fixed offsets. This interval therefore
    does not include uncertainty from estimating the peer baseline itself.
    """
    observed = observed.astype(float)
    expected = expected.astype(float)

    lower_counts = np.where(
        observed > 0,
        0.5 * chi2.ppf(alpha / 2.0, 2.0 * observed),
        0.0,
    )
    upper_counts = 0.5 * chi2.ppf(
        1.0 - alpha / 2.0,
        2.0 * (observed + 1.0),
    )

    lower_ratio = lower_counts / expected
    upper_ratio = upper_counts / expected
    return lower_ratio, upper_ratio


def bh_fdr(p_values: np.ndarray) -> np.ndarray:
    """Benjamini-Hochberg adjusted p-values."""
    p = np.asarray(p_values, dtype=float)
    n = len(p)
    order = np.argsort(p)
    ranked = p[order]

    adjusted_ranked = ranked * n / np.arange(1, n + 1)
    adjusted_ranked = np.minimum.accumulate(adjusted_ranked[::-1])[::-1]
    adjusted_ranked = np.clip(adjusted_ranked, 0.0, 1.0)

    adjusted = np.empty(n, dtype=float)
    adjusted[order] = adjusted_ranked
    return adjusted


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
            WHERE table_name = 'gold_corridor_candidates_spatial_v2'
            """
        ).fetchone()[0]

        if not table_exists:
            raise SystemExit(
                "gold_corridor_candidates_spatial_v2 not found. "
                "Run phase2b_spatial.py first."
            )

        df = con.execute(
            """
            SELECT *
            FROM gold_corridor_candidates_spatial_v2
            WHERE expected_severe_peer >= ?
              AND severe_crashes >= 1
            """,
            [MIN_EXPECTED],
        ).fetchdf()

        if df.empty:
            raise SystemExit("No eligible corridors found for statistical validation.")

        obs = df["severe_crashes"].to_numpy(dtype=float)
        exp = df["expected_severe_peer"].to_numpy(dtype=float)

        # One-sided exceedance p-value:
        # Under H0, observed severe crashes follow Poisson(expected).
        p_values = poisson.sf(obs - 1.0, exp)

        ci_low, ci_high = poisson_oe_ci(obs, exp, ALPHA)
        q_values = bh_fdr(p_values)

        df["oe_ci95_low"] = ci_low
        df["oe_ci95_high"] = ci_high
        df["p_value_excess"] = p_values
        df["q_value_bh"] = q_values
        df["statistically_elevated_fdr05"] = (
            (df["q_value_bh"] <= FDR_ALPHA)
            & (df["oe_ci95_low"] > 1.0)
        )

        # Executive screening: statistical credibility + meaningful absolute burden.
        df["evidence_band_v3"] = np.select(
            [
                (
                    df["statistically_elevated_fdr05"]
                    & (df["excess_severe_crashes"] >= 10)
                ),
                (
                    df["statistically_elevated_fdr05"]
                    & (df["excess_severe_crashes"] >= MIN_EXCESS)
                ),
                (
                    (df["peer_oe_ratio"] > 1.0)
                    & (df["oe_ci95_low"] <= 1.0)
                ),
            ],
            [
                "PRIORITY SIGNAL",
                "ELEVATED SIGNAL",
                "UNCERTAIN",
            ],
            default="NO ELEVATION SIGNAL",
        )

        # For an executive shortlist, prioritize statistically credible excess burden,
        # then relative elevation. This avoids promoting tiny corridors solely because
        # their relative ratio is extreme.
        df["executive_rank"] = np.nan
        shortlist_mask = df["evidence_band_v3"].isin(
            ["PRIORITY SIGNAL", "ELEVATED SIGNAL"]
        )
        shortlist = df.loc[shortlist_mask].copy()
        shortlist = shortlist.sort_values(
            ["excess_severe_crashes", "peer_oe_ratio"],
            ascending=[False, False],
        )
        df.loc[shortlist.index, "executive_rank"] = np.arange(1, len(shortlist) + 1)

        # Persist to DuckDB.
        con.register("_phase2c_df", df)
        con.execute(
            """
            CREATE OR REPLACE TABLE gold_corridor_candidates_statistical_v3 AS
            SELECT * FROM _phase2c_df
            """
        )

        safe_out = str(OUT_PARQUET).replace("'", "''")
        con.execute(
            f"COPY gold_corridor_candidates_statistical_v3 TO '{safe_out}' "
            "(FORMAT PARQUET, COMPRESSION ZSTD)"
        )

        summary = {
            "corridors_tested": int(len(df)),
            "priority_signal": int((df["evidence_band_v3"] == "PRIORITY SIGNAL").sum()),
            "elevated_signal": int((df["evidence_band_v3"] == "ELEVATED SIGNAL").sum()),
            "uncertain": int((df["evidence_band_v3"] == "UNCERTAIN").sum()),
            "no_elevation_signal": int((df["evidence_band_v3"] == "NO ELEVATION SIGNAL").sum()),
        }

        top = df.loc[shortlist_mask].sort_values(
            ["excess_severe_crashes", "peer_oe_ratio"],
            ascending=[False, False],
        ).head(25)

        display_cols = [
            "executive_rank",
            "route_key",
            "corridor_start_mp",
            "corridor_end_mp",
            "crashes",
            "severe_crashes",
            "fatal_crashes",
            "total_vmt",
            "expected_severe_peer",
            "peer_oe_ratio",
            "oe_ci95_low",
            "oe_ci95_high",
            "excess_severe_crashes",
            "q_value_bh",
            "evidence_band_v3",
        ]
        top_display = top[display_cols].copy()
        top_display["total_vmt"] = top_display["total_vmt"] / 1_000_000.0

        rename = {
            "executive_rank": "rank",
            "corridor_start_mp": "start_mp",
            "corridor_end_mp": "end_mp",
            "total_vmt": "million_vmt",
            "expected_severe_peer": "expected",
            "peer_oe_ratio": "oe_ratio",
            "oe_ci95_low": "ci95_low",
            "oe_ci95_high": "ci95_high",
            "excess_severe_crashes": "excess_severe",
            "q_value_bh": "q_value",
        }
        top_display = top_display.rename(columns=rename)

        round_cols = [
            "start_mp",
            "end_mp",
            "million_vmt",
            "expected",
            "oe_ratio",
            "ci95_low",
            "ci95_high",
            "excess_severe",
            "q_value",
        ]
        for col in round_cols:
            top_display[col] = pd.to_numeric(
                top_display[col], errors="coerce"
            ).round(3)

        report = {
            "status": "success",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "method": {
                "observed_model": (
                    "Poisson exceedance test using the Phase 2B peer-expected severe "
                    "crash count as a fixed expected value."
                ),
                "confidence_interval": (
                    "Exact 95% Poisson confidence interval for observed/expected ratio."
                ),
                "multiple_testing": (
                    "Benjamini-Hochberg false discovery rate correction at q <= 0.05."
                ),
                "executive_shortlist": (
                    "Requires FDR-adjusted statistical elevation and lower 95% O/E "
                    "confidence bound > 1. Rankings prioritize excess severe crash "
                    "burden, then O/E ratio."
                ),
            },
            "important_limitation": (
                "The expected counts come from peer-group rates estimated from the "
                "same observational dataset and are treated as fixed in these intervals. "
                "Therefore this is an uncertainty-aware screening POC, not a causal "
                "safety model or a substitute for UDOT's official safety analysis."
            ),
            "summary": summary,
            "top_statistically_supported_corridors": top_display.to_dict(
                orient="records"
            ),
        }
        OUT_REPORT.write_text(
            json.dumps(report, indent=2, default=str),
            encoding="utf-8",
        )

        print("\nPHASE 2C COMPLETE")
        print("=================")
        print(f"Corridors tested: {summary['corridors_tested']}")
        print(f"PRIORITY SIGNAL: {summary['priority_signal']}")
        print(f"ELEVATED SIGNAL: {summary['elevated_signal']}")
        print(f"UNCERTAIN: {summary['uncertain']}")
        print(f"NO ELEVATION SIGNAL: {summary['no_elevation_signal']}")

        print("\nTop statistically supported corridor candidates")
        print("----------------------------------------------")
        if top_display.empty:
            print("No corridors met the statistical evidence criteria.")
        else:
            print(top_display.to_string(index=False))

        print("\nInterpretation:")
        print(
            "A PRIORITY/ELEVATED SIGNAL means the observed severe-crash count "
            "is above the peer expectation after BH-FDR correction, and the "
            "lower 95% O/E confidence bound is greater than 1."
        )
        print(
            "This is still a screening POC: it does not establish causality and "
            "does not replace UDOT's official safety methods."
        )

        print(f"\nSaved: {OUT_PARQUET.relative_to(ROOT)}")
        print(f"Saved: {OUT_REPORT.relative_to(ROOT)}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
