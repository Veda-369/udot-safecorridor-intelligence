-- Match crashes to the AADT section covering the crash milepoint.
CREATE OR REPLACE TABLE crash_aadt_matches AS
WITH candidates AS (
    SELECT
        c.crash_id,
        c.crash_year,
        c.route_raw,
        c.route_key,
        c.milepoint,
        c.severity,
        c.severe_crash_flag,
        c.fatal_crash_flag,
        c.latitude,
        c.longitude,
        c.county_name,
        c.region_name,
        c.speed_related_flag,
        c.dui_flag,
        c.distracted_driving_flag,
        c.roadway_departure_flag,
        a.segment_object_id,
        a.station,
        a.route_id_raw,
        a.begin_point,
        a.end_point,
        a.section_length,
        a.aadt,
        a.aadt_year,
        a.aadt_proxy_flag,
        a.annual_vmt,
        ROW_NUMBER() OVER (
            PARTITION BY c.crash_id
            ORDER BY
                ABS(((a.begin_point + a.end_point) / 2.0) - c.milepoint),
                a.segment_object_id
        ) AS match_rank
    FROM silver_crashes c
    LEFT JOIN silver_aadt_analysis a
      ON c.crash_year = a.analysis_year
     AND c.route_key = a.route_key
     AND c.milepoint BETWEEN LEAST(a.begin_point, a.end_point) AND GREATEST(a.begin_point, a.end_point)
)
SELECT * EXCLUDE (match_rank)
FROM candidates
WHERE match_rank = 1;

-- Segment-year exposure table includes AADT sections even when no crash occurred.
CREATE OR REPLACE TABLE gold_segment_risk AS
WITH crash_counts AS (
    SELECT
        segment_object_id,
        crash_year AS analysis_year,
        COUNT(*) AS crashes,
        SUM(severe_crash_flag) AS severe_crashes,
        SUM(fatal_crash_flag) AS fatal_crashes,
        SUM(speed_related_flag) AS speed_related_crashes,
        SUM(dui_flag) AS dui_crashes,
        SUM(distracted_driving_flag) AS distracted_crashes,
        SUM(roadway_departure_flag) AS roadway_departure_crashes
    FROM crash_aadt_matches
    WHERE segment_object_id IS NOT NULL
    GROUP BY segment_object_id, crash_year
),
segment_base AS (
    SELECT
        a.analysis_year,
        a.aadt_year,
        a.aadt_proxy_flag,
        a.segment_object_id,
        a.station,
        a.route_id_raw,
        a.route_key,
        a.begin_point,
        a.end_point,
        a.section_length,
        a.segment_description,
        a.aadt,
        a.annual_vmt,
        COALESCE(c.crashes, 0) AS crashes,
        COALESCE(c.severe_crashes, 0) AS severe_crashes,
        COALESCE(c.fatal_crashes, 0) AS fatal_crashes,
        COALESCE(c.speed_related_crashes, 0) AS speed_related_crashes,
        COALESCE(c.dui_crashes, 0) AS dui_crashes,
        COALESCE(c.distracted_crashes, 0) AS distracted_crashes,
        COALESCE(c.roadway_departure_crashes, 0) AS roadway_departure_crashes
    FROM silver_aadt_analysis a
    LEFT JOIN crash_counts c
      ON a.segment_object_id = c.segment_object_id
     AND a.analysis_year = c.analysis_year
)
SELECT
    *,
    severe_crashes * 100000000.0 / NULLIF(annual_vmt, 0) AS severe_crashes_per_100m_vmt,
    crashes * 100000000.0 / NULLIF(annual_vmt, 0) AS crashes_per_100m_vmt
FROM segment_base;

-- Route-level screening metric. Expected severe crashes use the statewide exposure rate.
CREATE OR REPLACE TABLE gold_route_risk AS
WITH statewide AS (
    SELECT
        SUM(severe_crashes) * 1.0 / NULLIF(SUM(annual_vmt), 0) AS severe_per_vmt
    FROM gold_segment_risk
),
route_rollup AS (
    SELECT
        route_key,
        SUM(crashes) AS crashes,
        SUM(severe_crashes) AS severe_crashes,
        SUM(fatal_crashes) AS fatal_crashes,
        SUM(speed_related_crashes) AS speed_related_crashes,
        SUM(dui_crashes) AS dui_crashes,
        SUM(distracted_crashes) AS distracted_crashes,
        SUM(roadway_departure_crashes) AS roadway_departure_crashes,
        SUM(annual_vmt) AS total_vmt,
        SUM(section_length) AS exposure_segment_miles,
        MAX(aadt_proxy_flag) AS uses_aadt_proxy
    FROM gold_segment_risk
    GROUP BY route_key
)
SELECT
    r.*,
    r.severe_crashes * 100000000.0 / NULLIF(r.total_vmt, 0) AS severe_crashes_per_100m_vmt,
    s.severe_per_vmt * r.total_vmt AS expected_severe_baseline,
    r.severe_crashes / NULLIF(s.severe_per_vmt * r.total_vmt, 0) AS observed_expected_ratio,
    CASE
        WHEN r.severe_crashes < 3 THEN 'INSUFFICIENT EVENTS'
        WHEN r.severe_crashes / NULLIF(s.severe_per_vmt * r.total_vmt, 0) >= 2.0 THEN 'HIGH'
        WHEN r.severe_crashes / NULLIF(s.severe_per_vmt * r.total_vmt, 0) >= 1.5 THEN 'ELEVATED'
        WHEN r.severe_crashes / NULLIF(s.severe_per_vmt * r.total_vmt, 0) >= 1.0 THEN 'MONITOR'
        ELSE 'BASELINE/LOW'
    END AS screening_band
FROM route_rollup r
CROSS JOIN statewide s
WHERE r.total_vmt > 0
ORDER BY observed_expected_ratio DESC NULLS LAST;

CREATE OR REPLACE TABLE gold_quality_summary AS
WITH crash_quality AS (
    SELECT
        COUNT(*) AS crash_rows,
        SUM(CASE WHEN route_key IS NOT NULL AND milepoint IS NOT NULL THEN 1 ELSE 0 END) AS eligible_for_aadt_match
    FROM silver_crashes
),
match_quality AS (
    SELECT
        COUNT(*) AS crashes_evaluated,
        SUM(CASE WHEN segment_object_id IS NOT NULL THEN 1 ELSE 0 END) AS crashes_matched_to_aadt,
        SUM(CASE WHEN aadt_proxy_flag = 1 THEN 1 ELSE 0 END) AS matched_using_aadt_proxy
    FROM crash_aadt_matches
)
SELECT
    c.crash_rows,
    c.eligible_for_aadt_match,
    m.crashes_evaluated,
    m.crashes_matched_to_aadt,
    m.matched_using_aadt_proxy,
    100.0 * m.crashes_matched_to_aadt / NULLIF(c.eligible_for_aadt_match, 0) AS eligible_match_rate_pct
FROM crash_quality c
CROSS JOIN match_quality m;
