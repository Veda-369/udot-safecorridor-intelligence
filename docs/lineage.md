# Data Lineage

```mermaid
flowchart LR
    A[UDOT completed-year crash layers] --> C[Python ArcGIS ingestion]
    A2[UDOT nightly current-year crash layer] --> C2[Current-year ingestion]
    B[UDOT AADT Unrounded source] --> D[Python AADT ingestion]
    R[Official UDOT route geometry] --> S[Spatial LRS]

    C --> E[Bronze crashes_raw.parquet]
    D --> F[Bronze aadt_raw.parquet]
    E --> G[DuckDB Silver crash normalization]
    F --> H[Dynamic analysis-year AADT exposure rows]
    G --> I[Crash to AADT exposure matching]
    H --> I
    G --> S
    R --> S

    I --> J[Gold route / segment risk]
    S --> K[5-mile corridor bins]
    K --> L[Poisson + FDR screening]
    L --> M[Executive corridor clusters]
    M --> N[Driver analysis]
    G --> O[Historical statewide explorer]

    C2 --> P[TimestampOffset normalization]
    P --> Q[Utah-local YTD comparisons]

    J --> Z[Streamlit dashboard]
    M --> Z
    N --> Z
    O --> Z
    Q --> Z
```

## Governance design

- Raw/intermediate snapshots and the local DuckDB warehouse are reproducible and excluded from Git history.
- Small Gold outputs and reports required by the public dashboard are intentionally versioned.
- No personal identifiers are introduced; the public crash source states that personal identification information is removed.
- Current-year source freshness is tracked separately from crash occurrence dates.
- AADT proxy use is explicit through `analysis_year`, `aadt_year`, and `aadt_proxy_flag`.
- Match quality and data-quality checks are analytical gates rather than hidden assumptions.
- Current-year YTD observations remain separate from the completed-year historical prioritization model.
