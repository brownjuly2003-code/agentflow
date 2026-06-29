"""Narrow, duckdb-free mutation test for the tenant SQL builder
(src/serving/semantic_layer/query/sql_builder.py).

This is the test the mutation gate runs against
``serving/semantic_layer/query/sql_builder.py`` (see scripts/mutation_report.py
MODULE_TARGETS). Every entity/metric SQL string the engine executes flows through
``_scope_sql`` / ``_qualify_table`` here, so a surviving mutant in the
tenant-schema qualification is a cross-tenant read (audit_28_06_26.md #5), exactly
the kind of code a mutation gate should pin.

Three design rules, shared with test_rate_limiter_mutation.py /
test_masking_mutation.py / test_sql_guard_mutation.py (see fable_handoff.md
cont.16-19):

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


def _src_package_available() -> bool:
    # In the mutation harness the workspace has no top-level `src` package
    # (only `serving`); under ordinary pytest `src` is the real package.
    try:
        import src  # noqa: F401

        return True
    except ModuleNotFoundError:
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


if not _src_package_available():
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


def test_resolve_tenant_id_defaults_to_demo_without_config():
    # No tenant config -> default_tenant is "demo", handed to the context reader.
    host = _host(tenant_router=_TenantRouter(has_config=False))
    assert host._resolve_tenant_id(None) == "demo"


def test_resolve_tenant_id_no_default_when_config_present():
    # With a tenant config the default is None (a multi-tenant deployment must
    # not silently fall back to "demo"). Kills `not self._tenant_router...` flip
    # and the "demo" literal leaking into the configured path.
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
    # mutant would drop "demo"). Echo the default back to prove it was passed.
    monkeypatch.setattr(sql_builder_module, "get_current_tenant_id", lambda default=None: default)
    host = _host(tenant_router=_TenantRouter(has_config=False))
    assert host._resolve_tenant_id(None) == "demo"


# --------------------------------------------------------------------------- #
# _get_tenant_schema: schema lookup + identifier validation.
# --------------------------------------------------------------------------- #


def test_get_tenant_schema_returns_valid_schema():
    host = _host(
        tenant_router=_TenantRouter(has_config=True, schema_by_tenant={"acme": "acme_schema"})
    )
    assert host._get_tenant_schema("acme") == "acme_schema"


def test_get_tenant_schema_returns_none_when_unmapped():
    # Unknown tenant -> get_duckdb_schema returns None -> early None. Kills the
    # `if schema is None` flip (which would fall through to the regex on None).
    host = _host(tenant_router=_TenantRouter(has_config=True, schema_by_tenant={}))
    assert host._get_tenant_schema("acme") is None


def test_get_tenant_schema_rejects_invalid_identifier():
    host = _host(
        tenant_router=_TenantRouter(has_config=True, schema_by_tenant={"acme": "bad-schema!"})
    )
    with pytest.raises(ValueError, match="Invalid DuckDB schema 'bad-schema!' for tenant 'acme'"):
        host._get_tenant_schema("acme")


def test_get_tenant_schema_accepts_leading_underscore():
    # The regex allows a leading underscore; pin it so `[A-Za-z_]`->`[A-Za-z]`
    # (which would reject `_staging`) dies.
    host = _host(
        tenant_router=_TenantRouter(has_config=True, schema_by_tenant={"acme": "_staging"})
    )
    assert host._get_tenant_schema("acme") == "_staging"


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
# _qualify_table: cache, cross-tenant guard, schema qualification.
# --------------------------------------------------------------------------- #


def test_qualify_table_qualifies_with_tenant_schema():
    host = _host(
        tenant_router=_TenantRouter(has_config=True, schema_by_tenant={"acme": "acme_schema"}),
    )
    assert host._qualify_table("orders", "acme") == '"acme_schema"."orders"'


def test_qualify_table_returns_bare_name_when_no_schema():
    # resolved tenant maps to no schema -> the table is returned unqualified.
    host = _host(tenant_router=_TenantRouter(has_config=False, schema_by_tenant={}))
    assert host._qualify_table("orders", "acme") == "orders"


def test_qualify_table_uses_cache_when_present():
    # A pre-seeded cache entry is returned without recomputation. Kills the
    # `cache is not None and cache_key in cache` guard flips.
    cache = {("orders", "acme"): "CACHED"}
    host = _host(
        tenant_router=_TenantRouter(has_config=True, schema_by_tenant={"acme": "acme_schema"}),
        cache=cache,
    )
    assert host._qualify_table("orders", "acme") == "CACHED"


def test_qualify_table_writes_qualified_result_to_cache():
    cache: dict = {}
    host = _host(
        tenant_router=_TenantRouter(has_config=True, schema_by_tenant={"acme": "acme_schema"}),
        cache=cache,
    )
    host._qualify_table("orders", "acme")
    assert cache[("orders", "acme")] == '"acme_schema"."orders"'


def test_qualify_table_writes_bare_name_to_cache():
    cache: dict = {}
    host = _host(tenant_router=_TenantRouter(has_config=False, schema_by_tenant={}), cache=cache)
    host._qualify_table("orders", "acme")
    assert cache[("orders", "acme")] == "orders"


def test_qualify_table_rejects_invalid_schema():
    host = _host(
        tenant_router=_TenantRouter(has_config=True, schema_by_tenant={"acme": "bad schema"}),
    )
    with pytest.raises(ValueError, match="Invalid DuckDB schema 'bad schema' for tenant 'acme'"):
        host._qualify_table("orders", "acme")


def test_qualify_table_requires_tenant_context_for_scoped_table(monkeypatch):
    # resolved tenant is None but a configured tenant owns columns for the table
    # -> ambiguous, so reading it without a tenant must raise (no silent
    # cross-tenant read). Pins the message and the table name.
    monkeypatch.setattr(sql_builder_module, "get_current_tenant_id", lambda default=None: None)
    router = _TenantRouter(
        has_config=True,
        schema_by_tenant={None: None},
        tenants=(_Tenant("acme_schema"),),
    )
    host = _host(tenant_router=router, table_columns={'"acme_schema"."orders"': {"id"}})
    with pytest.raises(
        ValueError, match="Tenant context is required for tenant-scoped table 'orders'"
    ):
        host._qualify_table("orders", None)


def test_qualify_table_no_context_passes_when_no_tenant_owns_table(monkeypatch):
    # Same None-context path, but no configured tenant has columns for the table
    # -> no raise, falls through to the (here unmapped) schema -> bare name. Kills
    # a mutant that always raises in the loop.
    monkeypatch.setattr(sql_builder_module, "get_current_tenant_id", lambda default=None: None)
    router = _TenantRouter(
        has_config=True,
        schema_by_tenant={None: None},
        tenants=(_Tenant("acme_schema"),),
    )
    host = _host(tenant_router=router, table_columns={})
    assert host._qualify_table("orders", None) == "orders"


# --------------------------------------------------------------------------- #
# _scope_sql: the core. Two paths -- no tenant schema (validate-only) and
# tenant schema (rewrite every known table into the schema).
# --------------------------------------------------------------------------- #


def test_scope_sql_rewrites_known_table_into_tenant_schema():
    host = _host(
        tenant_router=_TenantRouter(has_config=True, schema_by_tenant={"acme": "acme_schema"}),
    )
    scoped = host._scope_sql("SELECT * FROM orders", "acme")
    assert scoped == 'SELECT * FROM "acme_schema"."orders"'


def test_scope_sql_rewrites_pipeline_events_table():
    # pipeline_events is added to known_tables outside the catalog; pin that the
    # `.add("pipeline_events")` line is real.
    host = _host(
        catalog=_Catalog("orders"),
        tenant_router=_TenantRouter(has_config=True, schema_by_tenant={"acme": "acme_schema"}),
    )
    scoped = host._scope_sql("SELECT * FROM pipeline_events", "acme")
    assert scoped == 'SELECT * FROM "acme_schema"."pipeline_events"'


def test_scope_sql_leaves_unknown_table_untouched():
    # A table not in the catalog is not rewritten even under a tenant schema.
    host = _host(
        catalog=_Catalog("orders"),
        tenant_router=_TenantRouter(has_config=True, schema_by_tenant={"acme": "acme_schema"}),
    )
    scoped = host._scope_sql("SELECT * FROM widgets", "acme")
    assert "acme_schema" not in scoped
    assert "widgets" in scoped


def test_scope_sql_does_not_rewrite_cte_name():
    # A CTE named like a catalog table must not be schema-qualified (it's a local
    # alias, not the physical table). Kills dropping the `in cte_names` skip.
    host = _host(
        catalog=_Catalog("orders"),
        tenant_router=_TenantRouter(has_config=True, schema_by_tenant={"acme": "acme_schema"}),
    )
    scoped = host._scope_sql("WITH orders AS (SELECT 1 AS id) SELECT id FROM orders", "acme")
    assert "acme_schema" not in scoped


def test_scope_sql_no_schema_returns_sql_unchanged():
    # No tenant schema -> the SQL text is returned verbatim (validation-only path).
    host = _host(tenant_router=_TenantRouter(has_config=False, schema_by_tenant={}))
    sql = "SELECT * FROM orders"
    assert host._scope_sql(sql, "acme") == sql


def test_scope_sql_no_schema_enforces_tenant_context(monkeypatch):
    # In the no-schema path each known unqualified table is still routed through
    # _qualify_table, so an ambiguous tenant-scoped table raises rather than
    # leaking. Pins that the no-schema branch actually calls _qualify_table.
    monkeypatch.setattr(sql_builder_module, "get_current_tenant_id", lambda default=None: None)
    router = _TenantRouter(
        has_config=True,
        schema_by_tenant={None: None},
        tenants=(_Tenant("acme_schema"),),
    )
    host = _host(
        catalog=_Catalog("orders"),
        tenant_router=router,
        table_columns={'"acme_schema"."orders"': {"id"}},
    )
    with pytest.raises(
        ValueError, match="Tenant context is required for tenant-scoped table 'orders'"
    ):
        host._scope_sql("SELECT * FROM orders", None)


def test_scope_sql_no_schema_skips_already_qualified_table(monkeypatch):
    # An already schema-qualified table in the no-schema path is skipped (db set),
    # so it does not trigger the tenant-context guard. Kills dropping the
    # `table.db` part of the skip condition.
    calls: list[tuple[str, str | None]] = []
    monkeypatch.setattr(sql_builder_module, "get_current_tenant_id", lambda default=None: None)
    router = _TenantRouter(has_config=True, schema_by_tenant={None: None})
    host = _host(catalog=_Catalog("orders"), tenant_router=router)
    original = host._qualify_table

    def _spy(table_name: str, tenant_id: str | None) -> str:
        calls.append((table_name, tenant_id))
        return original(table_name, tenant_id)

    host._qualify_table = _spy  # type: ignore[method-assign]
    host._scope_sql('SELECT * FROM other_schema."orders"', None)
    assert calls == []  # qualified table was skipped, _qualify_table not called


# --------------------------------------------------------------------------- #
# Targeted mutant-killers: identifier-regex casing, the explicit-tenant
# short-circuit, the skip-condition boolean structure, continue-vs-break, and
# the catalog-clearing in the re-scope branch.
# --------------------------------------------------------------------------- #


def test_get_tenant_schema_accepts_uppercase_identifier():
    # The identifier regex must accept uppercase letters: a `[A-Za-z_]`->`[a-za-z_]`
    # mutant would reject a valid mixed-case schema and raise. Pin acceptance.
    host = _host(tenant_router=_TenantRouter(has_config=True, schema_by_tenant={"acme": "Acme_DW"}))
    assert host._get_tenant_schema("acme") == "Acme_DW"


def test_qualify_table_accepts_uppercase_schema():
    # Same regex-casing pin on the _qualify_table copy of the check.
    host = _host(tenant_router=_TenantRouter(has_config=True, schema_by_tenant={"acme": "Acme_DW"}))
    assert host._qualify_table("orders", "acme") == '"Acme_DW"."orders"'


def test_qualify_table_with_explicit_tenant_skips_ambiguity_scan():
    # resolved tenant is not None -> the `resolved is None AND has_config` guard
    # is False, so the cross-tenant ambiguity scan is skipped. An `and`->`or`
    # mutant would enter the scan and wrongly raise on a foreign-tenant column
    # match. Pin that an explicit tenant qualifies without raising.
    router = _TenantRouter(
        has_config=True,
        schema_by_tenant={"acme": "acme_schema"},
        tenants=(_Tenant("other_schema"),),
    )
    host = _host(tenant_router=router, table_columns={'"other_schema"."orders"': {"id"}})
    assert host._qualify_table("orders", "acme") == '"acme_schema"."orders"'


def test_scope_sql_no_schema_qualifies_only_known_non_cte_tables():
    # In the no-schema path _qualify_table is called for each known, unqualified,
    # non-CTE table with the forwarded tenant id -- and NOT for unknown tables.
    # Pins: the `not-in-known OR in-cte` boolean structure (an AND-flip would
    # qualify unknown tables), continue-not-break (a break would stop before the
    # known table), and the forwarded tenant id (a `->None` would drop it).
    calls: list[tuple[str, str | None]] = []
    router = _TenantRouter(has_config=False, schema_by_tenant={"acme": None})
    host = _host(catalog=_Catalog("orders"), tenant_router=router)
    original = host._qualify_table
    host._qualify_table = (  # type: ignore[method-assign]
        lambda name, tid: calls.append((name, tid)) or original(name, tid)
    )
    host._scope_sql("SELECT * FROM widgets JOIN orders ON widgets.id = orders.id", "acme")
    assert calls == [("orders", "acme")]


def test_scope_sql_no_schema_skips_cte_named_like_table():
    # A CTE named like a catalog table must not be qualified. The cte-name check
    # lowercases the name; an `in cte_names`->`upper() in cte_names` mutant would
    # miss the lowercase CTE and qualify it. Pin that no qualify call happens.
    calls: list[tuple[str, str | None]] = []
    router = _TenantRouter(has_config=False, schema_by_tenant={"acme": None})
    host = _host(catalog=_Catalog("orders"), tenant_router=router)
    original = host._qualify_table
    host._qualify_table = (  # type: ignore[method-assign]
        lambda name, tid: calls.append((name, tid)) or original(name, tid)
    )
    host._scope_sql("WITH orders AS (SELECT 1 AS id) SELECT id FROM orders", "acme")
    assert calls == []


def test_scope_sql_schema_skips_unknown_then_qualifies_known():
    # schema branch: an unknown table is skipped with continue (not break) so a
    # later known table is still rewritten. A continue->break mutant stops early
    # and leaves 'orders' unqualified.
    host = _host(
        catalog=_Catalog("orders"),
        tenant_router=_TenantRouter(has_config=True, schema_by_tenant={"acme": "acme_schema"}),
    )
    out = host._scope_sql("SELECT * FROM widgets JOIN orders ON widgets.id = orders.id", "acme")
    assert '"acme_schema"."orders"' in out
    assert '"acme_schema"."widgets"' not in out  # unknown table stays bare


def test_scope_sql_schema_clears_existing_qualification():
    # A table arriving already catalog/schema-qualified is fully re-scoped into
    # the caller's tenant schema -- the foreign catalog is cleared
    # (audit_28_06_26.md #5). Pins table.set("catalog", None): a mutant that
    # mis-keys or skips the catalog clear leaves the foreign catalog in the SQL.
    host = _host(
        catalog=_Catalog("orders"),
        tenant_router=_TenantRouter(has_config=True, schema_by_tenant={"acme": "acme_schema"}),
    )
    out = host._scope_sql("SELECT * FROM oldcat.oldschema.orders", "acme")
    assert out == 'SELECT * FROM "acme_schema"."orders"'
