# Methodology

## 1. Problem framing

Raw crash totals can prioritize high-volume roads simply because more vehicles use them. The MVP therefore adds an exposure denominator based on Annual Average Daily Traffic (AADT) and segment length.

## 2. Severe crash definition

For v0.1:

- Fatal
- Suspected Serious Injury

are classified as severe crashes.

## 3. Cross-source matching

Crashes are matched to AADT road sections using:

1. A normalized numeric route key extracted from UDOT `ROUTE` and AADT `RouteID`.
2. Crash `START_ACCUM` / milepoint falling between AADT `BeginPoint` and `EndPoint`.

If multiple candidates exist, the segment whose midpoint is closest to the crash milepoint is selected. The pipeline publishes an eligible match-rate diagnostic. Low matching quality should trigger route-key refinement before findings are presented.

## 4. Exposure

For each AADT section/year:

`Annual VMT = AADT × SectionLength × 365.25`

For 2025 crash screening, AADT2024 is used as an explicit proxy because the current source layer exposes annual AADT through 2024. The resulting records carry `aadt_proxy_flag = 1`.

## 5. Exposure-adjusted rate

`Severe Crash Rate = Severe Crashes × 100,000,000 / Annual VMT`

This yields severe crashes per 100 million vehicle miles traveled.

## 6. v0.1 observed/expected screen

The statewide baseline rate is:

`statewide severe crashes / statewide VMT`

For each route:

`Expected Severe = statewide rate × route VMT`

`O/E = observed severe crashes / expected severe crashes`

This is a transparent screening statistic, **not a causal crash-frequency model**.

## 7. Planned statistical model

The next version should estimate expected severe-crash counts using a count model such as Poisson or negative binomial with a log(VMT) offset and roadway covariates. Candidate features include functional class, lane count, median, shoulder, roadway geometry and other defensible attributes.

Model validation should include:

- Overdispersion assessment
- Residual diagnostics
- Holdout or temporal validation where appropriate
- Confidence/prediction intervals
- Sensitivity to sparse-event segments
