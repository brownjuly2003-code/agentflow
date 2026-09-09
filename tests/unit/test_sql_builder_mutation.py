"""Narrow, duckdb-free mutation test for the tenant SQL builder
(src/agentflow_runtime/serving/semantic_layer/query/sql_builder.py).

This is the test the mutation gate runs against
``serving/semantic_layer/query/sql_builder.py`` (see scripts/mutation_report.py
MODULE_TARGETS). Every entity/metric SQL string the engine executes flows through
``_scope_sql`` / ``_qualify_table`` here, so a surviving mutant in the
tenant-schema qualification is a cross-tenant read (audit_28_06_26.md #5), exactly
the kind of code a mutation gate should pin.

Three design rules, shared with test_rate_limiter_mutation.py /
test_sql_guard_mutation.py (see fable_handoff.md cont.16-19):

1. **duckdb-free.** The ordinary query-engine tests build a QueryEngine, which
   imports duckdb's compiled subpackage and crashes mutmut's ``mutants/``
   workspace. sql_builder itself imports only sqlglot + a tenant-id helper, so
   this file touches the mixin methods through a hand-built host and never drags
   duckdb in.

2. **No fixtures -- inline construction + direct method calls.** With
   ``mutate_only_covered_lines = true`` the gate collects coverage first; a
   fixture-built host left every method line uncovered, so only ``__init__`` got
   mutated (score 0%). Building the host inline and calling ``_scope_sql`` /
   ``_qualify_table`` / ``_quote_literal`` directly attributes every method line.

3. **Import shims.** The mutation harness copies ``src/agentflow_runtime/serving`` to a top-level
   ``serving`` package *without* ``src`` (copying ``src`` would shadow it), so
   every ``agentflow_runtime.*`` name on sql_builder's import path has to be
   arranged before the module loads. Two of them would drag duckdb in and are
   replaced: ``serving.semantic_layer.query``'s package ``__init__``
   (``from .engine import QueryEngine``) and ``.contracts`` (imports the duckdb
   backend for type hints). ``agentflow_runtime.serving.api.auth`` is replaced
   for the same reason, with a passthrough for ``get_current_tenant_id`` -- the
   host controls the tenant here. The rest are *aliased to the real objects*,
   not replaced: ``BackendExecutionError`` and ``quote_sql_literal`` come from
   the workspace's own ``serving`` copy (neither module imports duckdb at
   runtime), and ``agentflow_runtime`` itself stays the real package so
   ``agentflow_runtime.tenancy.DEFAULT_TENANT`` resolves. That distinction is
   the point: a stand-in for ``quote_sql_literal`` or a made-up
   ``DEFAULT_TENANT`` would change the very SQL strings this test asserts on,
   and mutants of the quoting and scoping logic would stop meaning anything.
   Under ordinary pytest there is no top-level ``serving``, so no shim is
   installed and the real modules load.

   The shim went stale once already: ``1096e2e`` renamed the runtime from
   ``src.*`` to ``agentflow_runtime.*``, which moved ``BackendExecutionError``,
   ``quote_sql_literal`` and ``DEFAULT_TENANT`` onto import paths this function
   did not cover. The module then failed to import inside the workspace, mutmut
   scored it ``n/a``, and the weekly mutation gate went red on 2026-07-12 and
   stayed red. Anything added to sql_builder's imports belongs here too.

A note on the score, because the number here was wrong for two months. This
docstring used to record "96.0% (killed 167, survived 7), the 7 are equivalent
mutants, not gaps", measured on a WSL/py3.10 harness. ``1096e2e`` then broke the
import shim above, the module scored ``n/a`` for nine weeks, and nobody could
have noticed the figure going stale. The first run after the shim was repaired
(``3820a2f``) measured 80.3% -- killed 106, survived 26, against a 90% threshold
-- and 14 of those 26 were in ``_holds_foreign_tenant_rows``, a method this file
did not test at all. So the old paragraph was not merely out of date: it was
describing a mutant population that no longer existed, and it read as
reassurance while a tenant-isolation guard sat unpinned.

The CI gate (mutation.yml on py3.11) is the only source of truth for this score;
mutant *counts* differ per interpreter, because ``mutate_only_covered_lines``
makes the population depend on coverage attribution. Do not restate a number
here that was not read off a mutation.yml run, and record the run id with it.
"""

from __future__ import annotations

import sys
import types
from datetime import datetime


def _in_mutation_workspace() -> bool:
    # mutmut's mutants/ workspace copies src/agentflow_runtime/serving to a TOP-LEVEL `serving`
    # package (scripts/mutation_report.py prepare_workspace); ordinary pytest has
    # no top-level `serving` (only agentflow_runtime.serving), so its presence cleanly marks the
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
    import importlib

    # `agentflow_runtime` stays the REAL package: sql_builder reads
    # DEFAULT_TENANT from agentflow_runtime.tenancy, which lives outside the
    # `serving` subtree the workspace copies, and a bare stub here would hide
    # the installed package and make that import unresolvable.
    runtime_pkg = importlib.import_module("agentflow_runtime")

    # agentflow_runtime.serving.api.auth.get_current_tenant_id: a contextvar reader in
    # production; here a default-arg passthrough (the host controls the tenant).
    # Registering the dotted names in sys.modules is what keeps the real,
    # duckdb-importing `serving.api` package from ever loading.
    serving_pkg = _ensure_module("agentflow_runtime.serving")
    api_pkg = _ensure_module("agentflow_runtime.serving.api")
    auth_pkg = _ensure_module("agentflow_runtime.serving.api.auth")

    def get_current_tenant_id(default: str | None = None) -> str | None:
        return default

    auth_pkg.get_current_tenant_id = get_current_tenant_id
    api_pkg.auth = auth_pkg
    serving_pkg.api = api_pkg
    runtime_pkg.serving = serving_pkg

    # The other two runtime imports are aliases onto the workspace's own copy,
    # not stand-ins: `serving.backends` names duckdb only under TYPE_CHECKING
    # and `serving.semantic_layer.sql_literals` is a leaf that imports nothing
    # but datetime, so both load here exactly as they do in production.
    from serving.backends import BackendExecutionError
    from serving.semantic_layer.sql_literals import quote_sql_literal

    backends_mod = _ensure_module("agentflow_runtime.serving.backends")
    backends_mod.BackendExecutionError = BackendExecutionError
    serving_pkg.backends = backends_mod

    semantic_pkg = _ensure_module("agentflow_runtime.serving.semantic_layer")
    literals_mod = _ensure_module("agentflow_runtime.serving.semantic_layer.sql_literals")
    literals_mod.quote_sql_literal = quote_sql_literal
    semantic_pkg.sql_literals = literals_mod
    serving_pkg.semantic_layer = semantic_pkg

    # Neuter the query package __init__ (`from .engine import QueryEngine`) and
    # the contracts module; both pull duckdb via the QueryEngine import chain and
    # neither contributes runtime behaviour to sql_builder.
    engine_stub = _ensure_module("serving.semantic_layer.query.engine")
    engine_stub.QueryEngine = object
    contracts_stub = _ensure_module("serving.semantic_layer.query.contracts")
    contracts_stub.SQLBuilderHost = object
    contracts_stub.QueryExecutionHost = object
    contracts_stub.NLQueryHost = object


if _in_mutation_workspace():
    _install_harness_stubs()

try:  # mutation-harness workspace exposes it as a top-level package
    from serving.semantic_layer.query import sql_builder as sql_builder_module
except ImportError:  # ordinary pytest sees it under the src package
    from agentflow_runtime.serving.semantic_layer.query import sql_builder as sql_builder_module

import pytest

SQLBuilderMixin = sql_builder_module.SQLBuilderMixin


# --------------------------------------------------------------------------- #
# In-process host doubles (no duckdb, no real tenant router).
# --------------------------------------------------------------------------- #


class _Entity:
    def __init__(self, table: str) -> None:
        self.table = table


class _Catalog:
    def __init__(self, *tables: str) -> None:
        self.entities = {table: _Entity(table) for table in tables}


class _TenantsConfig:
    def __init__(self, tenants: tuple[object, ...]) -> None:
        self.tenants = tenants


class _TenantRouter:
    """Only `has_config()` is left of what the SQL builder asks a router.

    Scoping a table is a predicate now, not a schema lookup (ADR-004), so there
    is no `get_duckdb_schema` to stub and no per-tenant config to consult — the
    builder needs the router for exactly one thing: is this a deployment that
    names tenants at all, or a single-tenant one whose rows are all `default`.
    """

    def __init__(
        self,
        *,
        has_config: bool = False,
        tenants: tuple[object, ...] = (),
    ) -> None:
        self._has_config = has_config
        self._tenants = tenants

    def has_config(self) -> bool:
        return self._has_config

    def load(self) -> _TenantsConfig:
        return _TenantsConfig(self._tenants)


class _Backend:
    """Answers the one question `_holds_foreign_tenant_rows` asks a store.

    It records the SQL rather than only replaying a verdict: the probe text *is*
    the check. A mutant that widens `<>` to `=`, drops the `LIMIT 1`, or asks
    about some tenant other than the default still returns a truthy row and
    would pass a test that only looked at the boolean.
    """

    def __init__(self, rows: object = (), error: BaseException | None = None) -> None:
        self._rows = rows
        self._error = error
        self.queries: list[str] = []

    def execute(self, sql: str) -> object:
        self.queries.append(sql)
        if self._error is not None:
            raise self._error
        return self._rows


class _Host(SQLBuilderMixin):
    def __init__(
        self,
        *,
        catalog: _Catalog,
        tenant_router: _TenantRouter,
        table_columns: dict[str, set[str]] | None = None,
        cache: dict | None = None,
        backend: _Backend | None = None,
        foreign_tenant_cache: dict[str, bool] | None = None,
    ) -> None:
        self.catalog = catalog
        self._tenant_router = tenant_router
        self._table_columns_map = dict(table_columns or {})
        if cache is not None:
            self._qualified_table_cache = cache
        # Absent, not None, when no store is supplied: the production host always
        # has `_backend`, and `_holds_foreign_tenant_rows` reads both attributes
        # through `getattr(..., None)`, so a double that never sets them exercises
        # the same defaulted reads the mixin performs.
        if backend is not None:
            self._backend = backend
        if foreign_tenant_cache is not None:
            self._foreign_tenant_cache = foreign_tenant_cache

    def _table_columns(self, table_name: str) -> set[str]:
        return self._table_columns_map.get(table_name, set())


def _host(**kwargs) -> _Host:
    catalog = kwargs.pop("catalog", _Catalog("orders", "customers"))
    tenant_router = kwargs.pop("tenant_router", _TenantRouter())
    return _Host(catalog=catalog, tenant_router=tenant_router, **kwargs)


# --------------------------------------------------------------------------- #
# _resolve_tenant_id: explicit id wins; else the context reader with a
# config-dependent default.
# --------------------------------------------------------------------------- #


def test_resolve_tenant_id_returns_explicit_id():
    # tenant_id is not None -> returned verbatim, the context reader is not
    # consulted. Kills `is not None` -> `is None`.
    host = _host()
    assert host._resolve_tenant_id("acme") == "acme"


def test_resolve_tenant_id_defaults_to_the_default_tenant_without_config():
    # No tenant config -> default_tenant is DEFAULT_TENANT, handed to the context reader.
    host = _host(tenant_router=_TenantRouter(has_config=False))
    assert host._resolve_tenant_id(None) == "default"


def test_resolve_tenant_id_no_default_when_config_present():
    # With a tenant config the default is None (a multi-tenant deployment must
    # not silently fall back to the single-tenant default). Kills the
    # `not self._tenant_router...` flip and the default leaking into the
    # configured path, where a real tenant must come from the request.
    host = _host(tenant_router=_TenantRouter(has_config=True))
    assert host._resolve_tenant_id(None) is None


def test_resolve_tenant_id_uses_context_value(monkeypatch):
    # When the context reader returns a tenant, _resolve_tenant_id forwards it.
    monkeypatch.setattr(
        sql_builder_module, "get_current_tenant_id", lambda default=None: "ctx-tenant"
    )
    host = _host(tenant_router=_TenantRouter(has_config=True))
    assert host._resolve_tenant_id(None) == "ctx-tenant"


def test_resolve_tenant_id_passes_default_through_to_reader(monkeypatch):
    # The default arg must reach the reader (a `default=...`->`default=None`
    # mutant would drop it). Echo the default back to prove it was passed.
    monkeypatch.setattr(sql_builder_module, "get_current_tenant_id", lambda default=None: default)
    host = _host(tenant_router=_TenantRouter(has_config=False))
    assert host._resolve_tenant_id(None) == "default"


# --------------------------------------------------------------------------- #
# _physical_table: the name you can DESCRIBE, as opposed to the relation you read
# through. Splitting the two is what let tenant scoping stop being a name at all.
# --------------------------------------------------------------------------- #


def test_physical_table_is_the_bare_table_name():
    assert _host()._physical_table("orders") == "orders"


# --------------------------------------------------------------------------- #
# _tenant_predicate: the tenant boundary, as a SQL fragment (ADR-004).
# --------------------------------------------------------------------------- #


def test_tenant_predicate_renders_equality_on_the_tenant_column():
    host = _host(tenant_router=_TenantRouter(has_config=True))
    assert host._tenant_predicate("acme") == "tenant_id = 'acme'"


def test_tenant_predicate_is_none_when_no_tenant_resolves(monkeypatch):
    # No tenant in context, tenants config present -> None, i.e. an unscoped read.
    # Reachable only with auth disabled; AuthMiddleware always sets a concrete
    # tenant. Kills an `is None` -> `is not None` flip, which would render the
    # nonsense predicate `tenant_id = 'None'`.
    monkeypatch.setattr(sql_builder_module, "get_current_tenant_id", lambda default=None: None)
    host = _host(tenant_router=_TenantRouter(has_config=True))
    assert host._tenant_predicate(None) is None


def test_tenant_predicate_rejects_an_id_that_could_break_out_of_the_literal():
    # The predicate IS the isolation boundary, and it is inlined as a literal on
    # the ClickHouse path (whose execute(params=...) is a documented no-op), so
    # the id is validated rather than trusted. Kills dropping the regex check.
    host = _host(tenant_router=_TenantRouter(has_config=True))
    with pytest.raises(ValueError, match="Invalid tenant id"):
        host._tenant_predicate("acme' OR '1'='1")


def test_tenant_predicate_rejects_empty_tenant_id():
    host = _host(tenant_router=_TenantRouter(has_config=True))
    with pytest.raises(ValueError, match="Invalid tenant id"):
        host._tenant_predicate("")


def test_tenant_predicate_accepts_hyphens_and_dots():
    # Shipped tenants look like `acme-corp`; a regex mutant that drops `-` would
    # reject every one of them.
    host = _host(tenant_router=_TenantRouter(has_config=True))
    assert host._tenant_predicate("acme-corp.eu") == "tenant_id = 'acme-corp.eu'"


def test_tenant_predicate_accepts_uppercase():
    # `[A-Za-z0-9]` -> `[a-z0-9]` would reject a valid mixed-case tenant id.
    host = _host(tenant_router=_TenantRouter(has_config=True))
    assert host._tenant_predicate("Acme_DW") == "tenant_id = 'Acme_DW'"


# --------------------------------------------------------------------------- #
# _quote_identifier: double-quote wrapping with embedded-quote doubling.
# --------------------------------------------------------------------------- #


def test_quote_identifier_wraps_in_double_quotes():
    assert _host()._quote_identifier("orders") == '"orders"'


def test_quote_identifier_doubles_embedded_quotes():
    # An embedded `"` must be doubled so the identifier can't be broken out of.
    assert _host()._quote_identifier('a"b') == '"a""b"'


# --------------------------------------------------------------------------- #
# _quote_literal: per-type rendering (the order matters: bool before int).
# --------------------------------------------------------------------------- #


def test_quote_literal_none_is_sql_null():
    assert _host()._quote_literal(None) == "NULL"


def test_quote_literal_true_is_sql_true_not_one():
    # bool is checked before int (bool is an int subclass); a dropped bool branch
    # would render True as "1". Pin both bool values.
    assert _host()._quote_literal(True) == "TRUE"


def test_quote_literal_false_is_sql_false():
    assert _host()._quote_literal(False) == "FALSE"


def test_quote_literal_int_is_bare():
    assert _host()._quote_literal(42) == "42"


def test_quote_literal_float_is_bare():
    assert _host()._quote_literal(3.5) == "3.5"


def test_quote_literal_datetime_uses_iso_seconds():
    assert _host()._quote_literal(datetime(2026, 6, 30, 14, 5, 9)) == "'2026-06-30 14:05:09'"


def test_quote_literal_string_is_quoted_and_escaped():
    # A single quote in a string literal must be doubled (anti-injection).
    assert _host()._quote_literal("O'Brien") == "'O''Brien'"


# --------------------------------------------------------------------------- #
# _holds_foreign_tenant_rows: the fail-closed probe behind an unscoped read.
# A request that carries no tenant context is answered only when the table has
# nothing to leak — every row in it belongs to DEFAULT_TENANT. Both directions
# have teeth: a false negative hands an anonymous caller every tenant's rows, a
# false positive 503s the single-tenant demo that never sets a tenant at all.
# (audit p2_1 #5)
#
# The method had no tests. Its only exercised path was the `_backend is None`
# early return the host doubles fell into, so the probe, the cache and the
# fail-closed branch it feeds were all unpinned — 14 of the 26 mutants that
# survived the 2026-09-08 gate run (score 80.3%, threshold 90%) live here.
# --------------------------------------------------------------------------- #

FOREIGN_TENANT_PROBE = "SELECT 1 FROM orders WHERE tenant_id <> 'default' LIMIT 1"


def test_holds_foreign_tenant_rows_is_true_when_the_store_returns_a_row():
    host = _host(backend=_Backend(rows=[(1,)]))
    assert host._holds_foreign_tenant_rows("orders") is True


def test_holds_foreign_tenant_rows_is_false_when_the_store_returns_nothing():
    host = _host(backend=_Backend(rows=[]))
    assert host._holds_foreign_tenant_rows("orders") is False


def test_holds_foreign_tenant_rows_asks_only_about_non_default_tenants():
    # The probe text *is* the check, so it is pinned whole. A mutant that widens
    # `<>` to `=`, drops the `LIMIT 1`, or names a tenant other than the default
    # still returns a truthy row, and a test that only read the boolean would
    # call every one of those correct.
    backend = _Backend(rows=[])
    host = _host(backend=backend)
    host._holds_foreign_tenant_rows("orders")
    assert backend.queries == [FOREIGN_TENANT_PROBE]


def test_holds_foreign_tenant_rows_probes_the_table_it_was_given():
    backend = _Backend(rows=[])
    host = _host(backend=backend)
    host._holds_foreign_tenant_rows("customers")
    assert backend.queries == ["SELECT 1 FROM customers WHERE tenant_id <> 'default' LIMIT 1"]


def test_holds_foreign_tenant_rows_treats_an_unreadable_table_as_empty():
    # Not materialized yet, or no tenant column: there are no foreign rows in it
    # to leak, so the unscoped read stays allowed.
    error = sql_builder_module.BackendExecutionError("no such table: orders")
    host = _host(backend=_Backend(error=error))
    assert host._holds_foreign_tenant_rows("orders") is False


def test_holds_foreign_tenant_rows_lets_an_unexpected_failure_through():
    # Only the store's own "cannot read that" is benign. A connection fault is
    # not evidence of an empty table, and must not be laundered into permission.
    host = _host(backend=_Backend(error=RuntimeError("connection reset")))
    with pytest.raises(RuntimeError):
        host._holds_foreign_tenant_rows("orders")


def test_holds_foreign_tenant_rows_serves_a_cached_verdict_without_probing():
    backend = _Backend(rows=[(1,)])
    host = _host(backend=backend, foreign_tenant_cache={"orders": False})
    assert host._holds_foreign_tenant_rows("orders") is False
    assert backend.queries == []


def test_holds_foreign_tenant_rows_caches_what_it_learned():
    # One probe per table per process, not one per read.
    backend = _Backend(rows=[(1,)])
    cache: dict[str, bool] = {}
    host = _host(backend=backend, foreign_tenant_cache=cache)
    assert host._holds_foreign_tenant_rows("orders") is True
    assert cache == {"orders": True}
    assert host._holds_foreign_tenant_rows("orders") is True
    assert len(backend.queries) == 1


def test_holds_foreign_tenant_rows_caches_per_table():
    # Keyed by table: one table's emptiness must never vouch for another's.
    backend = _Backend(rows=[(1,)])
    host = _host(backend=backend, foreign_tenant_cache={"orders": False})
    assert host._holds_foreign_tenant_rows("customers") is True
    assert backend.queries == ["SELECT 1 FROM customers WHERE tenant_id <> 'default' LIMIT 1"]


def test_holds_foreign_tenant_rows_still_answers_without_a_cache():
    # The cache is an optimisation the host may not offer; the verdict is not.
    backend = _Backend(rows=[(1,)])
    host = _host(backend=backend)
    assert host._holds_foreign_tenant_rows("orders") is True
    assert host._holds_foreign_tenant_rows("orders") is True
    assert len(backend.queries) == 2


# --------------------------------------------------------------------------- #
# _qualify_table: the scoped relation every entity read goes through, plus its
# cache. This is the chokepoint — a surviving mutant here is a cross-tenant read.
# --------------------------------------------------------------------------- #

SCOPED_ORDERS_ACME = (
    "(SELECT * EXCLUDE (tenant_id) FROM orders WHERE tenant_id = 'acme') AS \"orders\""
)
SCOPED_ORDERS_UNSCOPED = '(SELECT * EXCLUDE (tenant_id) FROM orders) AS "orders"'


def test_qualify_table_filters_by_the_caller_tenant():
    host = _host(tenant_router=_TenantRouter(has_config=True))
    assert host._qualify_table("orders", "acme") == SCOPED_ORDERS_ACME


def test_qualify_table_excludes_the_tenant_column_from_the_projection():
    # EXCLUDE keeps tenant_id out of `SELECT *`, so an API row carries exactly the
    # columns its entity contract promises and the two stores stay
    # column-identical. Kills a mutant that drops the EXCLUDE clause.
    host = _host(tenant_router=_TenantRouter(has_config=True))
    assert "EXCLUDE (tenant_id)" in host._qualify_table("orders", "acme")


def test_qualify_table_aliases_the_subquery_back_to_the_table_name():
    # The alias is what keeps every caller's WHERE/ORDER BY/JOIN working unchanged
    # against a relation that is no longer a table.
    host = _host(tenant_router=_TenantRouter(has_config=True))
    assert host._qualify_table("orders", "acme").endswith('AS "orders"')


def test_qualify_table_without_a_tenant_emits_no_predicate(monkeypatch):
    # Unscoped read (auth disabled): no WHERE clause at all — not `WHERE tenant_id
    # = 'None'`, and not a silently dropped EXCLUDE either.
    monkeypatch.setattr(sql_builder_module, "get_current_tenant_id", lambda default=None: None)
    host = _host(tenant_router=_TenantRouter(has_config=True))
    scoped = host._qualify_table("orders", None)
    assert scoped == SCOPED_ORDERS_UNSCOPED
    assert "WHERE" not in scoped


def test_qualify_table_uses_cache_when_present():
    # A pre-seeded entry is returned without recomputation. Kills the
    # `cache is not None and cache_key in cache` guard flips.
    cache = {("orders", "tenant_id = 'acme'"): "CACHED"}
    host = _host(tenant_router=_TenantRouter(has_config=True), cache=cache)
    assert host._qualify_table("orders", "acme") == "CACHED"


def test_qualify_table_writes_result_to_cache():
    cache: dict = {}
    host = _host(tenant_router=_TenantRouter(has_config=True), cache=cache)
    host._qualify_table("orders", "acme")
    assert cache[("orders", "tenant_id = 'acme'")] == SCOPED_ORDERS_ACME


def test_qualify_table_cache_never_serves_one_tenant_the_other_relation():
    # Why the cache is keyed by the predicate: two tenants asking for the same
    # table must not share an entry. Kills a cache_key mutant that drops the
    # tenant component — which would hand whichever tenant asked second the
    # first one's rows.
    cache: dict = {}
    host = _host(tenant_router=_TenantRouter(has_config=True), cache=cache)
    acme = host._qualify_table("orders", "acme")
    demo = host._qualify_table("orders", "demo")
    assert acme != demo
    assert "tenant_id = 'acme'" in acme
    assert "tenant_id = 'demo'" in demo


def test_qualify_table_propagates_an_invalid_tenant_id():
    host = _host(tenant_router=_TenantRouter(has_config=True))
    with pytest.raises(ValueError, match="Invalid tenant id"):
        host._qualify_table("orders", "acme'; DROP TABLE orders--")


def test_qualify_table_refuses_an_unscoped_read_of_a_multi_tenant_table(monkeypatch):
    # No tenant context *and* the table holds somebody else's rows: the caller
    # gets a refusal, not everyone's data. This is the branch the probe exists
    # to feed, and until now nothing reached it — the host doubles had no store,
    # so `_holds_foreign_tenant_rows` always short-circuited to False and the
    # guard was never taken in a test.
    monkeypatch.setattr(sql_builder_module, "get_current_tenant_id", lambda default=None: None)
    backend = _Backend(rows=[(1,)])
    host = _host(tenant_router=_TenantRouter(has_config=True), backend=backend)
    with pytest.raises(ValueError, match="Tenant context is required"):
        host._qualify_table("orders", None)
    # And it refused because of *this* table. A mutant that probes something
    # else still finds a row and still raises, so the exception alone does not
    # prove the guard asked the right question.
    assert backend.queries == [FOREIGN_TENANT_PROBE]


def test_qualify_table_allows_an_unscoped_read_of_a_single_tenant_table(monkeypatch):
    # The other half of the same branch: a store whose rows all belong to the
    # default tenant has nothing to leak, so the deployment that never sets a
    # tenant keeps reading.
    monkeypatch.setattr(sql_builder_module, "get_current_tenant_id", lambda default=None: None)
    host = _host(tenant_router=_TenantRouter(has_config=True), backend=_Backend(rows=[]))
    assert host._qualify_table("orders", None) == SCOPED_ORDERS_UNSCOPED


def test_qualify_table_does_not_probe_when_a_tenant_is_in_context():
    # The probe only means anything for an unscoped read. Running it on the
    # scoped path would add a query per table per request, and a mutant that
    # loosens the `predicate is None` guard into `or` does exactly that.
    backend = _Backend(rows=[(1,)])
    host = _host(tenant_router=_TenantRouter(has_config=True), backend=backend)
    assert host._qualify_table("orders", "acme") == SCOPED_ORDERS_ACME
    assert backend.queries == []


# --------------------------------------------------------------------------- #
# _scope_sql: the same boundary, applied to SQL the engine did not build itself
# (metric templates, NL-generated SQL).
# --------------------------------------------------------------------------- #


def test_scope_sql_scopes_a_known_table():
    host = _host(tenant_router=_TenantRouter(has_config=True))
    scoped = host._scope_sql("SELECT * FROM orders", "acme")
    assert scoped == f"SELECT * FROM {SCOPED_ORDERS_ACME}"


def test_scope_sql_scopes_pipeline_events():
    # pipeline_events is added to known_tables outside the catalog; pin that the
    # `.add("pipeline_events")` line is real.
    host = _host(catalog=_Catalog("orders"), tenant_router=_TenantRouter(has_config=True))
    scoped = host._scope_sql("SELECT * FROM pipeline_events", "acme")
    assert "EXCLUDE (tenant_id) FROM pipeline_events WHERE tenant_id = 'acme'" in scoped


def test_scope_sql_leaves_unknown_table_untouched():
    # A table not in the catalog is not a serving table, so it is not scoped.
    host = _host(catalog=_Catalog("orders"), tenant_router=_TenantRouter(has_config=True))
    scoped = host._scope_sql("SELECT * FROM widgets", "acme")
    assert "tenant_id" not in scoped
    assert "widgets" in scoped


def test_scope_sql_does_not_scope_a_cte_name():
    # A CTE named like a catalog table is a local alias, not the physical table.
    # Kills dropping the cte_sources skip.
    host = _host(catalog=_Catalog("orders"), tenant_router=_TenantRouter(has_config=True))
    scoped = host._scope_sql("WITH orders AS (SELECT 1 AS id) SELECT id FROM orders", "acme")
    assert "tenant_id" not in scoped


def test_scope_sql_scopes_the_physical_table_shadowed_by_a_cte_of_the_same_name():
    # `WITH orders AS (SELECT * FROM orders) SELECT * FROM orders`: the INNER
    # reference is physical and must be scoped; the outer one is the CTE and must
    # not be. A global cte-name skip would leave the physical read unscoped and
    # hand back every tenant's rows (audit_30_06_26.md D1).
    host = _host(catalog=_Catalog("orders"), tenant_router=_TenantRouter(has_config=True))
    scoped = host._scope_sql("WITH orders AS (SELECT * FROM orders) SELECT * FROM orders", "acme")
    assert scoped.count("tenant_id = 'acme'") == 1


def test_scope_sql_fails_closed_on_a_recursive_cte_shadowing_a_table():
    # A recursive CTE's anchor reference cannot be safely re-scoped (it is
    # genuinely ambiguous with the recursion), and no legitimate query names one
    # after a physical table. Fail closed rather than leak.
    host = _host(catalog=_Catalog("orders"), tenant_router=_TenantRouter(has_config=True))
    # The message names the table it refused over: an operator reading the 503
    # needs to know which one, and pinning the rendered name is also what stops a
    # mutant from reporting `['ORDERS']` while the check itself still works.
    with pytest.raises(
        ValueError, match=r"Recursive CTE shadows tenant-scoped table\(s\): \['orders'\]"
    ):
        host._scope_sql(
            "WITH RECURSIVE orders AS (SELECT 1 AS id UNION ALL SELECT id FROM orders) "
            "SELECT id FROM orders",
            "acme",
        )


def test_scope_sql_allows_a_recursive_cte_that_shadows_nothing():
    # The rule above is about *shadowing*, not about recursion. A recursive CTE
    # whose name collides with no serving table is an ordinary query and has to
    # keep working — without this, a guard that refused every `WITH RECURSIVE`
    # would look identical to one that refused only the dangerous ones.
    host = _host(catalog=_Catalog("orders"), tenant_router=_TenantRouter(has_config=True))
    scoped = host._scope_sql(
        "WITH RECURSIVE counter AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM counter) "
        "SELECT n FROM counter",
        "acme",
    )
    assert "counter" in scoped


def test_scope_sql_unscoped_still_hides_the_tenant_column(monkeypatch):
    # No tenant (auth disabled) -> no predicate, but the read still goes through
    # the scoped relation, so tenant_id never surfaces in a caller's `SELECT *`.
    monkeypatch.setattr(sql_builder_module, "get_current_tenant_id", lambda default=None: None)
    host = _host(catalog=_Catalog("orders"), tenant_router=_TenantRouter(has_config=True))
    scoped = host._scope_sql("SELECT * FROM orders", None)
    assert scoped == f"SELECT * FROM {SCOPED_ORDERS_UNSCOPED}"


def test_scope_sql_returns_sql_untouched_when_it_names_no_serving_table():
    host = _host(catalog=_Catalog("orders"), tenant_router=_TenantRouter(has_config=True))
    sql = "SELECT 1 AS one"
    assert host._scope_sql(sql, "acme") == sql


# --------------------------------------------------------------------------- #
# Targeted mutant-killers: the re-scope of an already-qualified name, the
# skip-condition boolean structure, continue-vs-break, and the forwarded tenant.
# --------------------------------------------------------------------------- #


def test_scope_sql_rescopes_a_table_that_arrived_already_qualified():
    # A name that arrives schema/catalog-qualified is replaced wholesale, so a
    # qualified name can never reach around the boundary into another store.
    # validate_nl_sql rejects qualified NL SQL; this is the backstop for any other
    # caller (audit_28_06_26.md #5).
    host = _host(catalog=_Catalog("orders"), tenant_router=_TenantRouter(has_config=True))
    out = host._scope_sql("SELECT * FROM oldcat.oldschema.orders", "acme")
    assert "oldcat" not in out
    assert "oldschema" not in out
    assert out == f"SELECT * FROM {SCOPED_ORDERS_ACME}"


def test_scope_sql_skips_unknown_then_scopes_known():
    # An unknown table is skipped with continue (not break), so a later known
    # table is still scoped. A continue->break mutant leaves `orders` unscoped.
    host = _host(catalog=_Catalog("orders"), tenant_router=_TenantRouter(has_config=True))
    out = host._scope_sql("SELECT * FROM widgets JOIN orders ON widgets.id = orders.id", "acme")
    assert "tenant_id = 'acme'" in out
    assert "FROM widgets" in out


def test_scope_sql_scopes_every_known_table_in_the_statement():
    # Two serving tables in one statement -> both scoped. A loop that stops after
    # the first leaks the second.
    host = _host(
        catalog=_Catalog("orders", "customers"),
        tenant_router=_TenantRouter(has_config=True),
    )
    out = host._scope_sql("SELECT * FROM orders JOIN customers ON orders.id = customers.id", "acme")
    assert out.count("tenant_id = 'acme'") == 2


def test_scope_sql_forwards_the_tenant_id_to_qualify_table():
    # _qualify_table is called for each known, non-CTE table with the forwarded
    # tenant id — and NOT for unknown tables. Pins the `not-in-known OR in-cte`
    # boolean structure (an AND-flip would scope unknown tables) and the forwarded
    # tenant (a `->None` would build an unscoped relation for a scoped caller).
    calls: list[tuple[str, str | None]] = []
    host = _host(catalog=_Catalog("orders"), tenant_router=_TenantRouter(has_config=True))
    original = host._qualify_table
    host._qualify_table = (  # type: ignore[method-assign]
        lambda name, tid: calls.append((name, tid)) or original(name, tid)
    )
    host._scope_sql("SELECT * FROM widgets JOIN orders ON widgets.id = orders.id", "acme")
    assert calls == [("orders", "acme")]
