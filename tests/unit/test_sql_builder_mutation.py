"""Narrow, duckdb-free mutation test for the tenant SQL builder
(src/serving/semantic_layer/query/sql_builder.py).

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

3. **Import shims.** The mutation harness copies ``src/serving`` to a top-level
   ``serving`` package *without* ``src`` (copying ``src`` would shadow it). Three
   things on sql_builder's import path would otherwise fail or drag duckdb in:
   ``from src.serving.api.auth import get_current_tenant_id`` (no ``src``), the
   ``serving.semantic_layer.query`` package ``__init__`` (``from .engine import
   QueryEngine`` -> duckdb) and ``.contracts`` (imports the duckdb backend for
   type hints). We register stand-ins for all three before importing the module.
   They are only used as a default-arg helper and as runtime-unused type hints
   (``from __future__ import annotations`` keeps the annotations as strings), so
   the stand-ins change no executed logic. Under ordinary pytest the real ``src``
   package is importable, so no shim is installed and the real modules load.

Reproduced at 96.0% (killed 167, survived 7) via the WSL/mutmut harness (py3.10);
the CI gate (mutation.yml on py3.11) is the source of truth. The 7 survivors are
genuine equivalent mutants, not gaps: four mutate the *string* inside
``cast("dict[...]", value)`` -- the runtime ``typing.cast`` ignores its first
argument, so any text change there is a no-op -- and three flip
``parse_one(..., dialect="duckdb")`` / ``parsed.sql(dialect=...)`` to
``dialect=None``, which renders the plain SELECTs this builder handles identically.
"""

from __future__ import annotations

import sys
import types
from datetime import datetime


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
    # src.serving.api.auth.get_current_tenant_id: a contextvar reader in
    # production; here a default-arg passthrough (the host controls the tenant).
    _ensure_module("src")
    serving_pkg = _ensure_module("src.serving")
    api_pkg = _ensure_module("src.serving.api")
    auth_pkg = _ensure_module("src.serving.api.auth")

    def get_current_tenant_id(default: str | None = None) -> str | None:
        return default

    auth_pkg.get_current_tenant_id = get_current_tenant_id
    api_pkg.auth = auth_pkg
    serving_pkg.api = api_pkg

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
    from src.serving.semantic_layer.query import sql_builder as sql_builder_module

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


class _Tenant:
    def __init__(self, duckdb_schema: str) -> None:
        self.duckdb_schema = duckdb_schema


class _TenantsConfig:
    def __init__(self, tenants: tuple[_Tenant, ...]) -> None:
        self.tenants = tenants


class _TenantRouter:
    def __init__(
        self,
        *,
        has_config: bool = False,
        schema_by_tenant: dict[str | None, str] | None = None,
        tenants: tuple[_Tenant, ...] = (),
    ) -> None:
        self._has_config = has_config
        self._schema_by_tenant = dict(schema_by_tenant or {})
        self._tenants = tenants

    def has_config(self) -> bool:
        return self._has_config

    def get_duckdb_schema(self, tenant_id: str | None) -> str | None:
        return self._schema_by_tenant.get(tenant_id)

    def load(self) -> _TenantsConfig:
        return _TenantsConfig(self._tenants)


class _Host(SQLBuilderMixin):
    def __init__(
        self,
        *,
        catalog: _Catalog,
        tenant_router: _TenantRouter,
        table_columns: dict[str, set[str]] | None = None,
        cache: dict | None = None,
    ) -> None:
        self.catalog = catalog
        self._tenant_router = tenant_router
        self._table_columns_map = dict(table_columns or {})
        if cache is not None:
            self._qualified_table_cache = cache

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
# _qualify_table: the scoped relation every entity read goes through, plus its
# cache. This is the chokepoint — a surviving mutant here is a cross-tenant read.
# --------------------------------------------------------------------------- #

SCOPED_ORDERS_ACME = (
    '(SELECT * EXCLUDE (tenant_id) FROM orders WHERE tenant_id = \'acme\') AS "orders"'
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
    with pytest.raises(ValueError, match="Recursive CTE shadows tenant-scoped table"):
        host._scope_sql(
            "WITH RECURSIVE orders AS (SELECT 1 AS id UNION ALL SELECT id FROM orders) "
            "SELECT id FROM orders",
            "acme",
        )


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
