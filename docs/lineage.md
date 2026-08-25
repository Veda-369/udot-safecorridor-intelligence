# Data Lineage

```mermaid
flowchart LR
    A[UDOT Crash Locations MapServer] --> C[Python ArcGIS extractor]
    B[UDOT AADT Unrounded FeatureServer] --> D[Python ArcGIS extractor]
    C --> E[Bronze crashes_raw.parquet]
    D --> F[Bronze aadt_raw.parquet]
    E --> G[DuckDB Silver crash normalization]
    F --> H[DuckDB Silver AADT long/exposure model]
    G --> I[Route + milepoint matching]
    H --> I
    I --> J[Gold segment_risk]
    J --> K[Gold route_risk]
    G --> L[Gold severe_crash_points]
    I --> M[Gold quality_summary]
    K --> N[Streamlit dashboard]
    L --> N
    M --> N
```

## Governance design

- Raw source snapshots are reproducible and excluded from Git history.
- Small Gold outputs are intended for the public dashboard.
- No personal identifiers are introduced.
- Source limitations are documented in the repository and dashboard.
- Match quality is treated as an analytical gate, not hidden.
