# Published output manifest

The live Streamlit application reads generated files from `data/gold/` and `reports/`.

This source snapshot intentionally does **not overwrite or delete** the already-published generated outputs in an existing clone. Copy this package over the current cloned repository so the current working dashboard artifacts remain in place until GitHub Actions regenerates them.

Expected Gold outputs include:

- `data/gold/corridor_candidates_spatial_v2.parquet`
- `data/gold/corridor_candidates_statistical_v3.parquet`
- `data/gold/corridor_driver_analysis_v1.parquet`
- `data/gold/executive_corridors_v4.parquet`
- `data/gold/quality_summary.parquet`
- `data/gold/route_candidates_v2.parquet`
- `data/gold/route_risk.parquet`
- `data/gold/segment_risk.parquet`
- `data/gold/severe_crash_points.parquet`
- `data/gold/statewide_county_summary.parquet`
- `data/gold/statewide_route_summary.parquet`
- `data/gold/statewide_severe_crashes.parquet`
- `data/gold/current_year_crashes.parquet`
- `data/gold/current_year_county_summary.parquet`
- `data/gold/current_year_route_summary.parquet`
- `data/gold/current_year_ytd_comparison.parquet`
- `data/gold/current_year_monthly_trend.parquet`

Expected reports include:

- `reports/quality_report.json`
- `reports/pipeline_run.json`
- `reports/phase2a_screening.json`
- `reports/phase2b_spatial.json`
- `reports/phase2c_statistical_validation.json`
- `reports/phase2d_executive_corridors.json`
- `reports/phase3_driver_analysis.json`
- `reports/phase3b_statewide_explorer.json`
- `reports/phase3c_current_year_monitor.json`

GitHub Actions regenerates and republishes these outputs after the source update is committed.


### Refresh observability reports
- `reports/incremental_historical_refresh.json` — which historical years were reused vs re-fetched
- `reports/incremental_current_refresh.json` — current-year refresh mode, rows fetched, reconciliation/fallback details

The underlying `data/cache/` directory is deliberately **not** published to Git; GitHub Actions cache persists it between successful workflow runs.
