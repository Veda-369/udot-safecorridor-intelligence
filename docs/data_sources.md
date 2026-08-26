# Data Sources

## 1. UDOT Crash Locations — historical continuity service

ArcGIS MapServer:

`https://central.udot.utah.gov/central/rest/services/TrafficAndSafety/Crash_Locations/MapServer`

Project use:

- Completed historical crash years where available
- 2018 coverage retained for the historical model
- Crash identifier, date/time, county, route, severity and behavior flags
- Geographic crash coordinates

The production extractor prefers this validated source for completed years when the annual layer exists, then falls back to the nightly service for newer years.

## 2. UDOT Crash Locations — nightly/current-year service

ArcGIS FeatureServer:

`https://services.arcgis.com/pA2nEVnB6tquxgOW/ArcGIS/rest/services/Utah_Crash_Locations/FeatureServer`

Project use:

- Current calendar-year YTD monitoring
- Automatic discovery of newly published annual layers
- Future historical-year rollover when a completed year is not available in the legacy MapServer

UDOT states that this service has personal identifying information removed and is refreshed nightly. Recent crashes can be delayed, reviewed, corrected, or moved after initial entry. Current-year records are therefore treated as **preliminary YTD observations** rather than final historical records.

The code normalizes the newer service's lower-case/renamed fields (for example `route_id` and `beg_mileage`) to the canonical schema used by the historical pipeline.

## 3. UDOT AADT 2024 Unrounded

ArcGIS FeatureServer layer:

`https://services.arcgis.com/pA2nEVnB6tquxgOW/ArcGIS/rest/services/AADT2024_Unrounded/FeatureServer/3`

Project use:

- RouteID
- BeginPoint / EndPoint
- SectionLength
- Historical unrounded AADT fields
- VMT-based exposure calculations

The unrounded AADT source is used for statistical calculations such as VMT. The current project still uses the 2024 AADT publication as the exposure source; future work can add automatic discovery of newer AADT publications when UDOT releases them.

## 4. Official UDOT route geometry

UDOT Roads ArcGIS service:

`https://roads.udot.utah.gov/server/rest/services/Public/UDOT_Routes/MapServer/0/query`

Project use:

- Official route geometry
- Route aliases / IDs
- Begin and end mileage
- Spatial crash-to-route matching
- Spatially derived route milepoint / LRS position

The final corridor methodology does **not** treat the crash-source `START_ACCUM` field as a statewide route milepost. Crash coordinates are spatially matched to official route geometry instead.

## 5. Optional later POC: UDOT Traffic API

`https://udottraffic.utah.gov/developers/doc`

Potential use:

- Current road conditions
- Weather stations
- Traffic events / alerts

This API requires a developer key and is deliberately excluded from the zero-secret core pipeline.
