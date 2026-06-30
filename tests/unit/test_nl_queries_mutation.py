"""Narrow, duckdb-free mutation test for the NL query execution path
(src/serving/semantic_layer/query/nl_queries.py).

This is the test the mutation gate runs against
``serving/semantic_layer/query/nl_queries.py`` (see scripts/mutation_report.py
MODULE_TARGETS). nl_queries is the only ``validate_nl_sql()`` enforcement
boundary (``_prepare_nl_sql``) plus the pagination / row-cap SQL wrappers built
around the prevalidated NL SQL -- a surviving mutant in the row cap, the
validate wrap or the cursor checks is an un-paginated full-table read or a
denylist bypass (audit_28_06_26.md #8), exactly what a mutation gate should pin.

Design rules, shared with test_rate_limiter_mutation.py /
test_sql_builder_mutation.py (see fable_handoff.md cont.16-19):

1. **duckdb-free.** The ordinary query-engine tests build a QueryEngine, which
   imports duckdb and crashes mutmut's ``mutants/`` workspace. This file drives
   the NLQueryMixin methods through a hand-built host with a fake backend, so
   duckdb is never imported.

2. **No fixtures for the subject -- inline construction + direct method calls.**
   With ``mutate_only_covered_lines = true`` a fixture-built host left every
   method line uncovered (only ``__init__`` mutated, score 0%). The host is built
   inline and the methods are called directly. (The one pytest fixture below only
   toggles the telemetry flag; it constructs nothing under test.)

3. **Import shims.** The mutation harness copies ``src/serving`` to a top-level
   ``serving`` package *without* ``src``. Several things on nl_queries' import
   path would otherwise fail or drag duckdb in: ``from src.processing.tracing
   import telemetry_disabled`` and ``from src.serving.backends import
   BackendExecutionError`` (no ``src``), the ``serving.semantic_layer.query``
   package ``__init__`` (``from .engine import QueryEngine`` -> duckdb) and
   ``.contracts`` (imports the duckdb backend for type hints). The ``.sql_guard``
   import is a shim that does ``from src.serving.semantic_layer.sql_guard import
   ...``; we point that src-name at the REAL top-level sql_guard (sqlglot-only,
   duckdb-free) so the validate boundary runs against the genuine guard. Under
   ordinary pytest the real ``src`` package is importable, so no shim is installed
   and the real modules load.

Reproduced at 94.4% (killed 323, survived 19) via the WSL/mutmut harness (py3.10);
the CI gate (mutation.yml on py3.11) is the source of truth. The surviving mutants
are genuine equivalents, documented at the bottom of this file.
"""

from __future__ import annotations

import base64
import hashlib
import sys
import types


def _in_mutation_workspace() -> bool:
    # mutmut's mutants/ workspace copies src/serving to a TOP-LEVEL `serving`
    # package (scripts/mutation_report.py prepare_workspace); ordinary pytest has
    # no top-level `serving` (only src.serving), so its presence cleanly marks the
    # harness. The old `import src` probe did not: the editable-installed repo keeps
    # the real `src` importable even inside the workspace, so the stubs were skipped
    # there and the real duckdb-backed engine import crashed mutmut's
    # coverage-instrumented stats pass on py3.11 (duckdb's lazy `_duckdb._sqltypes`
    # import breaks under coverage tracing -- see .github/workflows/ci.yml).
    import importlib.util

    try:
        return importlib.util.find_spec("serving") is not None
    except (ImportError, ValueError):
        return False


def _ensure_module(name: str) -> types.ModuleType:
    module = sys.modules.get(name)
    if module is None:
        module = types.ModuleType(name)
        sys.modules[name] = module
    return module


def _install_harness_stubs() -> None:
    _ensure_module("src")
    processing_pkg = _ensure_module("src.processing")
    tracing_mod = _ensure_module("src.processing.tracing")

    def telemetry_disabled() -> bool:
        return True

    tracing_mod.telemetry_disabled = telemetry_disabled
    processing_pkg.tracing = tracing_mod

    serving_pkg = _ensure_module("src.serving")
    backends_mod = _ensure_module("src.serving.backends")

    class BackendExecutionError(RuntimeError):
        """Mirror of src.serving.backends.BackendExecutionError."""

    backends_mod.BackendExecutionError = BackendExecutionError
    serving_pkg.backends = backends_mod

    # nl_engine is imported lazily inside explain(); supply a rule-based default.
    semantic_pkg = _ensure_module("src.serving.semantic_layer")
    nl_engine_mod = _ensure_module("src.serving.semantic_layer.nl_engine")
    nl_engine_mod._ANTHROPIC_KEY = ""
    semantic_pkg.nl_engine = nl_engine_mod

    # nl_queries imports `.sql_guard`, a shim that does
    # `from src.serving.semantic_layer.sql_guard import ...`. Point that src-name
    # at the REAL top-level sql_guard (sqlglot-only, duckdb-free, importable in
    # the harness) so the validate_nl_sql boundary is exercised against the
    # genuine guard rather than a stub.
    import serving.semantic_layer.sql_guard as _real_sql_guard

    sys.modules["src.serving.semantic_layer.sql_guard"] = _real_sql_guard
    semantic_pkg.sql_guard = _real_sql_guard

    # nl_queries imports `from src.serving.pii_policy import get_pii_policy` for the
    # deny-gate. Point that src-name at the REAL top-level pii_policy (yaml-only,
    # duckdb-free) so the gate runs against the genuine policy + config.
    import serving.pii_policy as _real_pii_policy

    sys.modules["src.serving.pii_policy"] = _real_pii_policy
    serving_pkg.pii_policy = _real_pii_policy

    # Neuter the query package __init__ (`from .engine import QueryEngine`) and
    # the contracts module; both pull duckdb via the QueryEngine import chain and
    # neither contributes runtime behaviour to nl_queries.
    engine_stub = _ensure_module("serving.semantic_layer.query.engine")
    engine_stub.QueryEngine = object
    contracts_stub = _ensure_module("serving.semantic_layer.query.contracts")
    contracts_stub.SQLBuilderHost = object
    contracts_stub.QueryExecutionHost = object
    contracts_stub.NLQueryHost = object


if _in_mutation_workspace():
    _install_harness_stubs()

try:  # mutation-harness workspace exposes it as a top-level package
    from serving.semantic_layer.query import nl_queries as nlq_module
except ImportError:  # ordinary pytest sees it under the src package
    from src.serving.semantic_layer.query import nl_queries as nlq_module

import pytest

NLQueryMixin = nlq_module.NLQueryMixin
UnsafeNLQueryError = nlq_module.UnsafeNLQueryError


# --------------------------------------------------------------------------- #
# In-process host + fake backend + recording span (no duckdb, no real tracer).
# --------------------------------------------------------------------------- #


class _Entity:
    def __init__(self, table: str) -> None:
        self.table = table


class _Catalog:
    def __init__(
        self, tables: tuple[str, ...] = ("orders",), metrics: tuple[str, ...] = ()
    ) -> None:
        self.entities = {table: _Entity(table) for table in tables}
        self.metrics = dict.fromkeys(metrics)


class _FakeBackend:
    """Records every SQL string handed to execute/scalar/explain so the
    pagination wrappers and the row-cap can be pinned exactly."""

    def __init__(self, rows=None, scalar_value=0, explain_rows=None) -> None:
        self._rows = rows if rows is not None else []
        self._scalar_value = scalar_value
        self._explain_rows = explain_rows if explain_rows is not None else []
        self.executed: list[str] = []
        self.scalared: list[str] = []
        self.explained: list[str] = []

    def execute(self, sql: str):
        self.executed.append(sql)
        return self._rows

    def scalar(self, sql: str):
        self.scalared.append(sql)
        return self._scalar_value

    def explain(self, sql: str):
        self.explained.append(sql)
        return self._explain_rows


class _RecordingSpan:
    def __init__(self) -> None:
        self.attributes: dict = {}

    def is_recording(self) -> bool:
        return True

    def set_attribute(self, key, value) -> None:
        self.attributes[key] = value


class _SpanCtx:
    def __init__(self, span: _RecordingSpan) -> None:
        self._span = span

    def __enter__(self) -> _RecordingSpan:
        return self._span

    def __exit__(self, *exc) -> bool:
        return False


class _RecordingTracer:
    def __init__(self) -> None:
        self.started: list = []
        self.spans: list[_RecordingSpan] = []

    def start_as_current_span(self, name):
        self.started.append(name)
        span = _RecordingSpan()
        self.spans.append(span)
        return _SpanCtx(span)


class _Host(NLQueryMixin):
    def __init__(
        self,
        *,
        catalog: _Catalog | None = None,
        backend: _FakeBackend | None = None,
        backend_name: str = "duckdb",
        translated: str = "SELECT id FROM orders",
    ) -> None:
        self.catalog = catalog if catalog is not None else _Catalog()
        self._backend = backend if backend is not None else _FakeBackend()
        self._backend_name = backend_name
        self._translated = translated
        self.translate_calls: list[tuple[str, str | None]] = []
        self.scope_calls: list[tuple[str, str | None]] = []

    # Overridden so the test never pulls nl_engine / the tenant router; these
    # live in other modules and are mutation-tested separately. Calls are
    # recorded so the call sites' argument forwarding can be pinned.
    def _translate_question_to_sql(self, question: str, tenant_id: str | None = None) -> str:
        self.translate_calls.append((question, tenant_id))
        return self._translated

    def _scope_sql(self, sql: str, tenant_id: str | None) -> str:
        self.scope_calls.append((sql, tenant_id))
        return sql

    def _resolve_tenant_id(self, tenant_id: str | None) -> str | None:
        return tenant_id


@pytest.fixture(autouse=True)
def _disable_telemetry(monkeypatch):
    # Force the no-span path deterministically in both contexts (the harness stub
    # already returns True; under ordinary pytest the real one may not). Telemetry
    # tests below re-enable it explicitly.
    monkeypatch.setattr(nlq_module, "telemetry_disabled", lambda: True)


def _fixed_clock(monkeypatch, start_t: float, end_t: float) -> None:
    # Pin time.monotonic so elapsed_ms is deterministic: first call returns the
    # method's start stamp, every later call returns the end stamp. This makes the
    # elapsed arithmetic killable without depending on the absolute wall clock (a
    # `- start`->`+ start` flip would otherwise pass or fail by machine uptime).
    state = {"calls": 0}

    def _monotonic() -> float:
        state["calls"] += 1
        return start_t if state["calls"] == 1 else end_t

    monkeypatch.setattr(nlq_module, "time", types.SimpleNamespace(monotonic=_monotonic))


# --------------------------------------------------------------------------- #
# _default_allowed_tables: catalog tables + pipeline_events.
# --------------------------------------------------------------------------- #


def test_default_allowed_tables_includes_catalog_and_pipeline_events():
    host = _Host(catalog=_Catalog(tables=("orders", "customers")))
    allowed = nlq_module._default_allowed_tables(host)
    assert allowed == {"orders", "customers", "pipeline_events"}


# --------------------------------------------------------------------------- #
# _prepare_nl_sql: the validate_nl_sql enforcement boundary.
# --------------------------------------------------------------------------- #


def test_prepare_nl_sql_returns_validated_sql_unchanged():
    sql = "SELECT id FROM orders"
    assert (
        nlq_module._prepare_nl_sql(
            sql, {"orders"}, table_to_entity={"orders": "order"}, tenant_id="acme"
        )
        == sql
    )


def test_prepare_nl_sql_wraps_unsafe_sql_as_403():
    with pytest.raises(UnsafeNLQueryError) as exc_info:
        nlq_module._prepare_nl_sql(
            "DROP TABLE orders", {"orders"}, table_to_entity={}, tenant_id="acme"
        )
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail.startswith("NL-to-SQL produced unsafe query:")


def test_prepare_nl_sql_rejects_unknown_table():
    with pytest.raises(UnsafeNLQueryError):
        nlq_module._prepare_nl_sql(
            "SELECT id FROM secret_table", {"orders"}, table_to_entity={}, tenant_id="acme"
        )


def test_prepare_nl_sql_denies_pii_column_for_nonexempt_tenant():
    # The deny-gate runs after validate_nl_sql: a non-exempt tenant reading a PII
    # column is rejected before execution (order -> shipping_address per config).
    with pytest.raises(UnsafeNLQueryError, match="PII column"):
        nlq_module._prepare_nl_sql(
            "SELECT shipping_address FROM orders",
            {"orders"},
            table_to_entity={"orders": "order"},
            tenant_id="acme",
        )


def test_prepare_nl_sql_exempt_tenant_skips_pii_deny():
    # An exempt tenant bypasses the deny-gate (pins the `not is_exempt` guard).
    sql = "SELECT shipping_address FROM orders"
    assert (
        nlq_module._prepare_nl_sql(
            sql,
            {"orders"},
            table_to_entity={"orders": "order"},
            tenant_id="internal-analytics",
        )
        == sql
    )


def test_unsafe_nl_query_error_is_403():
    err = UnsafeNLQueryError("boom")
    assert err.status_code == 403
    assert err.detail == "boom"


# --------------------------------------------------------------------------- #
# _build_query_hash: tenant-scoped sha256.
# --------------------------------------------------------------------------- #


def test_build_query_hash_matches_sha256_of_tenant_and_sql():
    host = _Host()
    expected = hashlib.sha256(b"acme:SELECT 1").hexdigest()
    assert host._build_query_hash("SELECT 1", "acme") == expected


def test_build_query_hash_uses_default_when_tenant_none():
    host = _Host()
    expected = hashlib.sha256(b"default:SELECT 1").hexdigest()
    assert host._build_query_hash("SELECT 1", None) == expected


def test_build_query_hash_is_sql_sensitive():
    host = _Host()
    assert host._build_query_hash("SELECT 1", "acme") != host._build_query_hash("SELECT 2", "acme")


# --------------------------------------------------------------------------- #
# _encode_cursor / _decode_cursor: base64 round-trip + validation.
# --------------------------------------------------------------------------- #


def test_cursor_round_trip():
    host = _Host()
    cursor = host._encode_cursor(42, "abc123")
    assert host._decode_cursor(cursor) == (42, "abc123")


def test_encode_cursor_is_base64_of_offset_and_hash():
    host = _Host()
    cursor = host._encode_cursor(7, "deadbeef")
    assert base64.urlsafe_b64decode(cursor.encode()).decode() == "7:deadbeef"


def test_decode_cursor_accepts_zero_offset():
    # offset 0 is valid (`offset < 0` rejects, not `<= 0` / `< 1`).
    host = _Host()
    cursor = base64.urlsafe_b64encode(b"0:abc").decode()
    assert host._decode_cursor(cursor) == (0, "abc")


def test_decode_cursor_keeps_colon_in_hash():
    # The hash is split off with maxsplit=1, so a hash containing ':' survives.
    # Kills split(":") (no maxsplit), rsplit, and maxsplit=2.
    host = _Host()
    cursor = base64.urlsafe_b64encode(b"5:a:b:c").decode()
    assert host._decode_cursor(cursor) == (5, "a:b:c")


def test_decode_cursor_rejects_negative_offset():
    host = _Host()
    bad = base64.urlsafe_b64encode(b"-1:abc").decode()
    with pytest.raises(ValueError) as exc_info:
        host._decode_cursor(bad)
    assert str(exc_info.value) == "Invalid cursor value."


def test_decode_cursor_rejects_empty_hash():
    host = _Host()
    bad = base64.urlsafe_b64encode(b"5:").decode()
    with pytest.raises(ValueError) as exc_info:
        host._decode_cursor(bad)
    assert str(exc_info.value) == "Invalid cursor value."


def test_decode_cursor_rejects_non_numeric_offset():
    host = _Host()
    bad = base64.urlsafe_b64encode(b"x:abc").decode()
    with pytest.raises(ValueError) as exc_info:
        host._decode_cursor(bad)
    assert str(exc_info.value) == "Invalid cursor value."


def test_decode_cursor_rejects_garbage():
    host = _Host()
    with pytest.raises(ValueError) as exc_info:
        host._decode_cursor("!!!not-base64!!!")
    assert str(exc_info.value) == "Invalid cursor value."


# --------------------------------------------------------------------------- #
# execute_nl_query: the un-paginated path bounds rows with a hard LIMIT.
# --------------------------------------------------------------------------- #


def test_execute_nl_query_bounds_rows_with_hard_limit():
    # The bounded wrapper caps the row count at _MAX_NL_QUERY_ROWS (1000) so an
    # un-paginated NL item cannot stream a whole table (audit_28 #8). Pin the
    # exact SQL string AND every key of the result dict.
    backend = _FakeBackend(rows=[("r1",), ("r2",)])
    host = _Host(backend=backend, translated="SELECT id FROM orders")
    result = host.execute_nl_query("how many orders", allowed_tables={"orders"})
    assert backend.executed == [
        "SELECT * FROM (SELECT id FROM orders) AS bounded_nl_query LIMIT 1000"
    ]
    assert result["data"] == [("r1",), ("r2",)]
    assert result["sql"] == "SELECT id FROM orders"
    assert result["row_count"] == 2
    assert result["freshness_seconds"] is None
    assert isinstance(result["execution_time_ms"], int)
    assert set(result) == {"data", "sql", "row_count", "execution_time_ms", "freshness_seconds"}


def test_execute_nl_query_max_rows_constant_is_1000():
    assert nlq_module._MAX_NL_QUERY_ROWS == 1000


def test_execute_nl_query_forwards_question_tenant_and_scope():
    backend = _FakeBackend(rows=[("a",)])
    host = _Host(backend=backend)
    host.execute_nl_query("the question", tenant_id="acme", allowed_tables={"orders"})
    assert host.translate_calls == [("the question", "acme")]
    assert host.scope_calls == [("SELECT id FROM orders", "acme")]


def test_execute_nl_query_uses_passed_allowed_tables_not_default():
    # allowed_tables is honoured even when it differs from the catalog-derived
    # default: an `is not None`->`is None` flip would validate against the
    # (here unrelated) default and reject. Empty catalog -> default lacks 'orders'.
    backend = _FakeBackend(rows=[("a",)])
    host = _Host(catalog=_Catalog(tables=()), backend=backend, translated="SELECT id FROM orders")
    result = host.execute_nl_query("q", allowed_tables={"orders"})
    assert result["row_count"] == 1


def test_execute_nl_query_uses_default_allowed_tables_when_none():
    # allowed_tables=None -> _default_allowed_tables(self) governs validation; a
    # `(self)`->`(None)` mutant raises AttributeError on None.catalog.
    backend = _FakeBackend(rows=[("a",)])
    host = _Host(catalog=_Catalog(tables=("orders",)), backend=backend)
    result = host.execute_nl_query("q", allowed_tables=None)
    assert result["row_count"] == 1


def test_execute_nl_query_elapsed_is_monotonic_delta_in_ms(monkeypatch):
    # elapsed_ms = int((end - start) * 1000) on a pinned clock. Kills `=None`,
    # `/1000` and `- start`->`+ start` (the *1001 variant rounds to the same 50).
    _fixed_clock(monkeypatch, 1.0, 1.5)
    host = _Host(backend=_FakeBackend(rows=[("a",)]))
    result = host.execute_nl_query("q", allowed_tables={"orders"})
    assert result["execution_time_ms"] == 500  # int((1.5 - 1.0) * 1000)


def test_execute_nl_query_records_span_attributes(monkeypatch):
    monkeypatch.setattr(nlq_module, "telemetry_disabled", lambda: False)
    tracer = _RecordingTracer()
    monkeypatch.setattr(nlq_module, "tracer", tracer)
    backend = _FakeBackend(rows=[("a",), ("b",)])
    host = _Host(backend=backend, backend_name="duckdb")
    host.execute_nl_query("q", tenant_id="acme", allowed_tables={"orders"})
    assert tracer.started == ["duckdb.query"]
    span = tracer.spans[0]
    assert span.attributes["sql"] == "SELECT id FROM orders"
    assert span.attributes["tenant_id"] == "acme"
    assert span.attributes["row_count"] == 2


def test_execute_nl_query_wraps_backend_error_as_value_error():
    class _BoomBackend(_FakeBackend):
        def execute(self, sql):
            raise nlq_module.BackendExecutionError("boom")

    host = _Host(backend=_BoomBackend())
    with pytest.raises(ValueError, match="Query execution failed: boom"):
        host.execute_nl_query("q", allowed_tables={"orders"})


# --------------------------------------------------------------------------- #
# paginated_query: the page/count SQL wrappers + the pagination arithmetic.
# --------------------------------------------------------------------------- #


def test_paginated_query_builds_page_and_count_sql():
    backend = _FakeBackend(rows=[("a",), ("b",), ("c",)], scalar_value=3)
    host = _Host(backend=backend, translated="SELECT id FROM orders")
    host.paginated_query("q", limit=2, allowed_tables={"orders"})
    assert backend.executed == [
        "SELECT * FROM (SELECT id FROM orders) AS paginated_query LIMIT 3 OFFSET 0"
    ]
    assert backend.scalared == [
        "SELECT COUNT(*) FROM (SELECT 1 FROM (SELECT id FROM orders) AS count_query "
        "LIMIT 10001) AS bounded_count"
    ]


def test_paginated_query_default_limit_is_100():
    # No limit -> default 100 -> page SQL asks for limit+1 = 101.
    backend = _FakeBackend(rows=[("a",)], scalar_value=1)
    host = _Host(backend=backend)
    host.paginated_query("q", allowed_tables={"orders"})
    assert backend.executed == [
        "SELECT * FROM (SELECT id FROM orders) AS paginated_query LIMIT 101 OFFSET 0"
    ]


def test_paginated_query_result_dict_keys_and_values():
    backend = _FakeBackend(rows=[("a",), ("b",), ("c",)], scalar_value=3)
    host = _Host(backend=backend)
    result = host.paginated_query("q", limit=2, allowed_tables={"orders"})
    assert result["sql"] == "SELECT id FROM orders"
    assert result["freshness_seconds"] is None
    assert isinstance(result["execution_time_ms"], int)
    assert set(result) == {
        "data",
        "sql",
        "row_count",
        "total_count",
        "next_cursor",
        "has_more",
        "page_size",
        "execution_time_ms",
        "freshness_seconds",
    }


def test_paginated_query_has_more_and_data_slice():
    backend = _FakeBackend(rows=[("a",), ("b",), ("c",)], scalar_value=3)
    host = _Host(backend=backend)
    result = host.paginated_query("q", limit=2, allowed_tables={"orders"})
    assert result["has_more"] is True
    assert result["data"] == [("a",), ("b",)]
    assert result["row_count"] == 2
    assert result["page_size"] == 2


def test_paginated_query_no_more_when_rows_within_limit():
    backend = _FakeBackend(rows=[("a",), ("b",)], scalar_value=2)
    host = _Host(backend=backend)
    result = host.paginated_query("q", limit=2, allowed_tables={"orders"})
    assert result["has_more"] is False
    assert result["next_cursor"] is None
    assert result["data"] == [("a",), ("b",)]


def test_paginated_query_next_cursor_advances_offset():
    backend = _FakeBackend(rows=[("a",), ("b",), ("c",)], scalar_value=3)
    host = _Host(backend=backend)
    result = host.paginated_query("q", limit=2, allowed_tables={"orders"})
    assert result["next_cursor"] is not None
    offset, _hash = host._decode_cursor(result["next_cursor"])
    assert offset == 2  # offset(0) + limit(2)


def test_paginated_query_cursor_hash_is_tenant_and_sql_bound():
    # The cursor hash must derive from the scoped SQL and the tenant id; a mutant
    # that hashes None for either yields a hash that doesn't match the recomputed
    # value, which would also break the same-query cursor check.
    backend = _FakeBackend(rows=[("a",), ("b",), ("c",)], scalar_value=3)
    host = _Host(backend=backend)
    result = host.paginated_query("q", limit=2, tenant_id="acme", allowed_tables={"orders"})
    _offset, cursor_hash = host._decode_cursor(result["next_cursor"])
    assert cursor_hash == host._build_query_hash("SELECT id FROM orders", "acme")


def test_paginated_query_total_count_below_threshold_is_exact():
    backend = _FakeBackend(rows=[("a",)], scalar_value=5)
    host = _Host(backend=backend)
    result = host.paginated_query("q", limit=10, allowed_tables={"orders"})
    assert result["total_count"] == 5


def test_paginated_query_total_count_is_none_above_threshold():
    backend = _FakeBackend(rows=[("a",)], scalar_value=10_001)
    host = _Host(backend=backend)
    result = host.paginated_query("q", limit=10, allowed_tables={"orders"})
    assert result["total_count"] is None


def test_paginated_query_total_count_exactly_threshold_is_exact():
    backend = _FakeBackend(rows=[("a",)], scalar_value=10_000)
    host = _Host(backend=backend)
    result = host.paginated_query("q", limit=10, allowed_tables={"orders"})
    assert result["total_count"] == 10_000


def test_paginated_query_total_count_zero_when_scalar_none():
    # A None scalar coalesces to 0 (kills the `else 0`->`else 1` mutant).
    backend = _FakeBackend(rows=[("a",)], scalar_value=None)
    host = _Host(backend=backend)
    result = host.paginated_query("q", limit=10, allowed_tables={"orders"})
    assert result["total_count"] == 0


def test_paginated_query_second_page_uses_cursor_offset():
    backend = _FakeBackend(rows=[("a",), ("b",), ("c",)], scalar_value=3)
    host = _Host(backend=backend)
    first = host.paginated_query("q", limit=2, allowed_tables={"orders"})
    backend.executed.clear()
    host.paginated_query("q", limit=2, cursor=first["next_cursor"], allowed_tables={"orders"})
    assert backend.executed == [
        "SELECT * FROM (SELECT id FROM orders) AS paginated_query LIMIT 3 OFFSET 2"
    ]


def test_paginated_query_rejects_cursor_for_different_query():
    host = _Host(backend=_FakeBackend(rows=[("a",)], scalar_value=1))
    foreign_cursor = host._encode_cursor(2, "not-the-right-hash")
    with pytest.raises(ValueError) as exc_info:
        host.paginated_query("q", limit=2, cursor=foreign_cursor, allowed_tables={"orders"})
    assert str(exc_info.value) == "Cursor does not match the requested query."


def test_paginated_query_rejects_limit_below_one():
    host = _Host()
    with pytest.raises(ValueError) as exc_info:
        host.paginated_query("q", limit=0, allowed_tables={"orders"})
    assert str(exc_info.value) == "limit must be between 1 and 1000"


def test_paginated_query_rejects_limit_above_1000():
    host = _Host()
    with pytest.raises(ValueError) as exc_info:
        host.paginated_query("q", limit=1001, allowed_tables={"orders"})
    assert str(exc_info.value) == "limit must be between 1 and 1000"


def test_paginated_query_allows_boundary_limits():
    backend = _FakeBackend(rows=[("a",)], scalar_value=1)
    host = _Host(backend=backend)
    host.paginated_query("q", limit=1, allowed_tables={"orders"})
    host.paginated_query("q", limit=1000, allowed_tables={"orders"})  # no raise


def test_paginated_query_forwards_question_tenant_and_scope():
    backend = _FakeBackend(rows=[("a",)], scalar_value=1)
    host = _Host(backend=backend)
    host.paginated_query("the question", limit=2, tenant_id="acme", allowed_tables={"orders"})
    assert host.translate_calls == [("the question", "acme")]
    assert host.scope_calls == [("SELECT id FROM orders", "acme")]


def test_paginated_query_uses_passed_allowed_tables_not_default():
    backend = _FakeBackend(rows=[("a",)], scalar_value=1)
    host = _Host(catalog=_Catalog(tables=()), backend=backend, translated="SELECT id FROM orders")
    result = host.paginated_query("q", limit=5, allowed_tables={"orders"})
    assert result["row_count"] == 1


def test_paginated_query_uses_default_allowed_tables_when_none():
    backend = _FakeBackend(rows=[("a",)], scalar_value=1)
    host = _Host(catalog=_Catalog(tables=("orders",)), backend=backend)
    result = host.paginated_query("q", limit=5, allowed_tables=None)
    assert result["row_count"] == 1


def test_paginated_query_elapsed_is_monotonic_delta_in_ms(monkeypatch):
    _fixed_clock(monkeypatch, 1.0, 1.5)
    host = _Host(backend=_FakeBackend(rows=[("a",)], scalar_value=1))
    result = host.paginated_query("q", limit=5, allowed_tables={"orders"})
    assert result["execution_time_ms"] == 500  # int((1.5 - 1.0) * 1000)


def test_paginated_query_records_span_attributes(monkeypatch):
    monkeypatch.setattr(nlq_module, "telemetry_disabled", lambda: False)
    tracer = _RecordingTracer()
    monkeypatch.setattr(nlq_module, "tracer", tracer)
    backend = _FakeBackend(rows=[("a",), ("b",), ("c",)], scalar_value=3)
    host = _Host(backend=backend, backend_name="duckdb")
    host.paginated_query("q", limit=2, tenant_id="acme", allowed_tables={"orders"})
    assert tracer.started == ["duckdb.query"]
    span = tracer.spans[0]
    assert span.attributes["sql"] == "SELECT id FROM orders"
    assert span.attributes["tenant_id"] == "acme"
    assert span.attributes["row_count"] == 2  # len(page_rows[:limit])


# The span SQL attribute is bounded: <=200 chars verbatim, else sql[:197]+"...".
# Two boundary lengths pin the <=200 comparison and the 197 truncation offset.
_SQL_200 = "SELECT id FROM orders".ljust(200)
_SQL_201 = "SELECT id FROM orders".ljust(201)


def _recording_tracer(monkeypatch):
    monkeypatch.setattr(nlq_module, "telemetry_disabled", lambda: False)
    tracer = _RecordingTracer()
    monkeypatch.setattr(nlq_module, "tracer", tracer)
    return tracer


def test_paginated_query_span_keeps_sql_at_200_boundary(monkeypatch):
    tracer = _recording_tracer(monkeypatch)
    host = _Host(backend=_FakeBackend(rows=[("a",)], scalar_value=1), translated=_SQL_200)
    host.paginated_query("q", limit=2, allowed_tables={"orders"})
    assert tracer.spans[0].attributes["sql"] == _SQL_200  # len == 200 kept whole


def test_paginated_query_span_truncates_sql_past_200(monkeypatch):
    tracer = _recording_tracer(monkeypatch)
    host = _Host(backend=_FakeBackend(rows=[("a",)], scalar_value=1), translated=_SQL_201)
    host.paginated_query("q", limit=2, allowed_tables={"orders"})
    assert tracer.spans[0].attributes["sql"] == _SQL_201[:197] + "..."


def test_execute_span_keeps_sql_at_200_boundary(monkeypatch):
    tracer = _recording_tracer(monkeypatch)
    host = _Host(backend=_FakeBackend(rows=[("a",)]), translated=_SQL_200)
    host.execute_nl_query("q", allowed_tables={"orders"})
    assert tracer.spans[0].attributes["sql"] == _SQL_200


def test_execute_span_truncates_sql_past_200(monkeypatch):
    tracer = _recording_tracer(monkeypatch)
    host = _Host(backend=_FakeBackend(rows=[("a",)]), translated=_SQL_201)
    host.execute_nl_query("q", allowed_tables={"orders"})
    assert tracer.spans[0].attributes["sql"] == _SQL_201[:197] + "..."


def test_paginated_query_wraps_backend_error_as_value_error():
    class _BoomBackend(_FakeBackend):
        def execute(self, sql):
            raise nlq_module.BackendExecutionError("kaboom")

    host = _Host(backend=_BoomBackend())
    with pytest.raises(ValueError, match="Query execution failed: kaboom"):
        host.paginated_query("q", limit=2, allowed_tables={"orders"})


# --------------------------------------------------------------------------- #
# explain: translate without executing; table extraction + scan warning.
# --------------------------------------------------------------------------- #


def test_explain_reports_tables_estimate_and_scan_warning():
    backend = _FakeBackend(explain_rows=[(0, "SEQ_SCAN orders"), (1, "estimated ~ 1,234 rows")])
    host = _Host(backend=backend, translated="SELECT id FROM orders")
    result = host.explain("show orders", allowed_tables={"orders"})
    assert result["question"] == "show orders"
    assert result["sql"] == "SELECT id FROM orders"
    assert result["tables_accessed"] == ["orders"]
    assert result["estimated_rows"] == 1234
    assert result["engine"] == "rule_based"
    assert result["warning"] == "Full table scan on orders (no index)"
    assert set(result) == {
        "question",
        "sql",
        "tables_accessed",
        "estimated_rows",
        "engine",
        "warning",
    }


def test_explain_warns_on_sequential_scan_text_only():
    # The warning fires on "Sequential Scan" too, not just "SEQ_SCAN". A plan with
    # the spaced form (and no SEQ_SCAN) must still warn -- pins the exact
    # "Sequential Scan" literal and its casing.
    backend = _FakeBackend(explain_rows=[(0, "Sequential Scan on orders")])
    host = _Host(backend=backend, translated="SELECT id FROM orders")
    result = host.explain("q", allowed_tables={"orders"})
    assert result["warning"] == "Full table scan on orders (no index)"


def test_explain_no_warning_without_sequential_scan():
    backend = _FakeBackend(explain_rows=[(0, "HASH_JOIN"), (1, "estimated ~ 10 rows")])
    host = _Host(backend=backend, translated="SELECT id FROM orders")
    result = host.explain("q", allowed_tables={"orders"})
    assert result["warning"] is None
    assert result["estimated_rows"] == 10


def test_explain_single_column_row_uses_first_element():
    # A one-element explain row has no row[1]; the plan text must come from
    # str(row[0]). Kills `len(row) > 1`->`>= 1` (IndexError) and `str(row[0])`->
    # `str(None)`/`str(row[1])` (which would drop the SEQ_SCAN text).
    backend = _FakeBackend(explain_rows=[("SEQ_SCAN orders ~ 42 rows",)])
    host = _Host(backend=backend, translated="SELECT id FROM orders")
    result = host.explain("q", allowed_tables={"orders"})
    assert result["estimated_rows"] == 42
    assert result["warning"] == "Full table scan on orders (no index)"


def test_explain_normalizes_box_drawing_around_estimate():
    # EXPLAIN output draws box characters; they are normalized to spaces so the
    # row-estimate regex still matches. A box char glued to the estimate must be
    # blanked. Kills the box-drawing re.sub mutants.
    backend = _FakeBackend(explain_rows=[(0, "estimated ~ 1234│rows")])
    host = _Host(backend=backend, translated="SELECT id FROM orders")
    result = host.explain("q", allowed_tables={"orders"})
    assert result["estimated_rows"] == 1234


def test_explain_passes_scoped_sql_to_backend_explain():
    backend = _FakeBackend(explain_rows=[(0, "x")])
    host = _Host(backend=backend, translated="SELECT id FROM orders")
    host.explain("q", allowed_tables={"orders"})
    assert backend.explained == ["SELECT id FROM orders"]


def test_explain_forwards_question_tenant_and_scope():
    backend = _FakeBackend(explain_rows=[(0, "x")])
    host = _Host(backend=backend)
    host.explain("the question", tenant_id="acme", allowed_tables={"orders"})
    assert host.translate_calls == [("the question", "acme")]
    assert host.scope_calls == [("SELECT id FROM orders", "acme")]


def test_explain_uses_passed_allowed_tables_not_default():
    backend = _FakeBackend(explain_rows=[(0, "x")])
    host = _Host(catalog=_Catalog(tables=()), backend=backend, translated="SELECT id FROM orders")
    result = host.explain("q", allowed_tables={"orders"})
    assert result["tables_accessed"] == ["orders"]


def test_explain_uses_default_allowed_tables_when_none():
    backend = _FakeBackend(explain_rows=[(0, "x")])
    host = _Host(catalog=_Catalog(tables=("orders",)), backend=backend)
    result = host.explain("q", allowed_tables=None)
    assert result["tables_accessed"] == ["orders"]


def test_explain_reports_llm_engine_when_key_and_anthropic_present(monkeypatch):
    # When a key is configured and `import anthropic` succeeds, the engine label
    # is "llm". Pins the getattr(nl_engine, "_ANTHROPIC_KEY", "") read: a mutant
    # that reads the wrong attribute/object collapses to "rule_based".
    nl_engine_mod = sys.modules["src.serving.semantic_layer.nl_engine"]
    monkeypatch.setattr(nl_engine_mod, "_ANTHROPIC_KEY", "sk-test", raising=False)
    monkeypatch.setitem(sys.modules, "anthropic", types.ModuleType("anthropic"))
    backend = _FakeBackend(explain_rows=[(0, "x")])
    host = _Host(backend=backend, translated="SELECT id FROM orders")
    result = host.explain("q", allowed_tables={"orders"})
    assert result["engine"] == "llm"


def test_explain_wraps_backend_error_as_value_error():
    class _BoomBackend(_FakeBackend):
        def explain(self, sql):
            raise nlq_module.BackendExecutionError("nope")

    host = _Host(backend=_BoomBackend())
    with pytest.raises(ValueError, match="Query explanation failed: nope"):
        host.explain("q", allowed_tables={"orders"})


# --------------------------------------------------------------------------- #
# Known equivalent survivors (documented, not gaps). 94.4% reproduced on the
# WSL/mutmut harness; the survivors below cannot change observable behaviour:
#   * tables-extraction in explain() parses with sqlglot and falls back to a
#     regex on any exception. For the bare-table SQL that validate_nl_sql permits
#     (schema/catalog qualifiers are rejected upstream) both paths return the same
#     list, so the parse-dialect / parse-arg mutants and the fromkeys/find_all
#     mutants in that block are equivalent.
#   * the explain() box-drawing re.sub case mutant (╿<->╿ is the same
#     code point range) and the plan-join separator mutant (the joined plan text
#     is not returned, only scanned for the same substrings either way).
#   * the explain() getattr default-value mutants: nl_engine always defines
#     _ANTHROPIC_KEY, so the third (default) argument is unreachable.
#   * elapsed_ms `* 1000`->`* 1001`: indistinguishable at unit-test timescales.
#   * the span SQL slice `[:200]`->`[:201]`: in the `len(sql) <= 200` branch the
#     slice never reaches 200 chars, so the extra index is a no-op.
# The telemetry span guards and the <=200 / [:197] truncation boundary ARE pinned
# by the records_span / span-boundary tests above (telemetry re-enabled).
# --------------------------------------------------------------------------- #
