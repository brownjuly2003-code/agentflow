from __future__ import annotations

import base64
import json
import re
import ssl
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import sqlglot
from sqlglot import exp

from src.serving.backends import BackendExecutionError, BackendMissingTableError, ServingBackend
from src.serving.semantic_layer.sql_literals import quote_sql_literal

# ClickHouse expresses filtered aggregation through -If combinators, not the
# standard `<agg> FILTER (WHERE ...)` clause.
_FILTERED_AGG_COMBINATORS: dict[type[exp.Expr], str] = {
    exp.Count: "countIf",
    exp.Sum: "sumIf",
    exp.Avg: "avgIf",
    exp.Min: "minIf",
    exp.Max: "maxIf",
}

# The tenant boundary, as it must exist physically on a shared store (P0-1).
# Every serving table leads its sorting key with `tenant_id`, so two tenants'
# rows that share an entity id are distinct rows rather than two versions of
# one ReplacingMergeTree row. `ensure_schema` refuses to serve a store whose
# tables disagree with this — see `assert_tenant_key`.
TENANT_SORTING_KEYS: dict[str, tuple[str, ...]] = {
    "orders_v2": ("tenant_id", "order_id"),
    "products_current": ("tenant_id", "product_id"),
    "sessions_aggregated": ("tenant_id", "session_id"),
    "users_enriched": ("tenant_id", "user_id"),
    "pipeline_events": ("tenant_id", "topic", "processed_at", "event_id"),
}

# The entity primary key each table replaces on, i.e. its sorting key minus the
# tenant lead. Used by the migration to rebuild a table and by the read path to
# know what a tenant-scoped row is keyed by.
TENANT_ENTITY_KEYS: dict[str, str] = {
    table: key[1] for table, key in TENANT_SORTING_KEYS.items() if table != "pipeline_events"
}

# One definition per serving table, shared by `ensure_schema` and by the
# tenant-key migration, so a rebuilt table can never drift from a freshly
# provisioned one. `af_updated_at` is MATERIALIZED — server-side on insert,
# absent from `SELECT *` and from `table_columns` — so the logical schema stays
# identical to the DuckDB store.
SERVING_TABLE_DDL: dict[str, str] = {
    "orders_v2": """(
        tenant_id String DEFAULT 'default',
        order_id String,
        user_id String,
        status String,
        total_amount Decimal(10, 2),
        currency String,
        created_at DateTime,
        af_updated_at DateTime64(3) MATERIALIZED now64(3)
    ) ENGINE = ReplacingMergeTree(af_updated_at)
    ORDER BY (tenant_id, order_id)""",
    "products_current": """(
        tenant_id String DEFAULT 'default',
        product_id String,
        name String,
        category String,
        price Decimal(10, 2),
        in_stock UInt8,
        stock_quantity Int32,
        af_updated_at DateTime64(3) MATERIALIZED now64(3)
    ) ENGINE = ReplacingMergeTree(af_updated_at)
    ORDER BY (tenant_id, product_id)""",
    "sessions_aggregated": """(
        tenant_id String DEFAULT 'default',
        session_id String,
        user_id Nullable(String),
        started_at DateTime,
        ended_at Nullable(DateTime),
        duration_seconds Nullable(Float64),
        event_count Int32,
        unique_pages Int32,
        funnel_stage String,
        is_conversion UInt8,
        af_updated_at DateTime64(3) MATERIALIZED now64(3)
    ) ENGINE = ReplacingMergeTree(af_updated_at)
    ORDER BY (tenant_id, session_id)""",
    "users_enriched": """(
        tenant_id String DEFAULT 'default',
        user_id String,
        total_orders Int32,
        total_spent Decimal(10, 2),
        first_order_at DateTime,
        last_order_at DateTime,
        preferred_category Nullable(String),
        af_updated_at DateTime64(3) MATERIALIZED now64(3)
    ) ENGINE = ReplacingMergeTree(af_updated_at)
    ORDER BY (tenant_id, user_id)""",
    "pipeline_events": """(
        event_id String,
        topic String,
        tenant_id String DEFAULT 'default',
        entity_id Nullable(String),
        event_type Nullable(String),
        latency_ms Nullable(Int32),
        processed_at DateTime
    ) ENGINE = MergeTree()
    ORDER BY (tenant_id, topic, processed_at, event_id)""",
}

# The insertable columns of each table, in DDL order and *without* `tenant_id`:
# what a tenant-key migration copies across from a table that predates the
# tenant column. `af_updated_at` is excluded — MATERIALIZED columns cannot be
# inserted into.
SERVING_TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "orders_v2": ("order_id", "user_id", "status", "total_amount", "currency", "created_at"),
    "products_current": (
        "product_id",
        "name",
        "category",
        "price",
        "in_stock",
        "stock_quantity",
    ),
    "sessions_aggregated": (
        "session_id",
        "user_id",
        "started_at",
        "ended_at",
        "duration_seconds",
        "event_count",
        "unique_pages",
        "funnel_stage",
        "is_conversion",
    ),
    "users_enriched": (
        "user_id",
        "total_orders",
        "total_spent",
        "first_order_at",
        "last_order_at",
        "preferred_category",
    ),
    "pipeline_events": (
        "event_id",
        "topic",
        "entity_id",
        "event_type",
        "latency_ms",
        "processed_at",
    ),
}


def _normalize_key(sorting_key: str) -> tuple[str, ...]:
    """Parse ``system.tables.sorting_key`` ("tenant_id, order_id") into a tuple."""
    return tuple(part.strip() for part in sorting_key.split(",") if part.strip())


def _rewrite_for_clickhouse(node: exp.Expr) -> exp.Expr:
    """AST rewrites the stock duckdb→clickhouse transpile does not cover.

    - ClickHouse has no `<agg> FILTER (WHERE ...)` clause; rewrite the
      aggregates the semantic layer uses to native -If combinators
      (`COUNT(*) FILTER (WHERE c)` → `countIf(c)`). Unknown aggregates are
      left untouched so ClickHouse rejects them loudly server-side.
    - DuckDB's two-argument `quantile_cont(col, q)` transpiles to
      `PERCENTILE_CONT(col, q)`, which ClickHouse does not have: its quantile is
      parametric, `quantile(q)(col)`. Without this the SLO latency SLI would
      have been the one journal read that could not leave DuckDB (audit P0-3).
    - DuckDB `FLOAT` is a 4-byte float and would transpile to `Float32`;
      widen to DOUBLE so the backend keeps its historical Float64
      semantics for ratio metrics.
    """
    if isinstance(node, exp.Filter):
        aggregate = node.this
        condition = node.expression.this
        combinator = _FILTERED_AGG_COMBINATORS.get(type(aggregate))
        if combinator is None:
            return node
        if isinstance(aggregate, exp.Count):
            return exp.func(combinator, condition)
        return exp.func(combinator, aggregate.this, condition)
    if isinstance(node, exp.PercentileCont):
        return exp.Quantile(this=node.this, quantile=node.expression)
    if isinstance(node, exp.DataType) and node.this == exp.DataType.Type.FLOAT:
        return exp.DataType.build("DOUBLE")
    return node


class ClickHouseBackend(ServingBackend):
    """HTTP-based ClickHouse serving backend.

    Query-parameter binding is intentionally *not* used on this path (A-3,
    audit_codex_03_06_26). Unlike ``DuckDBBackend``, which binds positional
    ``?`` placeholders, the semantic layer's ClickHouse branch inlines values
    as quoted literals via ``SQLBuilderMixin._quote_literal`` and calls
    ``execute(sql)`` with no ``params`` (see ``EntityQueryMixin`` /
    ``MetricQueryMixin``: ``use_query_params`` is false whenever the active
    backend is not DuckDB). Injection safety is therefore enforced
    structurally rather than by binding:

    * Values are wrapped as single-quoted literals (``'`` doubled to ``''``)
      and then re-escaped to ClickHouse's own rules by ``_translate_sql`` — the
      sqlglot ``duckdb`` → ``clickhouse`` round-trip parses each literal
      structurally and regenerates it (e.g. a lone backslash becomes ``\\``),
      so a payload cannot break out of its literal even though ClickHouse
      honours backslash escapes that DuckDB does not. Multi-statement or
      unparseable SQL is rejected before it ever reaches the server.
    * Identifiers (table / column / schema names) come from the catalog
      allowlist and ``_quote_identifier`` — never from request data.

    ``params`` is accepted only for interface symmetry with ``ServingBackend``
    and is a documented no-op; the ClickHouse query path never supplies it.
    The injection-neutralisation property is pinned by
    ``tests/unit/test_clickhouse_backend.py::TestTranslateSqlInjectionSafety``
    and ``tests/unit/test_query_engine_injection.py`` (ClickHouse path).
    """

    name = "clickhouse"

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
        secure: bool = False,
        timeout_seconds: int = 10,
    ) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._database = database
        self._secure = secure
        self._timeout_seconds = timeout_seconds
        scheme = "https" if secure else "http"
        self._base_url = f"{scheme}://{host}:{port}"
        # H-C2: when running against HTTPS, validate the server cert
        # against the system trust store explicitly instead of relying on
        # urllib's default (which on some Python builds disables hostname
        # verification when no context is passed).
        self._ssl_context = ssl.create_default_context() if secure else None

    def _request(
        self,
        sql: str,
        *,
        expect_json: bool,
        translate: bool = True,
        final: bool = False,
        use_database: bool = True,
    ) -> str:
        translated_sql = self._translate_sql(sql) if translate else sql
        # `use_database=False` is for bootstrap statements (CREATE DATABASE):
        # setting the session database to one that does not exist yet fails the
        # whole request on a bare server (Docker images pre-create it via
        # CLICKHOUSE_DB, which masked this).
        url = (
            f"{self._base_url}/?database={quote(self._database)}"
            if use_database
            else f"{self._base_url}/?"
        )
        if expect_json:
            url = f"{url}&default_format=JSON"
        if final:
            # The mutable serving tables are ReplacingMergeTree (upserts are
            # modeled as append-a-new-version); `final=1` makes every read see
            # only the latest version per sorting key without the semantic
            # layer having to know the engine's dedup model.
            url = f"{url}&final=1"

        request = Request(url, data=translated_sql.encode("utf-8"), method="POST")
        if self._user or self._password:
            token = base64.b64encode(f"{self._user}:{self._password}".encode()).decode("ascii")
            request.add_header("Authorization", f"Basic {token}")

        try:
            # `context=` is only valid for HTTPS targets; passing it on HTTP
            # urls under some Python stdlib versions raises TypeError, and
            # passing it as an unconditional kwarg breaks test mocks. Build
            # the call kwargs explicitly so HTTP paths stay parameter-clean.
            urlopen_kwargs: dict = {"timeout": self._timeout_seconds}
            if self._ssl_context is not None:
                urlopen_kwargs["context"] = self._ssl_context
            # scheme is fixed to http/https by trusted backend config; HTTPS verifies via the explicit ssl context above
            with urlopen(request, **urlopen_kwargs) as response:  # nosec B310
                decoded: str = response.read().decode("utf-8")
                return decoded
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if "UNKNOWN_TABLE" in detail or "doesn't exist" in detail:
                table_match = re.search(r"table ([^\\s]+)", detail, flags=re.IGNORECASE)
                table_name = table_match.group(1) if table_match else None
                raise BackendMissingTableError(detail.strip(), table_name=table_name) from exc
            raise BackendExecutionError(detail.strip() or str(exc)) from exc
        except URLError as exc:
            raise BackendExecutionError(str(exc.reason)) from exc

    def _translate_sql(self, sql: str) -> str:
        """Transpile DuckDB-flavored semantic-layer SQL to ClickHouse.

        H-C2 (audit-2026-05): a sqlglot parse → AST rewrite → generate
        pipeline replaces the former regex chain, which could corrupt string
        literals and silently mistranslate anything its patterns missed.
        The parser preserves literals structurally; anything it cannot parse
        fails loudly instead of going to the server half-rewritten.
        """
        try:
            statements = sqlglot.parse(sql, read="duckdb")
        except sqlglot.errors.ParseError as exc:
            raise BackendExecutionError(f"SQL translation failed: {exc}") from exc
        parsed = [statement for statement in statements if statement is not None]
        if len(parsed) != 1:
            raise BackendExecutionError(f"expected exactly one SQL statement, got {len(parsed)}")
        rewritten = parsed[0].transform(_rewrite_for_clickhouse)
        translated: str = rewritten.sql(dialect="clickhouse")
        self._assert_scope_preserved(parsed[0], translated)
        return translated

    @staticmethod
    def _table_refs(node: exp.Expr) -> list[tuple[str, str, str]]:
        return sorted(
            (
                (table.catalog or "").lower(),
                (table.db or "").lower(),
                (table.name or "").lower(),
            )
            for table in node.find_all(exp.Table)
        )

    def _assert_scope_preserved(self, source: exp.Expr, translated: str) -> None:
        """Fail closed if the transpile changed any table reference.

        Tenant isolation is enforced upstream by ``_scope_sql``, which replaces
        every physical table reference with a tenant-filtered sub-select aliased
        back to the table's own name (ADR-004). This backend rewrites the SQL
        *after* that guard ran, so the rewrite must never add, drop, or rename a
        table reference — otherwise a transpiler regression could silently drop
        the scoped relation and read another tenant's rows (the same
        rewrite-after-guard seam that produced the historical PII bypasses).

        The check still holds under the column model: the table reference the
        guard compares lives *inside* the sub-select, and the transpile leaves it
        alone (``EXCLUDE`` becomes ClickHouse's ``EXCEPT``, the reference does
        not move). Parse the *generated string* back rather than trusting the
        rewritten AST, so generation-level quoting bugs are caught too.
        """
        try:
            reparsed = sqlglot.parse_one(translated, read="clickhouse")
        except sqlglot.errors.ParseError as exc:
            raise BackendExecutionError(
                f"translated SQL does not re-parse; refusing to execute: {exc}"
            ) from exc
        source_refs = self._table_refs(source)
        translated_refs = self._table_refs(reparsed)
        if source_refs != translated_refs:
            raise BackendExecutionError(
                "SQL translation changed table references "
                f"(before={source_refs}, after={translated_refs}); "
                "refusing to execute a query whose tenant scoping may have been lost."
            )

    def execute(self, sql: str, params: list | None = None) -> list[dict]:
        # `params` is a documented no-op on this backend (see the class
        # docstring): the ClickHouse query path inlines values as literals that
        # `_translate_sql` re-escapes structurally, rather than binding `?`.
        del params
        payload = self._request(sql, expect_json=True, final=True)
        data = json.loads(payload)
        rows: list[dict] = data.get("data", [])
        return rows

    def scalar(self, sql: str, params: list | None = None) -> Any:
        del params
        rows = self.execute(sql)
        if not rows:
            return None
        return next(iter(rows[0].values()))

    def table_columns(self, table_name: str) -> set[str]:
        try:
            # Native ClickHouse introspection — bypasses the duckdb transpile.
            payload = self._request(
                f"DESCRIBE TABLE {table_name}", expect_json=True, translate=False
            )
        except BackendMissingTableError:
            return set()
        except BackendExecutionError as exc:
            if "UNKNOWN_DATABASE" in str(exc):
                return set()
            raise
        rows: list[dict] = json.loads(payload).get("data", [])
        # MATERIALIZED / ALIAS / EPHEMERAL columns (e.g. the ReplacingMergeTree
        # version column `af_updated_at`) are not part of the logical row: they
        # are excluded from `SELECT *` and cannot be INSERTed, so exposing them
        # here would make the semantic layer's column set diverge from the
        # DuckDB store and from the entity contracts.
        return {
            str(row["name"])
            for row in rows
            if "name" in row
            and str(row.get("default_type", "")) not in {"MATERIALIZED", "ALIAS", "EPHEMERAL"}
        }

    def explain(self, sql: str) -> list[tuple]:
        # EXPLAIN itself is ClickHouse syntax, but the wrapped query comes
        # from the DuckDB-flavored semantic layer — transpile it first, then
        # send the assembled statement untouched.
        translated = self._translate_sql(sql)
        raw = self._request(f"EXPLAIN {translated}", expect_json=False, translate=False)
        return [(line,) for line in raw.splitlines() if line.strip()]

    def ensure_schema(self) -> None:
        """Create the serving database and tables (no seed rows).

        The four mutable serving tables are **ReplacingMergeTree**: the pipeline
        models an upsert as appending a new row version keyed by the sorting
        key, ClickHouse collapses versions on merges, and every read on this
        backend runs with ``final=1`` (see ``_request``) so queries always see
        the latest version. The version column ``af_updated_at`` is
        ``MATERIALIZED`` — populated server-side on insert, invisible to
        ``SELECT *`` and to ``table_columns`` — so the logical schema stays
        identical to the DuckDB store. ``pipeline_events`` is an append-only
        journal and stays plain MergeTree.

        Every serving table carries ``tenant_id`` and leads its sorting key with
        it (audit P0-1). On a shared store the tenant boundary has to be in the
        physical schema and in the *write* key, not only in a read filter: with
        ``ORDER BY order_id`` alone, two tenants' rows sharing an ``order_id``
        are the same ReplacingMergeTree row and the later insert *destroys* the
        earlier one — a data-loss bug no read-side predicate can undo.
        ``ORDER BY (tenant_id, order_id)`` makes them distinct rows.

        The key cannot be fixed in place: ClickHouse only appends to a sorting
        key, never prepends, and ``CREATE TABLE IF NOT EXISTS`` against a table
        that already has the old key silently keeps it. So a store provisioned
        before this change must be migrated explicitly
        (``python -m src.serving.provision --migrate``), and ``_assert_tenant_key``
        below refuses to serve a store that still has the old key rather than
        letting it look provisioned.
        """
        self._request(
            f"CREATE DATABASE IF NOT EXISTS {self._database}",
            expect_json=False,
            translate=False,
            use_database=False,
        )
        # n4 (G2 audit): no `branch` column on the ClickHouse journal, unlike the
        # DuckDB embedded schema (ADR 0012 N4, `src/processing/local_pipeline.py`)
        # — deferred, not an oversight. The three-node demo's node-ingest write
        # path (`src/serving/node/ingest.py`) always applies through
        # `_process_event(..., clickhouse_sink=None)`, i.e. it is DuckDB-only
        # today; no ClickHouse caller reads or filters on a branch tag. Add
        # `branch Nullable(String)` to the ALTER loop below (same
        # additive/idempotent pattern) if/when node ingest is ever wired to
        # write through ClickHouse.
        for table, body in SERVING_TABLE_DDL.items():
            self._request(
                f"CREATE TABLE IF NOT EXISTS {self._database}.{table} {body}",
                expect_json=False,
                translate=False,
            )
        self._request(
            f"""
            ALTER TABLE {self._database}.pipeline_events
            ADD COLUMN IF NOT EXISTS tenant_id String DEFAULT 'default'
            """,
            expect_json=False,
            translate=False,
        )
        for column_ddl in (
            "entity_id Nullable(String)",
            "event_type Nullable(String)",
            "latency_ms Nullable(Int32)",
        ):
            self._request(
                f"""
                ALTER TABLE {self._database}.pipeline_events
                ADD COLUMN IF NOT EXISTS {column_ddl}
                """,
                expect_json=False,
                translate=False,
            )

        self.assert_tenant_key()

    def sorting_keys(self) -> dict[str, str]:
        """Actual sorting key of every serving table, as ClickHouse reports it.

        ``system.tables.sorting_key`` renders the key as a comma-separated
        expression list (``ORDER BY (tenant_id, order_id)`` → ``tenant_id,
        order_id``). Missing tables are simply absent from the mapping.
        """
        payload = self._request(
            # the database name is trusted backend config, quoted as a literal
            "SELECT name, sorting_key FROM system.tables WHERE database = "  # nosec B608
            f"{quote_sql_literal(self._database)}",
            expect_json=True,
            translate=False,
        )
        rows: list[dict] = json.loads(payload).get("data", [])
        return {
            str(row["name"]): str(row.get("sorting_key") or "")
            for row in rows
            if isinstance(row, dict) and "name" in row
        }

    def assert_tenant_key(self) -> None:
        """Refuse to serve a store whose tables are not keyed by tenant (P0-1).

        ``CREATE TABLE IF NOT EXISTS`` is a no-op against a table that already
        exists, and ClickHouse cannot prepend a column to an existing sorting
        key. A store provisioned before the tenant key therefore survives
        ``ensure_schema()`` untouched and *looks* provisioned while still
        collapsing two tenants' rows that share an entity id into one
        ReplacingMergeTree row. Silence there is the whole failure mode, so this
        is loud: the operator runs ``python -m src.serving.provision --migrate``.
        """
        actual = self.sorting_keys()
        stale = {
            table: actual[table]
            for table, expected in TENANT_SORTING_KEYS.items()
            if table in actual and _normalize_key(actual[table]) != expected
        }
        if not stale:
            return
        detail = "; ".join(
            f"{table}: ORDER BY ({found or 'tuple()'}), expected "
            f"({', '.join(TENANT_SORTING_KEYS[table])})"
            for table, found in sorted(stale.items())
        )
        raise BackendExecutionError(
            "ClickHouse serving tables predate the tenant sorting key "
            f"(audit P0-1) and cannot be altered in place — {detail}. "
            "Migrate with: python -m src.serving.provision --migrate"
        )

    def migrate_tenant_key(self) -> list[str]:
        """Rebuild every serving table that predates the tenant sorting key.

        The key must lead with ``tenant_id`` and ClickHouse cannot prepend to an
        existing one, so each stale table is rebuilt: stage a new table with the
        right key, copy the rows into it under the ``'default'`` tenant, and swap
        the two. Pre-existing rows become ``'default'`` because that is the
        tenant they were in fact written under — the pipeline stamps events via
        ``_event_tenant()``, which falls back to ``'default'``, and the journal
        rows written alongside them already say exactly that.

        Idempotent and crash-safe. Tables already on the new key are skipped, so
        re-running a completed migration does nothing. The staging table is
        dropped before it is built, so a run interrupted mid-copy leaves a
        partial staging table that the next run discards rather than appends to.
        ``EXCHANGE TABLES`` is atomic on the Atomic database engine (the default
        since 20.10; this repo runs 24.8–25.5), so a crash cannot leave the store
        half-swapped — a reader sees either the old table or the new one.

        Returns the tables it rebuilt.
        """
        # The database has to exist before anything can query system.tables with
        # it as the session database — `--migrate` may run against a store that
        # was never provisioned, where there is simply nothing to migrate.
        self._request(
            f"CREATE DATABASE IF NOT EXISTS {self._database}",
            expect_json=False,
            translate=False,
            use_database=False,
        )
        actual = self.sorting_keys()
        migrated: list[str] = []
        for table, expected in TENANT_SORTING_KEYS.items():
            if table not in actual or _normalize_key(actual[table]) == expected:
                continue
            self._rebuild_with_tenant_key(table)
            migrated.append(table)
        return migrated

    def _rebuild_with_tenant_key(self, table: str) -> None:
        staging = f"{table}__tenant_key"
        columns = ", ".join(SERVING_TABLE_COLUMNS[table])
        self._request(
            f"DROP TABLE IF EXISTS {self._database}.{staging}",
            expect_json=False,
            translate=False,
        )
        self._request(
            f"CREATE TABLE {self._database}.{staging} {SERVING_TABLE_DDL[table]}",
            expect_json=False,
            translate=False,
        )
        # FINAL collapses the ReplacingMergeTree versions on the way out, so the
        # rebuilt table holds one row per entity instead of every version ever
        # appended. (A no-op on the plain-MergeTree journal.)
        self._request(
            # table and column names come from the module's own DDL, never request data
            f"INSERT INTO {self._database}.{staging} (tenant_id, {columns}) "  # nosec B608
            f"SELECT 'default', {columns} FROM {self._database}.{table} FINAL",
            expect_json=False,
            translate=False,
        )
        self._request(
            f"EXCHANGE TABLES {self._database}.{table} AND {self._database}.{staging}",
            expect_json=False,
            translate=False,
        )
        self._request(
            f"DROP TABLE IF EXISTS {self._database}.{staging}",
            expect_json=False,
            translate=False,
        )

    def insert_rows(self, table_name: str, rows: list[dict]) -> None:
        """Append rows via ``FORMAT JSONEachRow``.

        JSONEachRow keeps value escaping structural (no SQL-literal quoting to
        get wrong), which is why the pipeline sink writes through this method
        instead of assembling INSERT literals. Column names come from the row
        keys and are validated as bare identifiers; values are JSON-encoded
        with datetimes rendered in ClickHouse's ``YYYY-MM-DD hh:mm:ss`` form.
        """
        if not rows:
            return
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table_name) is None:
            raise BackendExecutionError(f"invalid table name {table_name!r}")
        columns = list(rows[0].keys())
        for row in rows:
            if list(row.keys()) != columns:
                raise BackendExecutionError("all rows must share one column set")
        for column in columns:
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", column) is None:
                raise BackendExecutionError(f"invalid column name {column!r}")

        def _encode(value: object) -> object:
            if isinstance(value, datetime):
                return value.strftime("%Y-%m-%d %H:%M:%S")
            if isinstance(value, bool):
                return int(value)
            return value

        payload = "\n".join(
            json.dumps({key: _encode(value) for key, value in row.items()}) for row in rows
        )
        statement = (
            f"INSERT INTO {self._database}.{table_name} "  # nosec B608 - identifiers validated above
            f"({', '.join(columns)}) FORMAT JSONEachRow\n{payload}"
        )
        self._request(statement, expect_json=False, translate=False)

    def seed_demo_data(self) -> None:
        # database name comes from trusted backend config
        existing_rows = self.scalar(f"SELECT COUNT(*) AS value FROM {self._database}.orders_v2")  # nosec B608
        if existing_rows is not None and int(existing_rows) > 0:
            return

        now = datetime.now(UTC).replace(microsecond=0)

        def ts(delta: timedelta) -> str:
            return (now - delta).strftime("%Y-%m-%d %H:%M:%S")

        self._request(
            "\n".join(
                [
                    # demo seed data uses trusted config and generated timestamps.
                    # Columns are listed explicitly so `tenant_id` takes its
                    # DEFAULT ('default'): the demo tenant is the same one the
                    # live demo stream writes under (`_event_tenant` falls back
                    # to 'default') and the same one the seeded journal rows
                    # already carry, so seed and stream stay one tenant (P0-1).
                    f"INSERT INTO {self._database}.products_current "  # nosec B608
                    "(product_id, name, category, price, in_stock, stock_quantity) VALUES",
                    "('PROD-001', 'Electric Kettle 1.7L 2200W', 'kettles', 2190.00, 0, 0),",
                    "('PROD-002', 'Air Fryer Grill 5.5L', 'grills', 5490.00, 1, 58),",
                    "('PROD-003', 'Immersion Blender Set 800W', 'blenders', 2490.00, 1, 203),",
                    "('PROD-004', 'Stand Mixer 5L Planetary', 'mixers', 6990.00, 1, 37),",
                    "('PROD-005', 'Drip Coffee Maker 1.2L', 'coffee', 3490.00, 1, 94),",
                    "('PROD-006', 'Waffle Maker Double', 'multibakers', 2290.00, 1, 142),",
                    "('PROD-007', 'Mini Chopper 500ml', 'choppers', 1490.00, 1, 315),",
                    "('PROD-008', 'Cold-Press Juicer', 'juicers', 4490.00, 1, 72),",
                    "('PROD-009', 'Digital Kitchen Scale 5kg', 'scales', 990.00, 1, 421),",
                    "('PROD-010', 'Vacuum Sealer Compact', 'vacuum-dry', 3290.00, 1, 167)",
                ]
            ),
            expect_json=False,
            translate=False,
        )
        self._request(
            "\n".join(
                [
                    # demo seed data uses trusted config and generated timestamps
                    f"INSERT INTO {self._database}.orders_v2 "  # nosec B608
                    "(order_id, user_id, status, total_amount, currency, created_at) VALUES",
                    f"('ORD-20260404-1001', 'USR-10001', 'delivered', 76400.00, 'RUB', '{ts(timedelta(hours=2))}'),",
                    f"('ORD-20260404-1002', 'USR-10002', 'shipped', 48100.00, 'RUB', '{ts(timedelta(minutes=90))}'),",
                    f"('ORD-20260404-1003', 'USR-10003', 'confirmed', 2650.00, 'RUB', '{ts(timedelta(hours=1))}'),",
                    f"('ORD-20260404-1004', 'USR-10003', 'pending', 1890.00, 'RUB', '{ts(timedelta(minutes=45))}'),",
                    f"('ORD-20260404-1005', 'USR-10004', 'delivered', 2290.00, 'RUB', '{ts(timedelta(minutes=30))}'),",
                    f"('ORD-20260404-1006', 'USR-10004', 'cancelled', 1590.00, 'RUB', '{ts(timedelta(minutes=20))}'),",
                    f"('ORD-20260404-1007', 'USR-10005', 'confirmed', 2990.00, 'RUB', '{ts(timedelta(minutes=15))}'),",
                    f"('ORD-20260404-1008', 'USR-10005', 'pending', 3990.00, 'RUB', '{ts(timedelta(minutes=5))}')",
                ]
            ),
            expect_json=False,
            translate=False,
        )
        self._request(
            "\n".join(
                [
                    # demo seed data uses trusted config and generated timestamps
                    f"INSERT INTO {self._database}.users_enriched "  # nosec B608
                    "(user_id, total_orders, total_spent, first_order_at, last_order_at, "
                    "preferred_category) VALUES",
                    f"('USR-10001', 34, 1200000.00, '{ts(timedelta(days=365))}', '{ts(timedelta(hours=2))}', 'grills'),",
                    f"('USR-10002', 15, 460000.00, '{ts(timedelta(days=270))}', '{ts(timedelta(minutes=90))}', 'coffee'),",
                    f"('USR-10003', 4, 8900.00, '{ts(timedelta(days=60))}', '{ts(timedelta(minutes=45))}', 'choppers'),",
                    f"('USR-10004', 6, 15800.00, '{ts(timedelta(days=120))}', '{ts(timedelta(minutes=20))}', 'blenders'),",
                    f"('USR-10005', 3, 28500.00, '{ts(timedelta(days=10))}', '{ts(timedelta(minutes=5))}', 'vacuum-dry')",
                ]
            ),
            expect_json=False,
            translate=False,
        )
        self._request(
            "\n".join(
                [
                    # demo seed data uses trusted config and generated timestamps
                    f"INSERT INTO {self._database}.sessions_aggregated "  # nosec B608
                    "(session_id, user_id, started_at, ended_at, duration_seconds, event_count, "
                    "unique_pages, funnel_stage, is_conversion) VALUES",
                    f"('SES-a1b2c3', 'USR-10005', '{ts(timedelta(hours=2))}', '{ts(timedelta(minutes=100))}', 1200, 14, 6, 'checkout', 1),",
                    f"('SES-d4e5f6', 'USR-10004', '{ts(timedelta(minutes=90))}', '{ts(timedelta(minutes=70))}', 1200, 8, 4, 'add_to_cart', 0),",
                    f"('SES-g7h8i9', NULL, '{ts(timedelta(minutes=60))}', '{ts(timedelta(minutes=58))}', 120, 2, 2, 'bounce', 0),",
                    f"('SES-j1k2l3', 'USR-10003', '{ts(timedelta(minutes=45))}', '{ts(timedelta(minutes=20))}', 1500, 11, 5, 'checkout', 1),",
                    f"('SES-m4n5o6', 'USR-10004', '{ts(timedelta(minutes=30))}', '{ts(timedelta(minutes=15))}', 900, 6, 3, 'product_view', 0),",
                    f"('SES-p7q8r9', 'USR-10005', '{ts(timedelta(minutes=20))}', NULL, NULL, 3, 2, 'browse', 0)",
                ]
            ),
            expect_json=False,
            translate=False,
        )
        self._request(
            "\n".join(
                [
                    # demo seed data uses trusted config and generated timestamps
                    f"INSERT INTO {self._database}.pipeline_events (event_id, topic, tenant_id, entity_id, event_type, latency_ms, processed_at) VALUES",  # nosec B608
                    f"('evt-001', 'events.validated', 'default', NULL, NULL, NULL, '{ts(timedelta(minutes=10))}'),",
                    f"('evt-002', 'events.validated', 'default', NULL, NULL, NULL, '{ts(timedelta(minutes=9))}'),",
                    f"('evt-003', 'events.validated', 'default', NULL, NULL, NULL, '{ts(timedelta(minutes=8))}'),",
                    f"('evt-004', 'events.deadletter', 'default', NULL, NULL, NULL, '{ts(timedelta(minutes=7))}'),",
                    f"('evt-005', 'events.validated', 'default', NULL, NULL, NULL, '{ts(timedelta(minutes=6))}'),",
                    f"('evt-006', 'events.validated', 'default', NULL, NULL, NULL, '{ts(timedelta(minutes=5))}'),",
                    f"('evt-007', 'events.validated', 'default', NULL, NULL, NULL, '{ts(timedelta(minutes=4))}'),",
                    f"('evt-008', 'events.validated', 'default', NULL, NULL, NULL, '{ts(timedelta(minutes=3))}'),",
                    f"('evt-009', 'events.deadletter', 'default', NULL, NULL, NULL, '{ts(timedelta(minutes=2))}'),",
                    f"('evt-010', 'events.validated', 'default', NULL, NULL, NULL, '{ts(timedelta(minutes=1))}'),",
                    # Lineage trail for ORD-20260404-1001, mirroring the DuckDB
                    # seed so /v1/lineage-style reads see the same demo story on
                    # either backend.
                    "('evt-ord-1001-ingest', 'orders.raw', 'default', 'ORD-20260404-1001',"
                    f" 'order.created', 12, '{ts(timedelta(minutes=3))}'),",
                    "('evt-ord-1001-validated', 'events.validated', 'default', 'ORD-20260404-1001',"
                    f" 'order.validated', 8, '{ts(timedelta(minutes=2))}'),",
                    "('evt-ord-1001-served', 'events.served', 'default', 'ORD-20260404-1001',"
                    f" 'order.served', 4, '{ts(timedelta(minutes=1))}')",
                ]
            ),
            expect_json=False,
            translate=False,
        )
        # Stage-entry trails (ops-surfaces-spec.md §1.6), mirroring the DuckDB
        # seed row-for-row so the Order 360 demo story matches on either
        # backend. ORD-20260404-1004's single pending entry at created_at is
        # the demo's sole SLA breach once D3 wires the stages: contract block.
        self._request(
            "\n".join(
                [
                    # demo seed data uses trusted config and generated timestamps
                    f"INSERT INTO {self._database}.pipeline_events (event_id, topic, tenant_id, entity_id, event_type, latency_ms, processed_at) VALUES",  # nosec B608
                    "('evt-ord-1001-status-pending', 'orders.status', 'default', 'ORD-20260404-1001',"
                    f" 'order.status.pending', NULL, '{ts(timedelta(minutes=120))}'),",
                    "('evt-ord-1001-status-confirmed', 'orders.status', 'default', 'ORD-20260404-1001',"
                    f" 'order.status.confirmed', NULL, '{ts(timedelta(minutes=100))}'),",
                    "('evt-ord-1001-status-shipped', 'orders.status', 'default', 'ORD-20260404-1001',"
                    f" 'order.status.shipped', NULL, '{ts(timedelta(minutes=60))}'),",
                    "('evt-ord-1001-status-delivered', 'orders.status', 'default', 'ORD-20260404-1001',"
                    f" 'order.status.delivered', NULL, '{ts(timedelta(minutes=10))}'),",
                    "('evt-ord-1002-status-pending', 'orders.status', 'default', 'ORD-20260404-1002',"
                    f" 'order.status.pending', NULL, '{ts(timedelta(minutes=90))}'),",
                    "('evt-ord-1002-status-confirmed', 'orders.status', 'default', 'ORD-20260404-1002',"
                    f" 'order.status.confirmed', NULL, '{ts(timedelta(minutes=80))}'),",
                    "('evt-ord-1002-status-shipped', 'orders.status', 'default', 'ORD-20260404-1002',"
                    f" 'order.status.shipped', NULL, '{ts(timedelta(minutes=70))}'),",
                    "('evt-ord-1003-status-pending', 'orders.status', 'default', 'ORD-20260404-1003',"
                    f" 'order.status.pending', NULL, '{ts(timedelta(minutes=60))}'),",
                    "('evt-ord-1003-status-confirmed', 'orders.status', 'default', 'ORD-20260404-1003',"
                    f" 'order.status.confirmed', NULL, '{ts(timedelta(minutes=50))}'),",
                    "('evt-ord-1004-status-pending', 'orders.status', 'default', 'ORD-20260404-1004',"
                    f" 'order.status.pending', NULL, '{ts(timedelta(minutes=45))}'),",
                    "('evt-ord-1005-status-pending', 'orders.status', 'default', 'ORD-20260404-1005',"
                    f" 'order.status.pending', NULL, '{ts(timedelta(minutes=30))}'),",
                    "('evt-ord-1005-status-confirmed', 'orders.status', 'default', 'ORD-20260404-1005',"
                    f" 'order.status.confirmed', NULL, '{ts(timedelta(minutes=25))}'),",
                    "('evt-ord-1005-status-shipped', 'orders.status', 'default', 'ORD-20260404-1005',"
                    f" 'order.status.shipped', NULL, '{ts(timedelta(minutes=15))}'),",
                    "('evt-ord-1005-status-delivered', 'orders.status', 'default', 'ORD-20260404-1005',"
                    f" 'order.status.delivered', NULL, '{ts(timedelta(minutes=5))}'),",
                    "('evt-ord-1006-status-pending', 'orders.status', 'default', 'ORD-20260404-1006',"
                    f" 'order.status.pending', NULL, '{ts(timedelta(minutes=20))}'),",
                    "('evt-ord-1006-status-cancelled', 'orders.status', 'default', 'ORD-20260404-1006',"
                    f" 'order.status.cancelled', NULL, '{ts(timedelta(minutes=10))}'),",
                    "('evt-ord-1007-status-pending', 'orders.status', 'default', 'ORD-20260404-1007',"
                    f" 'order.status.pending', NULL, '{ts(timedelta(minutes=15))}'),",
                    "('evt-ord-1007-status-confirmed', 'orders.status', 'default', 'ORD-20260404-1007',"
                    f" 'order.status.confirmed', NULL, '{ts(timedelta(minutes=8))}'),",
                    "('evt-ord-1008-status-pending', 'orders.status', 'default', 'ORD-20260404-1008',"
                    f" 'order.status.pending', NULL, '{ts(timedelta(minutes=5))}')",
                ]
            ),
            expect_json=False,
            translate=False,
        )

    def health(self) -> dict:
        try:
            value = self.scalar("SELECT 1 AS value")
        except BackendExecutionError as exc:
            return {"backend": self.name, "status": "error", "error": str(exc)}
        return {
            "backend": self.name,
            "status": "ok" if value == 1 else "error",
            "host": self._host,
            "port": self._port,
            "database": self._database,
        }
