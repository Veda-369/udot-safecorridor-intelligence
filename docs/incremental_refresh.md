# Incremental Refresh Design

## Objective

Avoid repeatedly downloading all completed crash years while preserving correctness when UDOT adds, corrects, or removes crash records.

## Persistent cache

The pipeline stores canonical raw crash snapshots under:

```text
data/cache/crashes/
  crashes_2018.parquet
  crashes_2019.parquet
  ...
  crashes_<current-year>.parquet
  incremental_state.json
```

`data/cache/` is gitignored. In GitHub Actions it is persisted between successful runs with `actions/cache@v5`. The cache contains only public UDOT transportation data and no credentials or user data.

A missing/evicted cache is safe: the next run automatically performs the necessary full fetches and rebuilds it.

## Completed historical years

For every completed year, the pipeline performs cheap ArcGIS metadata/count checks before downloading records.

- Same source layer + same edit revision + same feature count: reuse the cached annual snapshot.
- Revision or feature count changed: refresh only that year.
- Newest completed year: force a full safety reconciliation every 30 days.
- Older archive years: force a full safety reconciliation every 180 days.
- `UDOT_FORCE_FULL_CRASH_REFRESH=true`: force all years to refresh.

The periodic safety reconciliations protect against a same-count record correction that a service might not expose through a reliable edit timestamp.

## Current year

When the current-year layer is unchanged, the cached current-year snapshot is reused.

When it changes and a full reconciliation is not yet due, the pipeline performs two incremental queries:

1. `crash_datetime >= CURRENT_TIMESTAMP - INTERVAL '60' DAY`
2. `OBJECTID > <cached maximum OBJECTID>`

The recent 60-day portion of the cached dataset is removed and replaced by the newly queried recent window. The new-object query is then upserted by crash ID, falling back to OBJECTID when crash ID is absent.

This combination captures:

- newly entered crashes,
- corrections/deletions in the recent window,
- late-entered crashes whose occurrence date is older than the reconciliation window.

Every 30 days the current year is fully re-fetched as a safety reconciliation, which captures older corrections outside the rolling window.

If the incremental ArcGIS query is rejected or otherwise fails, the pipeline automatically falls back to a full current-year fetch.

## Calendar rollover

Example:

```text
During 2026
historical: 2018-2025
current:    2026 YTD

After rollover to 2027
2026 -> forced final full reconciliation -> historical
2027 -> new current-year YTD incremental cache
```

No hard-coded annual edit is required for crash-year rollover.

## State and observability

The cache state tracks per year:

- selected source service and layer ID,
- source edit revision,
- source feature count,
- cached row count,
- max OBJECTID,
- last full refresh timestamp,
- last incremental refresh timestamp.

Published reports show the refresh mode and network work performed:

```text
reports/incremental_historical_refresh.json
reports/incremental_current_refresh.json
```

Typical modes include:

```text
cache_reuse
full_refresh
incremental_reconcile
full_refresh_fallback
full_refresh_forced
```

## Configuration

Environment variables:

```text
UDOT_INCREMENTAL_REFRESH=true
UDOT_CURRENT_RECONCILIATION_DAYS=60
UDOT_CURRENT_FULL_RECONCILIATION_DAYS=30
UDOT_HISTORICAL_RECENT_RECONCILIATION_DAYS=30
UDOT_HISTORICAL_ARCHIVE_RECONCILIATION_DAYS=180
UDOT_FORCE_FULL_CRASH_REFRESH=false
```

## Important distinction

Incremental **ingestion** avoids unnecessary network downloads. The downstream DuckDB/SQL/spatial/statistical model is still rebuilt from the complete cached historical dataset so outputs remain deterministic and code/model changes are reflected even when the source data itself did not change.


## Dashboard freshness status

The Streamlit dashboard reads the committed refresh reports and displays a Utah-styled Data Freshness panel with:

- last successful analytical refresh, converted to America/Denver;
- next scheduled GitHub Actions refresh (Monday 10:17 UTC, rendered in Utah local time);
- current-year refresh mode (`cache_reuse`, `incremental_reconcile`, full reconciliation, or fallback);
- current refresh network-row count when available; and
- historical cache reuse vs refreshed-year counts.

Manual GitHub Actions runs remain supported; the next scheduled time always reflects the weekly cron schedule rather than predicting a manual run.
