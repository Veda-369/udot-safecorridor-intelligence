# UDOT SafeCorridor Intelligence

**Live dashboard:** https://udot-safecorridor.streamlit.app/

**Exposure-Adjusted Roadway Safety Prioritization & Decision-Support System**

Independent analytical proof-of-concept using publicly available Utah Department of Transportation (UDOT) transportation data.

> **Portfolio disclaimer:** This project is not affiliated with, commissioned by, or endorsed by UDOT. It was developed independently to demonstrate transportation analytics, spatial data engineering, statistical screening, data quality, automation, and executive decision support using public data.

---

## Executive question

**Which Utah roadway corridors show disproportionately high fatal and serious-injury crash burden after accounting for traffic exposure, and which corridors merit further investigation?**

The project moves beyond raw crash counts by combining:

- crash history,
- traffic exposure,
- official route geometry,
- spatial linear referencing,
- statistical uncertainty,
- false-discovery-rate control,
- corridor consolidation, and
- descriptive crash-characteristic analysis.

The result is a reproducible pipeline and interactive dashboard that separates:

1. **Where severe crashes occur statewide**
2. **Where severe-crash burden is unusually elevated after exposure adjustment**
3. **Which crash characteristics are overrepresented within a selected priority corridor**

---

## Project highlights

- **449,804** crash records processed
- **4,574** UDOT AADT roadway records processed
- **96.5%** eligible crash-to-AADT match rate
- **99.0%** valid spatial route-match rate
- **0.29 m** median crash-to-route snap distance
- **519** five-mile corridors statistically tested
- **45** supported executive corridor clusters after consolidation
- Automated **weekly GitHub Actions** refresh
- Interactive **Streamlit** dashboard with:
  - statewide severe-crash exploration,
  - county → route cascading filters,
  - priority-corridor screening,
  - corridor drill-down,
  - search,
  - numeric chart labels,
  - Utah-inspired styling, and
  - color-accessible / high-contrast viewing modes

---

## Analytical workflow

```text
Public UDOT APIs
      |
      v
Python ingestion
      |
      +--------------------+
      |                    |
      v                    v
Crash data             AADT data
      |                    |
      +---------+----------+
                |
                v
         Bronze Parquet
                |
                v
       DuckDB + SQL models
                |
                v
       Validation / QA layer
                |
                v
     Official route geometry
                |
                v
 Spatial route matching + LRS
                |
                v
       5-mile corridor bins
                |
                v
   Traffic-exposure adjustment
                |
                v
 Observed vs expected screening
                |
                v
 Poisson uncertainty intervals
                |
                v
 Benjamini-Hochberg FDR control
                |
                v
 Adjacent-bin consolidation
                |
                v
 Executive priority corridors
                |
        +-------+-------+
        |               |
        v               v
 Driver analysis   Statewide explorer
        |               |
        +-------+-------+
                |
                v
      Streamlit dashboard
```

---

## Data engineering

### Sources

The pipeline uses publicly available UDOT sources, including:

- annual crash-location layers,
- unrounded AADT roadway-section data, and
- official UDOT route geometry.

See [`docs/data_sources.md`](docs/data_sources.md) for source details.

### Ingestion

The ingestion layer includes:

- ArcGIS REST requests,
- pagination,
- dynamic crash-year layer discovery,
- WGS84 coordinate requests,
- schema normalization,
- Parquet persistence, and
- configurable analysis-year parameters.

### Storage and transformation

The project uses:

- **Python** for ingestion, spatial processing, statistics, and automation
- **DuckDB** for the analytical warehouse
- **SQL** for Bronze → Silver → Gold transformations
- **Parquet** for portable analytical outputs

Local raw/intermediate data and the DuckDB database are excluded from version control. Small Gold-layer outputs needed by the public dashboard are retained in the repository.

---

## Data quality and spatial validation

The pipeline explicitly validates:

- missing crash IDs,
- duplicate crash IDs,
- missing severity fields,
- coordinate plausibility,
- route normalization,
- AADT completeness,
- cross-source route matching, and
- spatial route-match quality.

Key validated results:

| Measure | Result |
|---|---:|
| Crash records processed | 449,804 |
| AADT records processed | 4,574 |
| Eligible crash-to-AADT match rate | 96.5% |
| Valid spatial route matches | 263,155 |
| Spatial route-match rate | 99.0% |
| Median crash-to-route snap distance | 0.29 m |

The spatial workflow replaced an earlier milepoint assumption after validation showed that the crash source field should not be interpreted as a statewide route milepost. The final methodology instead matches crash coordinates to official UDOT route geometry and derives route position spatially.

---

## Exposure-adjusted corridor methodology

### 1. Traffic exposure

AADT and segment length are used to estimate vehicle-miles traveled (VMT), allowing severe-crash burden to be compared after accounting for roadway exposure.

### 2. Five-mile corridor bins

Spatially referenced crashes are grouped into five-mile route bins.

### 3. Peer expected severe crashes

Corridors are compared with exposure-relevant roadway peers to estimate an expected severe-crash count.

### 4. Observed / expected ratio

```text
O/E = Observed severe crashes / Expected severe crashes
```

Values above 1 indicate more severe crashes than the screening baseline would expect.

### 5. Uncertainty

The screening layer includes:

- one-sided Poisson exceedance tests,
- exact 95% Poisson O/E confidence intervals, and
- Benjamini-Hochberg false-discovery-rate correction.

### 6. Executive consolidation

Adjacent supported five-mile bins are merged into longer executive corridor clusters for decision-support presentation while preserving the five-mile statistical results as the analytical evidence base.

---

## Example priority corridors

The final executive layer identified **45 supported corridor clusters**.

Examples from the ranked output include:

| Corridor | Severe | Fatal | Expected severe | O/E | Above expected |
|---|---:|---:|---:|---:|---:|
| SR 68 · MP 45–65 · Salt Lake County | 193 | 34 | 68.3 | 2.82 | 124.7 |
| SR 126 · MP 0–20 · Davis County | 172 | 35 | 65.5 | 2.63 | 106.5 |
| US 89 · MP 375–390 · Salt Lake County | 148 | 24 | 44.5 | 3.33 | 103.5 |
| US 89 · MP 420–430 · Weber County | 100 | 16 | 18.7 | 5.34 | 81.3 |

These are **screening/prioritization signals**, not causal findings or official project recommendations.

---

## Dashboard

The production app is:

```text
dashboard/app.py
```

The dashboard contains five analytical views:

### 1. Statewide Explorer

Answers:

> **Where are severe crashes occurring across Utah?**

Includes:

- severe and fatal crash KPIs,
- county / route / year filtering,
- county → route cascading,
- statewide crash map,
- time trend, and
- county ranking.

### 2. Current-Year YTD Monitor

Answers:

> **What is happening in the preliminary current calendar year, compared with the same period in prior completed years?**

Includes:

- automatic detection of the current UDOT annual crash layer,
- statewide YTD crash / severe / fatal KPIs,
- same-period prior-year comparisons,
- county → route cascading filters,
- current-year severe/fatal crash map,
- monthly severe-crash comparison, and
- county YTD context.

The current calendar year is intentionally excluded from the historical O/E/FDR model until the year is complete. At calendar rollover, the completed year automatically becomes historical and the new calendar year becomes the YTD monitor.

### 3. Priority Corridors

Answers:

> **Where is severe-crash burden disproportionately elevated after traffic exposure adjustment?**

Includes:

- supported corridor shortlist,
- observed vs expected burden,
- excess severe-crash ranking,
- corridor map, and
- synchronized county / route filters.

### 4. Why This Corridor?

Answers:

> **What crash characteristics are overrepresented within a selected priority corridor?**

Compares corridor severe crashes with the statewide severe-crash baseline for:

- speed-related crashes,
- DUI,
- distracted driving, and
- roadway departure.

These comparisons are descriptive associations and should not be interpreted as causal effects.

### 5. Methodology

Documents:

- analytical workflow,
- statistical assumptions,
- validation evidence,
- governance considerations, and
- limitations.

---

## Accessibility

The dashboard includes a **Color accessibility** control with:

- Standard Utah palette
- Color-accessible palette
- High contrast

Important information is not communicated through color alone. Charts and maps also use:

- numeric labels,
- legends,
- marker size,
- outlines,
- tables, and
- descriptive text.

---

## Automatic calendar-year rollover

The crash-year logic is dynamic rather than hard-coded:

```text
Calendar year N
├── Historical model: 2018 through N-1 (completed years)
└── Current monitor: N YTD (preliminary)
```

When January 1 arrives, year `N` automatically becomes eligible for the historical pipeline and year `N+1` becomes the YTD monitor. If UDOT has not yet published the new annual layer, the historical pipeline continues normally and the YTD monitor reports that the layer is not yet available.

Historical exposure years are also generated dynamically. For each analysis year, the pipeline uses same-year AADT when available; otherwise it explicitly uses the newest available prior AADT year as a proxy and records the mapping in the pipeline report. This prevents a newly completed crash year from silently dropping out of the exposure-adjusted model.

The historical extractor preserves the validated legacy source where available and falls back to UDOT's nightly FeatureServer for newer annual layers. Current-year TimestampOffset values are normalized to `America/Denver`, and source freshness is tracked separately from crash occurrence dates.

## Automation

The GitHub Actions workflow is defined in:

```text
.github/workflows/pipeline.yml
```

The scheduled workflow rebuilds the analytical chain:

```text
src.pipeline
    ↓
phase2a_screen.py
    ↓
phase2b_spatial.py
    ↓
phase2c_statistical.py
    ↓
phase2d_executive_corridors.py
    ↓
phase3_driver_analysis.py
    ↓
phase3b_statewide_explorer.py
    ↓
phase3c_current_year_monitor.py
```

Published Gold datasets and quality/statistical reports are committed when outputs change.

---

## Run locally

### Windows Command Prompt

```cmd
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m src.pipeline
.venv\Scripts\python.exe phase2a_screen.py
.venv\Scripts\python.exe phase2b_spatial.py
.venv\Scripts\python.exe phase2c_statistical.py
.venv\Scripts\python.exe phase2d_executive_corridors.py
.venv\Scripts\python.exe phase3_driver_analysis.py
.venv\Scripts\python.exe phase3b_statewide_explorer.py
.venv\Scripts\python.exe phase3c_current_year_monitor.py
.venv\Scripts\python.exe -m streamlit run dashboard\app.py
```

### macOS / Linux

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m src.pipeline
python phase2a_screen.py
python phase2b_spatial.py
python phase2c_statistical.py
python phase2d_executive_corridors.py
python phase3_driver_analysis.py
python phase3b_statewide_explorer.py
python phase3c_current_year_monitor.py
python -m streamlit run dashboard/app.py
```

---

## Repository structure

```text
.github/workflows/        scheduled pipeline orchestration
dashboard/                production Streamlit application
data/gold/                published analytical outputs
docs/                     methodology, lineage, sources, limitations
reports/                  generated QA/statistical reports
sql/                      DuckDB SQL transformations
src/ingestion/            ArcGIS REST ingestion
src/quality/              validation checks
src/pipeline.py            base orchestration
phase2a_screen.py          route screening
phase2b_spatial.py         spatial LRS + corridor construction
phase2c_statistical.py     statistical validation
phase2d_executive_corridors.py
                          adjacent-bin executive consolidation
phase3_driver_analysis.py  corridor characteristic analysis
phase3b_statewide_explorer.py
                          historical statewide dashboard dataset generation
phase3c_current_year_monitor.py
                          dynamic current-year YTD monitoring + rollover
tests/                    static pipeline checks
```

---

## Limitations

This is a portfolio proof-of-concept and should not be interpreted as an official roadway safety study.

Important limitations include:

- observational crash data do not establish causality,
- five-mile bins and consolidated clusters are analytical constructs rather than official project boundaries,
- peer expected counts are estimated from the same observational dataset,
- expected counts are treated as fixed for the screening confidence intervals,
- driver/behavior comparisons identify overrepresentation rather than causal mechanisms, and
- production roadway-safety decisions should use UDOT-approved engineering methods, roadway characteristics, and formal safety-performance modeling.

See [`docs/limitations.md`](docs/limitations.md).

---

## Technology

**Python · SQL · DuckDB · Pandas · GeoPandas · Shapely · SciPy · Parquet · ArcGIS REST · Streamlit · Altair · PyDeck · GitHub Actions**

---

## Purpose

This project demonstrates an end-to-end public-sector transportation analytics workflow:

**data acquisition → quality control → spatial integration → exposure normalization → statistical screening → executive prioritization → interactive decision support → automated refresh**
