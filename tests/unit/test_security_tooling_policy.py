import json
import tomllib
from configparser import ConfigParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_bandit_baseline_carries_no_suppressed_findings() -> None:
    # Accepted findings must be suppressed inline (`# nosec <id>` with a
    # justification) at the call site, like the existing B608 comments in
    # clickhouse_backend.py — not parked in the baseline sidecar. Baseline
    # entries are keyed by (test_id, filename, line_number), so any line
    # shift above a baselined call silently turns the accepted finding into
    # a "new" one and fails Security Scan on an unrelated edit (audit F-5).
    baseline = json.loads((ROOT / ".bandit-baseline.json").read_text(encoding="utf-8"))

    assert baseline["results"] == []


def test_sql_injection_checks_are_not_globally_suppressed() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    ruff_ignores = set(pyproject["tool"]["ruff"]["lint"].get("ignore", []))

    bandit = ConfigParser()
    bandit.read(ROOT / ".bandit", encoding="utf-8")
    bandit_skips = {
        skip.strip()
        for skip in bandit.get("bandit", "skips", fallback="").split(",")
        if skip.strip()
    }

    assert "S608" not in ruff_ignores
    assert "B608" not in bandit_skips
