CREATE OR REPLACE TABLE silver_aadt_long AS
WITH base AS (
    SELECT
        TRY_CAST(OBJECTID AS BIGINT) AS segment_object_id,
        TRIM(CAST(Station AS VARCHAR)) AS station,
        TRIM(CAST(RouteID AS VARCHAR)) AS route_id_raw,
        CASE
            WHEN regexp_extract(CAST(RouteID AS VARCHAR), '([0-9]+)', 1) <> ''
            THEN CAST(TRY_CAST(regexp_extract(CAST(RouteID AS VARCHAR), '([0-9]+)', 1) AS INTEGER) AS VARCHAR)
            ELSE NULL
        END AS route_key,
        TRY_CAST(BeginPoint AS DOUBLE) AS begin_point,
        TRY_CAST(EndPoint AS DOUBLE) AS end_point,
        TRY_CAST(SectionLength AS DOUBLE) AS section_length,
        TRIM(CAST(DESC_ AS VARCHAR)) AS segment_description,
        TRY_CAST(AADT2018 AS DOUBLE) AS aadt2018,
        TRY_CAST(AADT2019 AS DOUBLE) AS aadt2019,
        TRY_CAST(AADT2020 AS DOUBLE) AS aadt2020,
        TRY_CAST(AADT2021 AS DOUBLE) AS aadt2021,
        TRY_CAST(AADT2022 AS DOUBLE) AS aadt2022,
        TRY_CAST(AADT2023 AS DOUBLE) AS aadt2023,
        TRY_CAST(AADT2024 AS DOUBLE) AS aadt2024
    FROM bronze_aadt
)
SELECT segment_object_id, station, route_id_raw, route_key, begin_point, end_point, section_length, segment_description, 2018 AS analysis_year, 2018 AS aadt_year, aadt2018 AS aadt FROM base
UNION ALL
SELECT segment_object_id, station, route_id_raw, route_key, begin_point, end_point, section_length, segment_description, 2019, 2019, aadt2019 FROM base
UNION ALL
SELECT segment_object_id, station, route_id_raw, route_key, begin_point, end_point, section_length, segment_description, 2020, 2020, aadt2020 FROM base
UNION ALL
SELECT segment_object_id, station, route_id_raw, route_key, begin_point, end_point, section_length, segment_description, 2021, 2021, aadt2021 FROM base
UNION ALL
SELECT segment_object_id, station, route_id_raw, route_key, begin_point, end_point, section_length, segment_description, 2022, 2022, aadt2022 FROM base
UNION ALL
SELECT segment_object_id, station, route_id_raw, route_key, begin_point, end_point, section_length, segment_description, 2023, 2023, aadt2023 FROM base
UNION ALL
SELECT segment_object_id, station, route_id_raw, route_key, begin_point, end_point, section_length, segment_description, 2024, 2024, aadt2024 FROM base
UNION ALL
-- 2025 crashes use the latest currently published unrounded AADT field as an explicit proxy.
SELECT segment_object_id, station, route_id_raw, route_key, begin_point, end_point, section_length, segment_description, 2025, 2024, aadt2024 FROM base;

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
