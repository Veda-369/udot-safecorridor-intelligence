CREATE OR REPLACE TABLE gold_severe_crash_points AS
SELECT
    crash_id,
    crash_year,
    county_name,
    region_name,
    main_road_name,
    route_raw,
    route_key,
    milepoint,
    severity,
    latitude,
    longitude,
    speed_related_flag,
    dui_flag,
    distracted_driving_flag,
    roadway_departure_flag
FROM silver_crashes
WHERE severe_crash_flag = 1
  AND latitude BETWEEN 36.8 AND 42.2
  AND longitude BETWEEN -114.3 AND -108.7;
