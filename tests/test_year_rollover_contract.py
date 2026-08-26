from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def test_current_year_monitor_files_are_wired():
    assert (ROOT / "phase3c_current_year_monitor.py").exists()

    workflow = (ROOT / ".github" / "workflows" / "pipeline.yml").read_text(
        encoding="utf-8"
    )
    assert "phase3c_current_year_monitor.py" in workflow
    assert 'UDOT_CRASH_MAX_YEAR: "2025"' not in workflow
    assert "python -m pytest -q" in workflow


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


def test_current_parser_handles_timestamp_offset_and_preserves_utah_date():
    from phase3c_current_year_monitor import _parse_datetime, _to_utah_local

    parsed = _parse_datetime(
        pd.Series(["2026-08-25T23:45:00-06:00"])
    )
    local = _to_utah_local(parsed)

    assert parsed.notna().all()
    assert str(local.dt.date.iloc[0]) == "2026-08-25"


def test_current_parser_handles_epoch_ms_and_seconds():
    from phase3c_current_year_monitor import _parse_datetime

    # Both represent 2026-01-01 00:00:00 UTC.
    seconds = 1767225600
    milliseconds = seconds * 1000

    parsed = _parse_datetime(pd.Series([seconds, milliseconds]))

    assert parsed.notna().all()
    assert parsed.iloc[0] == parsed.iloc[1]


def test_current_parser_rejects_overflow_numeric_values():
    from phase3c_current_year_monitor import _parse_datetime

    parsed = _parse_datetime(
        pd.Series([10**30, -10**30, None])
    )
    assert parsed.isna().all()


def test_current_parser_handles_mixed_values():
    from phase3c_current_year_monitor import _parse_datetime

    parsed = _parse_datetime(
        pd.Series(
            [
                "2026-03-01T10:30:00-07:00",
                1767225600000,
                "not-a-date",
                None,
            ]
        )
    )
    assert parsed.notna().sum() == 2


def test_normalizer_preserves_multiple_missing_ids():
    from phase3c_current_year_monitor import _normalize_current

    raw = pd.DataFrame(
        {
            "CRASH_ID": [None, None],
            "CRASH_DATETIME": [
                "2026-05-01T10:00:00-06:00",
                "2026-05-02T10:00:00-06:00",
            ],
            "CURRENT_AS_OF_DATE": [
                "2026-05-03T00:00:00-06:00",
                "2026-05-03T00:00:00-06:00",
            ],
            "COUNTY_NAME": ["Salt Lake", "Utah"],
            "ROUTE": ["15", "89"],
            "CRASH_SEVERITY_DESC": ["No Injury/PDO", "Fatal"],
        }
    )

    normalized = _normalize_current(raw)
    assert len(normalized) == 2
    assert normalized["crash_id"].isna().sum() == 2


def test_normalizer_tolerates_missing_datetime_column():
    from phase3c_current_year_monitor import _normalize_current

    raw = pd.DataFrame(
        {
            "CRASH_ID": [1],
            "COUNTY_NAME": ["Salt Lake"],
            "ROUTE": ["15"],
            "CRASH_SEVERITY_DESC": ["Fatal"],
        }
    )

    normalized = _normalize_current(raw)
    assert len(normalized) == 1
    assert normalized["crash_datetime"].isna().all()
    assert normalized["valid_crash_date_flag"].eq(0).all()


def test_dynamic_aadt_rollover_uses_latest_prior_year_as_proxy():
    from src.ingestion.aadt import build_aadt_analysis_frame

    raw = pd.DataFrame(
        {
            "OBJECTID": [1],
            "Station": ["A"],
            "RouteID": ["0015"],
            "BeginPoint": [0.0],
            "EndPoint": [5.0],
            "SectionLength": [5.0],
            "DESC_": ["Example"],
            "AADT2023": [10000],
            "AADT2024": [11000],
        }
    )

    result = build_aadt_analysis_frame(raw, 2024, 2026)
    mapping = (
        result[["analysis_year", "aadt_year"]]
        .drop_duplicates()
        .sort_values("analysis_year")
        .set_index("analysis_year")["aadt_year"]
        .to_dict()
    )

    assert mapping == {
        2024: 2024,
        2025: 2024,
        2026: 2024,
    }
