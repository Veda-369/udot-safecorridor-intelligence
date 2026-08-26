from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_current_year_monitor_files_are_wired():
    assert (ROOT / "phase3c_current_year_monitor.py").exists()

    workflow = (ROOT / ".github" / "workflows" / "pipeline.yml").read_text(
        encoding="utf-8"
    )
    assert "phase3c_current_year_monitor.py" in workflow
    assert 'UDOT_CRASH_MAX_YEAR: "2025"' not in workflow


def test_config_uses_completed_year_default():
    config = (ROOT / "src" / "config.py").read_text(encoding="utf-8")
    assert "CALENDAR_CURRENT_YEAR - 1" in config
    assert "CURRENT_MONITOR_YEAR" in config
    assert "CURRENT_CRASH_SERVICE_URL" in config


def test_dashboard_has_dynamic_ytd_monitor():
    app = (ROOT / "dashboard" / "app.py").read_text(encoding="utf-8")
    assert "YTD Monitor" in app
    assert "current_year_crashes.parquet" in app
    assert "Rollover rule" in app


def test_crash_layer_name_pattern_supports_legacy_and_current_udot_formats():
    from src.ingestion.crashes import YEAR_PATTERN

    samples = {
        "Crash Locations 2018": 2018,
        "Crash Locations 2025": 2025,
        "2026 Crash Locations": 2026,
    }

    for name, expected_year in samples.items():
        match = YEAR_PATTERN.fullmatch(name)
        assert match is not None, name
        assert int(match.group(1) or match.group(2)) == expected_year
