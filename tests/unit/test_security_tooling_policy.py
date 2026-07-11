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
    # ADR 0006 Phase 1a (reviewed 2026-07-02): the ClickHouse pipeline sink
    # interpolates _quote_literal-escaped ids into its aggregate-recompute
    # reads (the backend transpile re-escapes them structurally), and
    # QueryEngine.fetch_pipeline_events interpolates only schema-probe column
    # names plus _quote_literal-escaped values on the non-binding backend path
    # — the journal scan moved there from stream.py / webhook_dispatcher.py,
    # whose sites are gone; clickhouse_backend gained the insert_rows header
    # (identifiers regex-validated).
    # S6 (reviewed 2026-07-09): +1 site — ClickHouseSink.existing_event_ids, the
    # serving bridge's idempotency guard. It interpolates _quote_literal-escaped
    # `event_id`s that originate in Kafka payloads, i.e. attacker-influenced if
    # a producer is compromised. Contained by the same mechanism as the other
    # two sites and pinned by
    # test_serving_bridge.py::test_hostile_event_id_cannot_escape_the_guard_literal,
    # which asserts structurally (parse the translated SQL as ClickHouse) that
    # quote/backslash/newline/UNION payloads stay one statement, one literal, and
    # round-trip to the original value. ClickHouse's `execute(params=...)` is a
    # documented no-op, so binding is not an option on this backend.
    "src/processing/clickhouse_sink.py": 3,
    # audit P0-3 (reviewed 2026-07-11): the five journal sites moved OUT of
    # routers/lineage.py (1) and routers/slo.py (4) and into
    # semantic_layer/journal.py, which reads pipeline_events through the active
    # backend instead of a private DuckDB cursor. Same surface, one place. Every
    # interpolated fragment is an identifier taken from a live schema probe
    # (`table_columns`) against a fixed allowlist — the time column, the
    # nullable-column fallbacks — plus the SLO quantile, a float from
    # config/slo.yaml formatted with :g. Values never interpolate: `_value()`
    # binds them as `?` on DuckDB and _quote_literal-escapes them on ClickHouse,
    # whose execute(params=...) is a documented no-op. So `entity_id` from the
    # URL path still binds exactly as it did before the move.
    "src/serving/semantic_layer/journal.py": 5,
    # ADR 0010 slice 5 (reviewed 2026-07-03): _replace_record_set interpolates
    # only its `table` argument, a module literal at exactly two call sites
    # (save_webhook_registrations / save_alert_rules); every value binds via
    # %s. All other adapter SQL is literal (the lease fragment is inlined and
    # the tenant/reason filters branch into full literal statements).
    "src/serving/control_plane/postgres.py": 3,
    # D2 (reviewed 2026-07-04): the new orders.status stage-trail seed INSERT
    # in initialize_demo_data follows the same pattern as the file's other six
    # seed-block sites — a static f-string of hardcoded demo ids and
    # ts()-formatted (trusted, generated) timestamps, no request-derived
    # input.
    "src/serving/backends/clickhouse_backend.py": 8,
    "src/serving/backends/duckdb_backend.py": 2,
    "src/serving/semantic_layer/nl_engine.py": 6,
    "src/serving/semantic_layer/query/engine.py": 1,
    # D3 (reviewed 2026-07-04): fetch_orders_by_status's new stuck-orders
    # bulk read follows get_entity's existing pattern in this same file — the
    # table name comes from the catalog allowlist (_qualify_table), and every
    # status value binds as a query param on DuckDB or is
    # _quote_literal-escaped on the non-binding ClickHouse path.
    # audit P0-3 (reviewed 2026-07-11): +1 site — scan_entity_rows, the bulk
    # entity read the search index used to run on the raw DuckDB connection.
    # Interpolates a catalog-defined table name and an int() limit; no values.
    # search_index.py's own site is gone with it.
    "src/serving/semantic_layer/query/entity_queries.py": 5,
    "src/serving/semantic_layer/query/nl_queries.py": 3,
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
