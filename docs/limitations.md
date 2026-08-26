# Limitations

1. This is an independent portfolio proof-of-concept, not a UDOT production system or official safety study.
2. Crash data are observational and do not establish causal effects.
3. UDOT notes that recent crash records can be delayed, revised, or have locations corrected after initial entry.
4. Current-year results are preliminary YTD observations and are intentionally excluded from the completed-year O/E/FDR model.
5. AADT is an annualized traffic-exposure estimate, not exact traffic at the moment of each crash.
6. The configured exposure source is currently UDOT AADT 2024 Unrounded. For later historical analysis years, the pipeline uses the newest available prior AADT year as an explicitly flagged proxy when same-year AADT is unavailable.
7. Automatic calendar rollover does not automatically discover a completely new future AADT publication URL; adopting a newer UDOT AADT source remains a maintenance task.
8. Route-number normalization may not perfectly map every local road or special route representation. Match quality is published and reviewed.
9. Five-mile bins and merged executive clusters are analytical constructs, not official project boundaries.
10. Peer expected counts are estimated from the observational dataset and treated as fixed for the screening confidence intervals.
11. Driver/behavior comparisons measure descriptive overrepresentation and should not be interpreted as causes.
12. Production roadway-safety decisions should use UDOT-approved engineering methods, roadway characteristics, and formal safety-performance modeling.
