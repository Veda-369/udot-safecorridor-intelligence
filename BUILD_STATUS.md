# Project Status

**Status:** Stabilization build prepared; cloud refresh pending validation  
**Last updated:** 2026-08-26

## Historical analytical core
- UDOT historical crash ingestion: implemented
- AADT ingestion and exposure normalization: implemented
- DuckDB Bronze/Silver/Gold transformations: implemented
- Spatial LRS using official UDOT route geometry: implemented
- 5-mile corridor construction: implemented
- O/E screening, Poisson intervals, and FDR: implemented
- Executive corridor consolidation: implemented
- Driver analysis and statewide explorer: implemented
- Streamlit production dashboard: deployed

## Stabilization changes prepared
- Current-year TimestampOffset parser hardened against numeric overflow
- Utah-local (`America/Denver`) calendar normalization
- `CURRENT_AS_OF_DATE` source-freshness handling
- Invalid/undated current-year date QA
- Missing-ID-safe current-year deduplication
- Dynamic AADT historical-year/proxy generation
- Pytest regression gate in GitHub Actions
- Workflow concurrency protection
- Historical-output publication isolated from current-monitor publication
- UDOT route-geometry pagination hardened
- JSON quality booleans normalized

## Next validation
Run the GitHub Actions workflow on `main`. A production-ready rollover status requires the full cloud workflow to finish green and publish the current-year Gold outputs.

## Disclaimer
This is an independent portfolio proof-of-concept using public UDOT data. It is not affiliated with or endorsed by UDOT. Priority results are screening signals for investigation, not causal findings or official roadway recommendations.


## Incremental refresh upgrade
- Hybrid incremental crash ingestion implemented
- Per-year historical cache with ArcGIS revision/count invalidation
- 30-day recent-history / 180-day archive safety reconciliations
- Current-year 60-day rolling reconciliation + new OBJECTID query
- 30-day full current-year reconciliation safety net
- Final rollover reconciliation for the completed year
- GitHub Actions persistent cache (`actions/cache@v5`)
- Full-fetch fallback when cache is missing or incremental queries fail
