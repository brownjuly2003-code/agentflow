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

# ClickHouse expresses filtered aggregation through -If combinators, not the
# standard `<agg> FILTER (WHERE ...)` clause.
_FILTERED_AGG_COMBINATORS: dict[type[exp.Expr], str] = {
    exp.Count: "countIf",
    exp.Sum: "sumIf",
    exp.Avg: "avgIf",
    exp.Min: "minIf",
    exp.Max: "maxIf",
}


def _rewrite_for_clickhouse(node: exp.Expr) -> exp.Expr:
    """AST rewrites the stock duckdb→clickhouse transpile does not cover.

    - ClickHouse has no `<agg> FILTER (WHERE ...)` clause; rewrite the
      aggregates the semantic layer uses to native -If combinators
      (`COUNT(*) FILTER (WHERE c)` → `countIf(c)`). Unknown aggregates are
      left untouched so ClickHouse rejects them loudly server-side.
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

        Tenant isolation is enforced upstream by ``_scope_sql`` as a *schema
        qualification* on the table name (``"tenant_schema"."table"``), and this
        backend rewrites the SQL *after* that guard ran. The rewrite must
        therefore never add, drop, or rename a table reference — otherwise a
        transpiler regression could silently unqualify a tenant-scoped table and
        read another tenant's rows (the same rewrite-after-guard seam that
        produced the historical PII bypasses). Parse the *generated string* back
        rather than trusting the rewritten AST, so generation-level quoting bugs
        are caught too.
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
        """
        self._request(
            f"CREATE DATABASE IF NOT EXISTS {self._database}",
            expect_json=False,
            translate=False,
            use_database=False,
        )
        self._request(
            f"""
            CREATE TABLE IF NOT EXISTS {self._database}.orders_v2 (
                order_id String,
                user_id String,
                status String,
                total_amount Decimal(10, 2),
                currency String,
                created_at DateTime,
                af_updated_at DateTime64(3) MATERIALIZED now64(3)
            ) ENGINE = ReplacingMergeTree(af_updated_at)
            ORDER BY order_id
        """,
            expect_json=False,
            translate=False,
        )
        self._request(
            f"""
            CREATE TABLE IF NOT EXISTS {self._database}.products_current (
                product_id String,
                name String,
                category String,
                price Decimal(10, 2),
                in_stock UInt8,
                stock_quantity Int32,
                af_updated_at DateTime64(3) MATERIALIZED now64(3)
            ) ENGINE = ReplacingMergeTree(af_updated_at)
            ORDER BY product_id
        """,
            expect_json=False,
            translate=False,
        )
        self._request(
            f"""
            CREATE TABLE IF NOT EXISTS {self._database}.sessions_aggregated (
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
            ORDER BY session_id
        """,
            expect_json=False,
            translate=False,
        )
        self._request(
            f"""
            CREATE TABLE IF NOT EXISTS {self._database}.users_enriched (
                user_id String,
                total_orders Int32,
                total_spent Decimal(10, 2),
                first_order_at DateTime,
                last_order_at DateTime,
                preferred_category Nullable(String),
                af_updated_at DateTime64(3) MATERIALIZED now64(3)
            ) ENGINE = ReplacingMergeTree(af_updated_at)
            ORDER BY user_id
        """,
            expect_json=False,
            translate=False,
        )
        self._request(
            f"""
            CREATE TABLE IF NOT EXISTS {self._database}.pipeline_events (
                event_id String,
                topic String,
                tenant_id String DEFAULT 'default',
                entity_id Nullable(String),
                event_type Nullable(String),
                latency_ms Nullable(Int32),
                processed_at DateTime
            ) ENGINE = MergeTree()
            ORDER BY (tenant_id, topic, processed_at, event_id)
        """,
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

    def initialize_demo_data(self) -> None:
        self.ensure_schema()

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
                    # demo seed data uses trusted config and generated timestamps
                    f"INSERT INTO {self._database}.products_current VALUES",  # nosec B608
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
                    f"INSERT INTO {self._database}.orders_v2 VALUES",  # nosec B608
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
                    f"INSERT INTO {self._database}.users_enriched VALUES",  # nosec B608
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
                    f"INSERT INTO {self._database}.sessions_aggregated VALUES",  # nosec B608
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
