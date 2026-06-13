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
# "one careless edit away from a hole". This ratchet pins the EXACT COUNT of
# inline `# nosec B608` (interpolated SQL) suppressions per file: a NEW file, OR
# a new site inside an already-listed file, fails here and forces a review
# (route the query through `sql_guard` / parameter binding / `_quote_identifier`
# / `_quote_literal` instead, or bump the count deliberately). Shrinking a count
# is also a deliberate event — bind a site, then lower (or drop) the entry.
# Each site's safety rationale is documented in docs/security-audit.md, and the
# per-line justification comment is enforced by
# test_bandit_diff.test_nosec_comments_carry_reason.
_ALLOWED_B608_SITES = {
    "src/orchestration/dags/daily_batch.py": 1,
    "src/serving/api/routers/lineage.py": 1,
    "src/serving/api/routers/slo.py": 4,
    "src/serving/api/routers/stream.py": 1,
    "src/serving/api/webhook_dispatcher.py": 1,
    "src/serving/backends/clickhouse_backend.py": 6,
    "src/serving/backends/duckdb_backend.py": 2,
    "src/serving/semantic_layer/nl_engine.py": 6,
    "src/serving/semantic_layer/query/entity_queries.py": 3,
    "src/serving/semantic_layer/query/nl_queries.py": 2,
    "src/serving/semantic_layer/search_index.py": 1,
}


def _b608_counts_by_file() -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in (ROOT / "src").rglob("*.py"):
        n = path.read_text(encoding="utf-8").count("# nosec B608")
        if n:
            counts[path.relative_to(ROOT).as_posix()] = n
    return counts


def test_interpolated_sql_nosec_surface_is_pinned() -> None:
    found = _b608_counts_by_file()

    new_sites = sorted(set(found) - set(_ALLOWED_B608_SITES))
    assert not new_sites, (
        "New `# nosec B608` interpolated-SQL site(s) introduced in "
        f"{new_sites}. Route the query through sql_guard / parameter binding / "
        "_quote_identifier/_quote_literal, or add the file to "
        "_ALLOWED_B608_SITES with explicit review (A-4)."
    )

    bound_sites = sorted(set(_ALLOWED_B608_SITES) - set(found))
    assert not bound_sites, (
        f"{bound_sites} no longer carry `# nosec B608` — the dynamic-SQL surface "
        "shrank. Remove them from _ALLOWED_B608_SITES to keep the ratchet tight."
    )

    drifted = {
        path: (found[path], expected)
        for path, expected in _ALLOWED_B608_SITES.items()
        if path in found and found[path] != expected
    }
    assert not drifted, (
        "Interpolated-SQL `# nosec B608` count changed (file: (found, pinned)): "
        f"{drifted}. A new site inside an already-listed file must be reviewed "
        "for injection safety (docs/security-audit.md) and the count bumped "
        "deliberately, or the value bound so the count drops."
    )
