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


# A-4: the dynamic-SQL surface is safe *today* — identifiers are regex-bound,
# NL->SQL passes sqlglot validation in `sql_guard`, and table allowlists apply —
# but only because every call site validated its input. The report flags it as
# "one careless edit away from a hole". This ratchet pins the set of files
# allowed to carry an inline `# nosec B608` (interpolated SQL) suppression: a
# NEW file introducing interpolated SQL fails here and forces a review (route it
# through `sql_guard` / parameter binding / `_quote_identifier`/`_quote_literal`
# instead, or extend the allowlist deliberately). Shrinking the set is also a
# deliberate event — bind a site, then drop the file from the allowlist.
_ALLOWED_B608_FILES = frozenset(
    {
        "src/orchestration/dags/daily_batch.py",
        "src/serving/api/routers/lineage.py",
        "src/serving/api/routers/slo.py",
        "src/serving/api/routers/stream.py",
        "src/serving/api/webhook_dispatcher.py",
        "src/serving/backends/clickhouse_backend.py",
        "src/serving/backends/duckdb_backend.py",
        "src/serving/semantic_layer/nl_engine.py",
        "src/serving/semantic_layer/query/entity_queries.py",
        "src/serving/semantic_layer/query/nl_queries.py",
        "src/serving/semantic_layer/search_index.py",
    }
)


def _src_files_with_b608() -> set[str]:
    found: set[str] = set()
    for path in (ROOT / "src").rglob("*.py"):
        if "# nosec B608" in path.read_text(encoding="utf-8"):
            found.add(path.relative_to(ROOT).as_posix())
    return found


def test_interpolated_sql_nosec_surface_is_pinned() -> None:
    found = _src_files_with_b608()

    new_sites = sorted(found - _ALLOWED_B608_FILES)
    assert not new_sites, (
        "New `# nosec B608` interpolated-SQL site(s) introduced in "
        f"{new_sites}. Route the query through sql_guard / parameter binding / "
        "_quote_identifier/_quote_literal, or add the file to "
        "_ALLOWED_B608_FILES with explicit review (A-4)."
    )

    bound_sites = sorted(_ALLOWED_B608_FILES - found)
    assert not bound_sites, (
        f"{bound_sites} no longer carry `# nosec B608` — the dynamic-SQL surface "
        "shrank. Remove them from _ALLOWED_B608_FILES to keep the ratchet tight."
    )
