# Methodology

## 1. Decision question

The project asks:

> Which Utah roadway corridors show disproportionately high fatal/serious-injury crash burden after accounting for traffic exposure, and which corridors merit further investigation?

Raw crash totals alone can over-prioritize roads simply because they carry more traffic, so the historical screening model includes traffic exposure and statistical uncertainty.

## 2. Historical versus current-year separation

The pipeline deliberately maintains two time tracks:

```text
Calendar year N
├── Historical model: 2018 through N-1 (completed years)
└── Current-year monitor: N YTD (preliminary)
```

The incomplete current year is excluded from the historical O/E/FDR model. At calendar rollover, the completed year automatically becomes eligible for historical modeling and the new calendar year becomes the YTD monitor year. If the new current-year UDOT layer is not yet available, the YTD monitor reports that condition while the historical pipeline remains usable.

## 3. Severe crash definition

A crash is classified as severe when severity is:

- Fatal
- Suspected Serious Injury

## 4. Data-quality validation

Validation includes:

- missing crash identifiers,
- duplicate crash identifiers,
- missing severity,
- plausible Utah coordinates,
- route normalization,
- AADT completeness,
- crash/AADT cross-source matching, and
- spatial route-match quality.

Current-year monitoring additionally reports invalid/undated timestamps, records dated outside the monitor year, missing crash IDs, and duplicate non-null IDs after normalization.

## 5. Crash-to-route spatial referencing

An earlier prototype tested the crash-source accumulated mileage field as a corridor location. Validation showed geographically impossible clustering across multiple counties for the same apparent milepoint, so that method was discarded.

The production approach instead:

1. Loads official UDOT route geometry.
2. Normalizes numeric route identifiers.
3. Matches crash coordinates to the corresponding route geometry.
4. Keeps route matches within the configured spatial tolerance.
5. Projects the crash point onto the official route line.
6. Derives an analytical route milepoint using UDOT begin/end mileage and normalized line position.

The route-reference download is object-ID paginated and count-validated before spatial processing.

## 6. Traffic exposure and annual rollover

For each AADT section/year:

`Annual VMT = AADT × SectionLength × 365.25`

Severe crash rates are expressed per 100 million vehicle miles traveled.

The configured exposure source is currently **UDOT AADT 2024 Unrounded**. Historical analysis years are generated dynamically from the AADT year fields available in that configured source:

1. Use same-year AADT when available.
2. Otherwise use the newest available AADT year less than or equal to the analysis year.
3. Mark the row with `aadt_proxy_flag = 1` when a proxy year is used.
4. Publish the analysis-year → AADT-year mapping in the pipeline report.

This lets a newly completed crash year move into the historical model without an annual SQL edit even if same-year AADT has not yet been published. Automatic discovery of an entirely new future AADT publication URL is not currently implemented; changing the configured AADT source remains a maintenance task when UDOT publishes a newer defensible exposure dataset.

## 7. Five-mile corridor screening

Spatially referenced crashes are aggregated into five-mile route bins. Corridors must meet minimum evidence/exposure thresholds before statistical prioritization.

Expected severe-crash burden is estimated from comparable exposure peers using a leave-one-route/corridor-out screening baseline.

For each corridor:

`O/E = Observed severe crashes / Expected severe crashes`

`Excess severe = Observed severe crashes - Expected severe crashes`

## 8. Statistical uncertainty

The screening layer uses:

- one-sided Poisson exceedance p-values,
- exact 95% Poisson confidence intervals for the O/E ratio, and
- Benjamini-Hochberg false-discovery-rate correction.

The peer expected count is estimated from the observational dataset and treated as fixed for this screening uncertainty calculation. This is a prioritization proof-of-concept, not an official crash-frequency safety-performance function.

## 9. Executive corridor consolidation

Adjacent statistically supported five-mile bins on the same route are merged into longer executive corridor clusters. This is a presentation/decision-support step; the underlying five-mile statistical results remain the evidence base.

## 10. Corridor characteristic analysis

For supported executive corridors, severe crashes are compared with the statewide severe-crash baseline for:

- speed-related crashes,
- DUI,
- distracted driving, and
- roadway departure.

These are descriptive overrepresentation measures, not causal effects.

## 11. Current-year YTD monitor

The YTD monitor discovers the current calendar-year UDOT crash layer, preferring the nightly FeatureServer. It produces:

- current-year crash, severe-crash and fatal-crash counts,
- severe/fatal crash map records,
- county and route summaries,
- same-period comparisons with up to five prior completed years, and
- monthly severe/fatal trends versus the same-period historical average.

UDOT `TimestampOffset` values are parsed as timezone-aware timestamps and converted to `America/Denver` before deriving dates, months, or comparison cutoffs. This avoids shifting late-night Utah crashes into the next UTC calendar date.

Source freshness and crash occurrence are treated separately:

- **Data as of:** latest valid `CURRENT_AS_OF_DATE` when available.
- **YTD comparison cutoff:** the earlier of today's Utah-local date and the source as-of date.

Historical comparison years are truncated to the same month/day cutoff. Invalid or undated current-year crash timestamps are excluded from same-period YTD comparisons and reported separately as data-quality metrics.

Current-year data remain explicitly labeled preliminary because recent records can be delayed or revised.

## 12. Interpretation limitations

- This is an independent portfolio proof-of-concept, not an official UDOT safety study.
- Observational data do not establish causality.
- Five-mile bins and merged clusters are analytical constructs, not official project boundaries.
- Peer expected counts are estimated from the same observational dataset.
- Current-year crash data are preliminary and may be incomplete near the reporting date.
- AADT is an annualized exposure estimate; proxy years may be used when same-year AADT is unavailable.
- The configured AADT publication must be manually updated when adopting an entirely new UDOT AADT source.
- Production roadway-safety decisions should use UDOT-approved engineering methods, roadway characteristics, and formal safety-performance modeling.
