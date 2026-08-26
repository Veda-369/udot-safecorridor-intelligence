# Methodology

## 1. Decision question

The project asks:

> Which Utah roadway corridors show disproportionately high fatal/serious-injury crash burden after accounting for traffic exposure, and which corridors merit further investigation?

Raw crash totals alone can over-prioritize roads simply because they carry more traffic, so the historical screening model includes traffic exposure and uncertainty.

## 2. Historical versus current-year separation

The pipeline deliberately maintains two time tracks:

```text
Calendar year N
├── Historical model: 2018 through N-1 (completed years)
└── Current-year monitor: N YTD (preliminary)
```

The historical model excludes the incomplete current year. On calendar rollover, the completed year becomes eligible for historical modeling automatically and the new calendar year becomes the YTD monitor year.

If UDOT has not yet published the new annual current-year layer, the YTD monitor reports that condition and waits; the historical pipeline continues normally.

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

## 5. Crash-to-route spatial referencing

An earlier prototype tested the crash-source accumulated mileage field as a corridor location. Validation showed geographically impossible clustering across multiple counties for the same apparent milepoint, so that method was discarded.

The production approach instead:

1. Loads official UDOT route geometry.
2. Normalizes numeric route identifiers.
3. Matches crash coordinates to the corresponding route geometry.
4. Keeps route matches within the configured spatial tolerance.
5. Projects the crash point onto the official route line.
6. Derives an analytical route milepoint using UDOT begin/end mileage and normalized line position.

This spatial LRS workflow is the basis for five-mile corridor construction.

## 6. Traffic exposure

For each AADT section/year:

`Annual VMT = AADT × SectionLength × 365.25`

Severe crash rates are expressed per 100 million vehicle miles traveled.

The project currently uses the UDOT AADT 2024 Unrounded publication, including explicit proxy handling where the crash year is newer than the available AADT year.

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

The peer expected count is estimated from the observational dataset and treated as fixed for this screening uncertainty calculation. This is a prioritization POC, not an official crash-frequency safety-performance function.

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

The YTD monitor automatically discovers the current calendar-year UDOT layer, preferring the nightly FeatureServer. It produces:

- current-year crash, severe-crash and fatal-crash counts,
- severe/fatal crash map records,
- county and route summaries,
- same-period comparisons with up to five prior completed years, and
- monthly severe/fatal trends versus the same-period historical average.

The comparison cutoff uses the latest crash date represented in the current-year data. Prior completed years are truncated to the same month/day so a partial year is not compared with full-year totals.

Current-year data remain explicitly labeled preliminary because recent records can be delayed or revised.

## 12. Interpretation limitations

- This is an independent portfolio proof-of-concept, not an official UDOT safety study.
- Observational data do not establish causality.
- Five-mile bins and merged clusters are analytical constructs, not official project boundaries.
- Peer expected counts are estimated from the same observational dataset.
- Current-year crash data are preliminary and may be incomplete near the reporting date.
- The AADT source is currently a fixed 2024 publication and should be refreshed when a newer defensible exposure source is available.
- Production roadway-safety decisions should use UDOT-approved engineering methods, roadway characteristics and formal safety-performance modeling.


## Current-year monitoring and automatic rollover

The current calendar year is treated as preliminary YTD data and is intentionally excluded from the completed-year O/E/FDR corridor model. ArcGIS `TimestampOffset` values are parsed safely and converted to `America/Denver` before date-based comparisons. `CURRENT_AS_OF_DATE` is used as the source-freshness signal when available.

At calendar rollover, the completed crash year becomes eligible for the historical model automatically. Historical AADT exposure rows are generated dynamically: same-year AADT is preferred; when unavailable, the newest prior available AADT is used as an explicitly labeled proxy.

Current-year same-period comparisons exclude invalid or undated crash timestamps and report those records separately as data-quality metrics.
