"""Shape tests for the CI lint gate scope.

The 2026-06-03 audit (F-2) found `scripts/` drifting outside the Ruff
gate: 20 lint errors and 12 unformatted files in release/benchmark/security
tooling that CI never checked. The lint job must cover `scripts/` alongside
`src/` and `tests/` so operational tooling cannot silently rot again.
"""

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]

LINTED_PATHS = ("src/", "tests/", "scripts/")


def _lint_steps() -> list[dict]:
    path = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    return workflow["jobs"]["lint"]["steps"]


def _run_text(steps: list[dict], prefix: str) -> str:
    matches = [
        str(step.get("run", "")) for step in steps if str(step.get("run", "")).startswith(prefix)
    ]
    assert matches, f"ci.yml lint job must keep a `{prefix}` step"
    return matches[0]


def test_ruff_check_covers_scripts():
    run = _run_text(_lint_steps(), "ruff check")
    for linted in LINTED_PATHS:
        assert linted in run, f"ruff check must cover {linted!r}"


def test_ruff_format_check_covers_scripts():
    run = _run_text(_lint_steps(), "ruff format --check")
    for linted in LINTED_PATHS:
        assert linted in run, f"ruff format --check must cover {linted!r}"
