-- Dynamic AADT exposure source is prepared in Python by
-- src.ingestion.aadt.build_aadt_analysis_frame().
--
-- For each historical analysis year the builder chooses:
--   1) same-year AADT when available;
--   2) otherwise the newest available AADT year <= analysis year.
--
-- This SQL deliberately avoids hard-coding calendar years so completed crash
-- years can roll into the historical model without an annual SQL edit.

CREATE OR REPLACE TABLE silver_aadt_long AS
SELECT
    TRY_CAST(segment_object_id AS BIGINT) AS segment_object_id,
    TRIM(CAST(station AS VARCHAR)) AS station,
    TRIM(CAST(route_id_raw AS VARCHAR)) AS route_id_raw,
    CASE
        WHEN TRY_CAST(route_key AS INTEGER) IS NOT NULL
        THEN CAST(TRY_CAST(route_key AS INTEGER) AS VARCHAR)
        ELSE NULL
    END AS route_key,
    TRY_CAST(begin_point AS DOUBLE) AS begin_point,
    TRY_CAST(end_point AS DOUBLE) AS end_point,
    TRY_CAST(section_length AS DOUBLE) AS section_length,
    TRIM(CAST(segment_description AS VARCHAR)) AS segment_description,
    TRY_CAST(analysis_year AS INTEGER) AS analysis_year,
    TRY_CAST(aadt_year AS INTEGER) AS aadt_year,
    TRY_CAST(aadt AS DOUBLE) AS aadt
FROM aadt_analysis_source;

CREATE OR REPLACE TABLE silver_aadt_analysis AS
SELECT
    *,
    CASE WHEN analysis_year <> aadt_year THEN 1 ELSE 0 END AS aadt_proxy_flag,
    CASE
        WHEN aadt > 0 AND section_length > 0
        THEN aadt * section_length * 365.25
        ELSE NULL
    END AS annual_vmt
FROM silver_aadt_long
WHERE aadt IS NOT NULL
  AND aadt > 0
  AND section_length IS NOT NULL
  AND section_length > 0
  AND route_key IS NOT NULL;
