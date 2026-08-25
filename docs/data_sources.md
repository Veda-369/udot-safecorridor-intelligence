# Data Sources

## 1. UDOT Crash Locations

ArcGIS MapServer:

`https://central.udot.utah.gov/central/rest/services/TrafficAndSafety/Crash_Locations/MapServer`

Project use:

- Crash identifiers and date/time
- County / UDOT region
- Route and milepoint
- Severity
- Weather / lighting / roadway surface
- Fatalities and serious injuries
- Behavioral/event flags such as speeding, DUI, distraction, roadway departure
- Geographic point coordinates

Source notes retained in this project:

- UDOT states the public service has personally identifying information removed.
- The service is refreshed nightly.
- Recent crashes may be delayed or later corrected.
- Source information should be field-verified before use on an actual transportation project.

## 2. UDOT AADT 2024 Unrounded

ArcGIS FeatureServer layer:

`https://services.arcgis.com/pA2nEVnB6tquxgOW/ArcGIS/rest/services/AADT2024_Unrounded/FeatureServer/3`

Project use:

- RouteID
- BeginPoint / EndPoint
- SectionLength
- Historical unrounded AADT fields

UDOT's service documentation notes that unrounded AADT is preferred when statistical calculations such as VMT are required.

## 3. Optional later POC: UDOT Traffic API

`https://udottraffic.utah.gov/developers/doc`

Potential use:

- Current road conditions
- Weather stations
- Traffic events / alerts

This API requires a developer key and is therefore deliberately excluded from the zero-secret core pipeline.
