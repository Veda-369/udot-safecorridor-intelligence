from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_required_project_files_exist():
    required = [
        ROOT / "src" / "pipeline.py",
        ROOT / "src" / "ingestion" / "crashes.py",
        ROOT / "src" / "ingestion" / "aadt.py",
        ROOT / "src" / "ingestion" / "incremental.py",
        ROOT / "sql" / "01_silver_crashes.sql",
        ROOT / "sql" / "02_silver_aadt.sql",
        ROOT / "sql" / "03_gold_risk.sql",
        ROOT / "dashboard" / "app.py",
        ROOT / ".github" / "workflows" / "pipeline.yml",
    ]
    assert all(path.exists() for path in required)


def test_disclaimer_present():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "not affiliated" in readme.lower()
    assert "proof-of-concept" in readme.lower()
