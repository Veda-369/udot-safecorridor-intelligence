from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def test_incremental_module_and_cache_wiring_exist():
    assert (ROOT / "src" / "ingestion" / "incremental.py").exists()
    workflow = (ROOT / ".github" / "workflows" / "pipeline.yml").read_text(
        encoding="utf-8"
    )
    assert "actions/cache@v5" in workflow
    assert "data/cache" in workflow
    assert "UDOT_INCREMENTAL_REFRESH" in workflow
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "data/cache/" in gitignore


def test_current_increment_replaces_recent_window_and_keeps_old_rows():
    from src.ingestion.incremental import _merge_current_increment

    now = pd.Timestamp.now(tz="UTC")
    old_date = (now - pd.Timedelta(days=120)).isoformat()
    recent_date = (now - pd.Timedelta(days=10)).isoformat()

    cached = pd.DataFrame(
        {
            "CRASH_ID": [1, 2],
            "OBJECTID": [10, 20],
            "CRASH_DATETIME": [old_date, recent_date],
            "COUNTY_NAME": ["OLD", "OLD_VALUE"],
        }
    )
    rolling = pd.DataFrame(
        {
            "CRASH_ID": [2],
            "OBJECTID": [20],
            "CRASH_DATETIME": [recent_date],
            "COUNTY_NAME": ["CORRECTED"],
        }
    )
    new_rows = pd.DataFrame(
        {
            "CRASH_ID": [3],
            "OBJECTID": [30],
            "CRASH_DATETIME": [recent_date],
            "COUNTY_NAME": ["NEW"],
        }
    )

    result = _merge_current_increment(
        cached,
        rolling,
        new_rows,
        reconciliation_days=60,
    ).sort_values("CRASH_ID")

    assert result["CRASH_ID"].tolist() == [1, 2, 3]
    assert result.loc[result["CRASH_ID"] == 1, "COUNTY_NAME"].iloc[0] == "OLD"
    assert result.loc[result["CRASH_ID"] == 2, "COUNTY_NAME"].iloc[0] == "CORRECTED"


def test_cache_signature_detects_revision_or_count_change():
    from src.ingestion.incremental import _same_signature

    entry = {
        "source": "nightly_featureserver",
        "service_url": "https://example.test/FeatureServer",
        "layer_id": 0,
        "revision": 100,
        "feature_count": 10,
    }
    same = dict(entry)
    changed_revision = dict(entry, revision=101)
    changed_count = dict(entry, feature_count=11)

    assert _same_signature(entry, same)
    assert not _same_signature(entry, changed_revision)
    assert not _same_signature(entry, changed_count)


def test_pipeline_uses_incremental_historical_loader():
    pipeline = (ROOT / "src" / "pipeline.py").read_text(encoding="utf-8")
    assert "load_historical_crashes" in pipeline
    assert "historical_incremental_refresh" in pipeline


def test_current_monitor_uses_incremental_current_loader():
    monitor = (ROOT / "phase3c_current_year_monitor.py").read_text(encoding="utf-8")
    assert "load_current_year_crashes" in monitor
    assert '"incremental_refresh": incremental_load.stats' in monitor


def test_historical_cache_hit_avoids_network_fetch(tmp_path, monkeypatch):
    import src.ingestion.incremental as inc
    from src.ingestion.crashes import CrashLayer

    cache_dir = tmp_path / "cache"
    report = tmp_path / "historical.json"
    state_path = cache_dir / "incremental_state.json"

    class DummyPaths:
        incremental_state_json = state_path
        incremental_historical_json = report
        incremental_current_json = tmp_path / "current.json"

    monkeypatch.setattr(inc, "CRASH_CACHE_DIR", cache_dir)
    monkeypatch.setattr(inc, "PATHS", DummyPaths())
    monkeypatch.setattr(inc, "INCREMENTAL_REFRESH_ENABLED", True)
    monkeypatch.setattr(inc, "FORCE_FULL_CRASH_REFRESH", False)

    layer = CrashLayer(
        year=2025,
        layer_id=1,
        service_url="https://example.test/FeatureServer",
        source="nightly_featureserver",
    )
    signature = {
        "source": layer.source,
        "service_url": layer.service_url,
        "layer_id": 1,
        "revision": 123,
        "feature_count": 1,
    }
    cache_dir.mkdir(parents=True)
    (cache_dir / "crashes_2025.parquet").touch()
    cached_frame = pd.DataFrame(
        {"CRASH_ID": [99], "OBJECTID": [1], "SOURCE_YEAR": [2025]}
    )
    monkeypatch.setattr(inc, "_read_cache", lambda year: cached_frame.copy())
    state_path.write_text(
        __import__("json").dumps(
            {
                "schema_version": inc.CRASH_CACHE_SCHEMA_VERSION,
                "active_current_year": 2026,
                "years": {
                    "2025": {
                        **signature,
                        "last_full_refresh_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(inc, "discover_crash_layers", lambda *a, **k: [layer])
    monkeypatch.setattr(inc, "layer_signature", lambda *a, **k: signature)

    def should_not_fetch(*args, **kwargs):
        raise AssertionError("network extraction should not occur on cache hit")

    monkeypatch.setattr(inc, "extract_crash_layer", should_not_fetch)

    result = inc.load_historical_crashes(2025, 2025, current_calendar_year=2026)
    assert result.stats["years"][0]["mode"] == "cache_reuse"
    assert result.stats["network_rows_fetched"] == 0
    assert len(result.frame) == 1


def test_rollover_forces_final_full_reconciliation(tmp_path, monkeypatch):
    import json
    import src.ingestion.incremental as inc
    from src.ingestion.crashes import CrashLayer

    cache_dir = tmp_path / "cache"
    report = tmp_path / "historical.json"
    state_path = cache_dir / "incremental_state.json"

    class DummyPaths:
        incremental_state_json = state_path
        incremental_historical_json = report
        incremental_current_json = tmp_path / "current.json"

    monkeypatch.setattr(inc, "CRASH_CACHE_DIR", cache_dir)
    monkeypatch.setattr(inc, "PATHS", DummyPaths())
    monkeypatch.setattr(inc, "INCREMENTAL_REFRESH_ENABLED", True)
    monkeypatch.setattr(inc, "FORCE_FULL_CRASH_REFRESH", False)

    layer = CrashLayer(
        year=2026,
        layer_id=0,
        service_url="https://example.test/FeatureServer",
        source="nightly_featureserver",
    )
    signature = {
        "source": layer.source,
        "service_url": layer.service_url,
        "layer_id": 0,
        "revision": 555,
        "feature_count": 1,
    }
    cache_dir.mkdir(parents=True)
    (cache_dir / "crashes_2026.parquet").touch()
    monkeypatch.setattr(
        inc,
        "_read_cache",
        lambda year: pd.DataFrame(
            {"CRASH_ID": [1], "OBJECTID": [1], "SOURCE_YEAR": [2026]}
        ),
    )
    state_path.write_text(
        json.dumps(
            {
                "schema_version": inc.CRASH_CACHE_SCHEMA_VERSION,
                "active_current_year": 2026,
                "years": {"2026": {**signature}},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(inc, "discover_crash_layers", lambda *a, **k: [layer])
    monkeypatch.setattr(inc, "layer_signature", lambda *a, **k: signature)
    monkeypatch.setattr(
        inc,
        "_full_fetch_year",
        lambda *a, **k: pd.DataFrame(
            {"CRASH_ID": [1, 2], "OBJECTID": [1, 2], "SOURCE_YEAR": [2026, 2026]}
        ),
    )

    result = inc.load_historical_crashes(2026, 2026, current_calendar_year=2027)
    assert result.stats["rollover_finalized_year"] == 2026
    assert result.stats["years"][0]["mode"] == "full_refresh"
    assert result.stats["network_rows_fetched"] == 2


def test_dashboard_exposes_refresh_freshness_status():
    app = (ROOT / "dashboard" / "app.py").read_text(encoding="utf-8")
    assert "DATA FRESHNESS" in app
    assert "LAST SUCCESSFUL REFRESH" in app
    assert "NEXT SCHEDULED REFRESH" in app
    assert "incremental_current_refresh.json" in app
    assert "incremental_historical_refresh.json" in app

