import tomllib
from configparser import ConfigParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


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
