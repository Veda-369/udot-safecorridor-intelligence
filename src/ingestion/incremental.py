from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import (
    CRASH_CACHE_SCHEMA_VERSION,
    CRASH_CACHE_DIR,
    CURRENT_FULL_RECONCILIATION_DAYS,
    CURRENT_RECONCILIATION_DAYS,
    FORCE_FULL_CRASH_REFRESH,
    HISTORICAL_ARCHIVE_RECONCILIATION_DAYS,
    HISTORICAL_RECENT_RECONCILIATION_DAYS,
    INCREMENTAL_REFRESH_ENABLED,
    PATHS,
)
from src.ingestion.arcgis import ArcGISError, layer_metadata, query_feature_count
from src.ingestion.crashes import (
    CrashLayer,
    discover_crash_layers,
    extract_crash_layer,
)

LOGGER = logging.getLogger(__name__)


@dataclass
class IncrementalLoad:
    frame: pd.DataFrame
    stats: dict[str, Any]
    layer: CrashLayer | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _utc_now().isoformat()


def _year_cache_path(year: int) -> Path:
    return CRASH_CACHE_DIR / f"crashes_{int(year)}.parquet"


def _empty_state() -> dict[str, Any]:
    return {
        "schema_version": CRASH_CACHE_SCHEMA_VERSION,
        "active_current_year": None,
        "years": {},
    }


def load_state() -> dict[str, Any]:
    path = PATHS.incremental_state_json
    if not path.exists():
        return _empty_state()
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        LOGGER.warning("Incremental state is unreadable; rebuilding cache state.")
        return _empty_state()
    if state.get("schema_version") != CRASH_CACHE_SCHEMA_VERSION:
        LOGGER.info("Incremental cache schema changed; ignoring prior state metadata.")
        return _empty_state()
    state.setdefault("years", {})
    return state


def save_state(state: dict[str, Any]) -> None:
    CRASH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    state["schema_version"] = CRASH_CACHE_SCHEMA_VERSION
    PATHS.incremental_state_json.write_text(
        json.dumps(state, indent=2, default=str),
        encoding="utf-8",
    )


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _layer_url(layer: CrashLayer) -> str:
    return f"{layer.service_url}/{layer.layer_id}"


def _metadata_revision(metadata: dict[str, Any]) -> int | str | None:
    editing = metadata.get("editingInfo") or {}
    candidates = (
        editing.get("dataLastEditDate"),
        editing.get("lastEditDate"),
        metadata.get("dataLastEditDate"),
        metadata.get("lastEditDate"),
        metadata.get("serviceItemId"),
    )
    for value in candidates:
        if value not in (None, ""):
            return value
    return None


def layer_signature(layer: CrashLayer) -> dict[str, Any]:
    url = _layer_url(layer)
    metadata = layer_metadata(url)
    count = query_feature_count(url)
    return {
        "source": layer.source,
        "service_url": layer.service_url,
        "layer_id": int(layer.layer_id),
        "revision": _metadata_revision(metadata),
        "feature_count": int(count),
    }


def _same_source(entry: dict[str, Any], signature: dict[str, Any]) -> bool:
    return (
        entry.get("source") == signature.get("source")
        and entry.get("service_url") == signature.get("service_url")
        and int(entry.get("layer_id", -1)) == int(signature.get("layer_id", -2))
    )


def _same_signature(entry: dict[str, Any], signature: dict[str, Any]) -> bool:
    if not _same_source(entry, signature):
        return False
    # Revision is the strongest signal. Count also detects appended/deleted rows.
    old_revision = entry.get("revision")
    new_revision = signature.get("revision")
    revision_same = (
        old_revision == new_revision
        if old_revision is not None and new_revision is not None
        else True
    )
    return revision_same and int(entry.get("feature_count", -1)) == int(
        signature.get("feature_count", -2)
    )


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _full_refresh_due(entry: dict[str, Any], max_age_days: int) -> bool:
    last = _parse_iso(entry.get("last_full_refresh_utc"))
    if last is None:
        return True
    return (_utc_now() - last) >= timedelta(days=max_age_days)


def _max_objectid(frame: pd.DataFrame) -> int | None:
    if "OBJECTID" not in frame.columns or frame.empty:
        return None
    values = pd.to_numeric(frame["OBJECTID"], errors="coerce").dropna()
    return int(values.max()) if not values.empty else None


def _cache_entry(
    layer: CrashLayer,
    signature: dict[str, Any],
    frame: pd.DataFrame,
    *,
    last_full_refresh_utc: str | None,
    last_incremental_refresh_utc: str | None,
) -> dict[str, Any]:
    return {
        **signature,
        "year": int(layer.year),
        "row_count": int(len(frame)),
        "max_objectid": _max_objectid(frame),
        "last_full_refresh_utc": last_full_refresh_utc,
        "last_incremental_refresh_utc": last_incremental_refresh_utc,
        "last_checked_utc": _iso_now(),
    }


def _read_cache(year: int) -> pd.DataFrame:
    return pd.read_parquet(_year_cache_path(year))


def _write_cache(year: int, frame: pd.DataFrame) -> None:
    CRASH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(_year_cache_path(year), index=False)


def _full_fetch_year(layer: CrashLayer) -> pd.DataFrame:
    frame = extract_crash_layer(layer)
    _write_cache(layer.year, frame)
    return frame


def _raw_datetime_utc(series: pd.Series) -> pd.Series:
    # Current FeatureServer uses TimestampOffset ISO strings. Coerce any odd
    # values to NaT so cache replacement stays fail-safe.
    return pd.to_datetime(series, errors="coerce", utc=True, format="mixed")


def _merge_current_increment(
    cached: pd.DataFrame,
    rolling: pd.DataFrame,
    new_rows: pd.DataFrame,
    *,
    reconciliation_days: int,
) -> pd.DataFrame:
    """Replace the recent window and upsert appended/late-entered rows."""
    base = cached.copy()
    if not base.empty and "CRASH_DATETIME" in base.columns:
        parsed = _raw_datetime_utc(base["CRASH_DATETIME"])
        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=reconciliation_days)
        base = base.loc[parsed.isna() | (parsed < cutoff)].copy()

    parts = [df for df in (base, rolling, new_rows) if df is not None and not df.empty]
    if not parts:
        return cached.iloc[0:0].copy()

    merged = pd.concat(parts, ignore_index=True, sort=False)
    merged["__order"] = range(len(merged))

    crash_id = pd.to_numeric(merged.get("CRASH_ID"), errors="coerce")
    object_id = pd.to_numeric(merged.get("OBJECTID"), errors="coerce")
    keys: list[str] = []
    for idx, (cid, oid) in enumerate(zip(crash_id, object_id)):
        if pd.notna(cid):
            keys.append(f"crash:{int(cid)}")
        elif pd.notna(oid):
            keys.append(f"oid:{int(oid)}")
        else:
            keys.append(f"row:{idx}")
    merged["__key"] = keys
    merged = (
        merged.sort_values("__order")
        .drop_duplicates(subset=["__key"], keep="last")
        .drop(columns=["__order", "__key"])
        .reset_index(drop=True)
    )
    return merged


def load_historical_crashes(
    min_year: int,
    max_year: int,
    *,
    current_calendar_year: int,
) -> IncrementalLoad:
    """Materialize completed historical years with per-year cache reuse.

    A cached historical year is reused when the source layer revision/count is
    unchanged. If metadata changes, only that year's layer is fetched again.
    On calendar rollover, the just-completed prior current year is forced
    through one final full reconciliation before it becomes historical.
    """
    layers = discover_crash_layers(min_year, max_year, prefer_current_service=False)
    if not layers:
        raise RuntimeError(f"No crash layers discovered for {min_year}-{max_year}.")

    state = load_state()
    previous_current_year = state.get("active_current_year")
    rollover_year = (
        int(previous_current_year)
        if previous_current_year is not None
        and int(previous_current_year) != int(current_calendar_year)
        and min_year <= int(previous_current_year) <= max_year
        else None
    )

    frames: list[pd.DataFrame] = []
    year_stats: list[dict[str, Any]] = []
    years_state = state.setdefault("years", {})

    for layer in layers:
        key = str(layer.year)
        cache_path = _year_cache_path(layer.year)
        entry = dict(years_state.get(key) or {})
        signature = layer_signature(layer)
        reconcile_days = (
            HISTORICAL_RECENT_RECONCILIATION_DAYS
            if layer.year == max_year
            else HISTORICAL_ARCHIVE_RECONCILIATION_DAYS
        )
        periodic_full_due = _full_refresh_due(entry, reconcile_days)
        force = (
            FORCE_FULL_CRASH_REFRESH
            or layer.year == rollover_year
            or periodic_full_due
        )

        if (
            INCREMENTAL_REFRESH_ENABLED
            and not force
            and cache_path.exists()
            and _same_signature(entry, signature)
        ):
            frame = _read_cache(layer.year)
            mode = "cache_reuse"
            fetched_rows = 0
            LOGGER.info("Historical year %s unchanged; reusing %s cached rows", layer.year, len(frame))
        else:
            frame = _full_fetch_year(layer)
            mode = "full_refresh"
            fetched_rows = len(frame)
            LOGGER.info("Historical year %s refreshed (%s rows)", layer.year, len(frame))

        last_full = _iso_now() if mode == "full_refresh" else entry.get("last_full_refresh_utc")
        years_state[key] = _cache_entry(
            layer,
            signature,
            frame,
            last_full_refresh_utc=last_full,
            last_incremental_refresh_utc=entry.get("last_incremental_refresh_utc"),
        )
        frames.append(frame)
        year_stats.append(
            {
                "year": layer.year,
                "mode": mode,
                "cached_rows": int(len(frame)),
                "network_rows_fetched": int(fetched_rows),
                "source_revision": signature.get("revision"),
                "source_feature_count": signature.get("feature_count"),
                "rollover_final_reconciliation": bool(layer.year == rollover_year),
                "periodic_reconciliation_days": int(reconcile_days),
                "periodic_full_due": bool(periodic_full_due),
            }
        )

    save_state(state)
    combined = pd.concat(frames, ignore_index=True, sort=False)
    stats = {
        "status": "success",
        "generated_at_utc": _iso_now(),
        "incremental_enabled": bool(INCREMENTAL_REFRESH_ENABLED),
        "historical_year_min": int(min_year),
        "historical_year_max": int(max_year),
        "rollover_finalized_year": rollover_year,
        "network_rows_fetched": int(sum(x["network_rows_fetched"] for x in year_stats)),
        "combined_rows": int(len(combined)),
        "years": year_stats,
    }
    _write_report(PATHS.incremental_historical_json, stats)
    return IncrementalLoad(combined, stats)


def load_current_year_crashes(year: int) -> IncrementalLoad:
    """Refresh current-year crashes with rolling reconciliation + appended rows.

    Strategy when the source changed:
      * full fetch on first run, source switch, cache shrink, or every configured
        full-reconciliation interval;
      * otherwise re-fetch the recent crash-date window and query OBJECTIDs newer
        than the cached max; replace the recent window and upsert new/late rows.

    If any incremental query is rejected by ArcGIS, the function falls back to a
    full current-year refresh rather than risking an incomplete cache.
    """
    layers = discover_crash_layers(year, year, prefer_current_service=True)
    if not layers:
        stats = {
            "status": "current_layer_unavailable",
            "generated_at_utc": _iso_now(),
            "year": int(year),
            "network_rows_fetched": 0,
        }
        _write_report(PATHS.incremental_current_json, stats)
        state = load_state()
        state["active_current_year"] = int(year)
        save_state(state)
        return IncrementalLoad(pd.DataFrame(), stats, None)

    layer = layers[0]
    signature = layer_signature(layer)
    state = load_state()
    years_state = state.setdefault("years", {})
    key = str(year)
    entry = dict(years_state.get(key) or {})
    cache_path = _year_cache_path(year)

    source_changed = bool(entry) and not _same_source(entry, signature)
    cached = _read_cache(year) if cache_path.exists() else pd.DataFrame()
    source_shrank = (
        not cached.empty
        and int(signature.get("feature_count", 0)) < int(entry.get("feature_count", len(cached)))
    )
    signature_unchanged = bool(entry) and _same_signature(entry, signature)
    full_due = _full_refresh_due(entry, CURRENT_FULL_RECONCILIATION_DAYS)

    mode: str
    fetched_rows = 0
    rolling_rows = 0
    new_rows_count = 0
    fallback_reason: str | None = None

    if not INCREMENTAL_REFRESH_ENABLED or FORCE_FULL_CRASH_REFRESH:
        current = _full_fetch_year(layer)
        mode = "full_refresh_forced"
        fetched_rows = len(current)
    elif cached.empty or source_changed or source_shrank or full_due:
        current = _full_fetch_year(layer)
        mode = "full_refresh"
        fetched_rows = len(current)
    elif signature_unchanged:
        current = cached
        mode = "cache_reuse"
    else:
        max_oid = _max_objectid(cached)
        try:
            rolling_where = (
                f"crash_datetime >= CURRENT_TIMESTAMP - INTERVAL "
                f"'{int(CURRENT_RECONCILIATION_DAYS)}' DAY"
            )
            rolling = extract_crash_layer(layer, where=rolling_where)
            if max_oid is None:
                new_rows = pd.DataFrame()
            else:
                new_rows = extract_crash_layer(layer, where=f"OBJECTID > {int(max_oid)}")
            current = _merge_current_increment(
                cached,
                rolling,
                new_rows,
                reconciliation_days=CURRENT_RECONCILIATION_DAYS,
            )
            _write_cache(year, current)
            rolling_rows = len(rolling)
            new_rows_count = len(new_rows)
            fetched_rows = rolling_rows + new_rows_count
            mode = "incremental_reconcile"
        except (ArcGISError, ValueError, TypeError) as exc:
            LOGGER.warning("Incremental current-year query failed; using full refresh: %s", exc)
            fallback_reason = str(exc)
            current = _full_fetch_year(layer)
            mode = "full_refresh_fallback"
            fetched_rows = len(current)

    now = _iso_now()
    last_full = (
        now
        if mode.startswith("full_refresh")
        else entry.get("last_full_refresh_utc")
    )
    last_incremental = (
        now
        if mode == "incremental_reconcile"
        else entry.get("last_incremental_refresh_utc")
    )
    years_state[key] = _cache_entry(
        layer,
        signature,
        current,
        last_full_refresh_utc=last_full,
        last_incremental_refresh_utc=last_incremental,
    )
    state["active_current_year"] = int(year)
    save_state(state)

    stats = {
        "status": "success",
        "generated_at_utc": now,
        "year": int(year),
        "mode": mode,
        "incremental_enabled": bool(INCREMENTAL_REFRESH_ENABLED),
        "reconciliation_days": int(CURRENT_RECONCILIATION_DAYS),
        "full_reconciliation_days": int(CURRENT_FULL_RECONCILIATION_DAYS),
        "network_rows_fetched": int(fetched_rows),
        "rolling_rows_fetched": int(rolling_rows),
        "new_objectid_rows_fetched": int(new_rows_count),
        "cached_rows_after_refresh": int(len(current)),
        "source_revision": signature.get("revision"),
        "source_feature_count": signature.get("feature_count"),
        "fallback_reason": fallback_reason,
    }
    _write_report(PATHS.incremental_current_json, stats)
    return IncrementalLoad(current, stats, layer)
