# Project Status

**Status:** Production dashboard QA passed  
**Last updated:** 2026-08-25

## Completed

### Data ingestion
- Dynamic discovery of UDOT annual crash layers
- Paginated ArcGIS REST extraction
- UDOT unrounded AADT ingestion
- Public UDOT route-geometry ingestion
- Bronze Parquet persistence

### Data engineering
- DuckDB analytical warehouse
- Bronze → Silver → Gold SQL transformations
- Route normalization
- Crash/AADT cross-source matching
- VMT exposure calculation
- Severe-crash feature normalization

### Data quality
- 449,804 crash records processed
- 4,574 AADT records processed
- 96.5% eligible crash-to-AADT match rate
- Missing / duplicate / coordinate validation
- Quality reports generated automatically

### Spatial analytics
- Crash-to-official-route spatial matching
- Route-position derivation using official geometry
- 263,155 valid spatial route matches
- 99.0% spatial match rate
- 0.29 m median snap distance
- Five-mile corridor construction

### Statistical screening
- Exposure-adjusted expected severe crashes
- Observed / expected ratios
- Exact 95% Poisson O/E confidence intervals
- One-sided exceedance testing
- Benjamini-Hochberg false-discovery-rate correction
- 519 corridors tested

### Executive prioritization
- Supported adjacent bins consolidated
- 45 executive corridor clusters produced
- Excess severe-crash burden ranking
- Executive corridor mapping

### Diagnostic analysis
- Speed-related crash comparison
- DUI comparison
- Distracted-driving comparison
- Roadway-departure comparison
- Statewide severe-crash baseline comparisons

### Dashboard
- Production app: `dashboard/app.py`
- Statewide Explorer
- Priority Corridors
- Why This Corridor?
- Methodology
- County → route cascading filters
- Searchable corridor drill-down
- Multi-county filtering
- Numeric bar labels
- Utah-inspired visual system
- Color-accessible palette
- High-contrast viewing mode
- Final dashboard QA passed

### Automation
- GitHub Actions weekly workflow
- Full analytical chain configured for automated refresh
- Published Gold datasets and reports prepared for version control

## Remaining deployment tasks

- Create remote GitHub repository
- Push initial commit
- Verify GitHub Actions manual run
- Deploy `dashboard/app.py` to Streamlit Community Cloud
- Add public dashboard URL to README
- Create final executive one-page brief
- Add portfolio/resume project entry
- Prepare recruiter outreach message

## Analytical caution

This project is an independent proof-of-concept using public UDOT data. It is not affiliated with or endorsed by UDOT.

Priority results are statistical screening signals for further investigation. They are not causal claims, engineering diagnoses, or official roadway project recommendations.
