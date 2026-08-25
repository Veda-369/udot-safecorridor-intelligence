# Limitations

1. This is an independent portfolio proof-of-concept, not a UDOT production system.
2. Crash data is observational and does not establish causal effects.
3. UDOT notes that recent crash records can be delayed or have locations corrected later.
4. AADT is an annualized traffic exposure estimate, not exact traffic at the moment of each crash.
5. The current AADT source exposes data through 2024; 2025 screening uses 2024 AADT as a documented proxy.
6. Route-number normalization may not perfectly map every local road or special route representation. Match rate is published and must be reviewed.
7. v0.1 observed/expected values use a statewide exposure baseline. A proper roadway-characteristic count model is planned for v0.2.
8. Small-number routes can produce unstable ratios; the dashboard marks routes with fewer than three severe crashes as insufficient-event screens.
