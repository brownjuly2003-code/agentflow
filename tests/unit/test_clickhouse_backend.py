"""Unit tests for the ClickHouse serving backend.

Closes the 0% line-coverage gap on `src/serving/backends/clickhouse_backend.py`
flagged in audit p5. We mock `urllib.request.urlopen` so we never need
a real ClickHouse server — the goal is to verify SQL translation, HTTP error
mapping, and the health/missing-table paths.
"""

from __future__ import annotations

import json
from datetime import datetime
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest
import sqlglot
from sqlglot import exp

from src.serving.backends import BackendExecutionError, BackendMissingTableError
from src.serving.backends.clickhouse_backend import ClickHouseBackend

# Injection payloads shared with the DuckDB-path coverage in
# tests/unit/test_query_engine_injection.py. Includes the backslash vectors
# ClickHouse treats as escapes (but DuckDB does not), which is the specific
# risk of the inline-literal ClickHouse path (A-3).
CLICKHOUSE_ATTACK_VECTORS = [
    "'; DROP TABLE orders_v2; --",
    "' OR '1'='1",
    "'; DELETE FROM users WHERE '1'='1",
    "\\'; DROP TABLE orders_v2; --",
    "ORD' UNION SELECT * FROM api_keys --",
    "'); ATTACH 'evil.db' AS evil; --",
    "ORD\x00'; DROP TABLE --",
    "ORD' AND (SELECT COUNT(*) FROM api_keys) > 0 --",
    "\\",
    "x\\' OR 1=1 --",
]


@pytest.fixture
def backend() -> ClickHouseBackend:
    return ClickHouseBackend(
        host="ch.example",
        port=8123,
        user="agentflow",
        password="agentflow",
        database="agentflow",
    )


def _http_response(payload: bytes):
    """Tiny shim that quacks like the urlopen context manager."""

    class _Resp:
        def __enter__(self_inner):
            return self_inner

        def __exit__(self_inner, *_):
            return False

        def read(self_inner) -> bytes:
            return payload

    return _Resp()


def test_translate_sql_transpiles_filter_clause_to_countif(backend):
    # ClickHouse has no `<agg> FILTER (WHERE ...)` clause — the transpile
    # must rewrite it to the native -If combinator (error_rate template).
    sql = (
        "SELECT CAST(COUNT(*) FILTER (WHERE topic = 'events.deadletter') AS FLOAT) "
        "/ NULLIF(COUNT(*), 0) as value "
        "FROM pipeline_events WHERE processed_at >= NOW() - INTERVAL '24 hours'"
    )

    translated = backend._translate_sql(sql)

    assert "countIf(topic = 'events.deadletter')" in translated
    assert "FILTER" not in translated
    assert "nullIf(COUNT(*), 0)" in translated
    assert "INTERVAL" in translated


def test_translate_sql_transpiles_sum_and_avg_filter_to_if_combinators(backend):
    translated = backend._translate_sql(
        "SELECT SUM(amount) FILTER (WHERE ok), AVG(amount) FILTER (WHERE ok) FROM t"
    )

    assert "sumIf(amount, ok)" in translated
    assert "avgIf(amount, ok)" in translated
    assert "FILTER" not in translated


def test_translate_sql_widens_duckdb_float_to_float64(backend):
    # DuckDB FLOAT is a 4-byte float and would transpile to Float32; the
    # backend keeps its historical Float64 semantics for ratio metrics.
    translated = backend._translate_sql("SELECT CAST(x AS FLOAT) FROM t")

    assert "Float64" in translated
    assert "Float32" not in translated


def test_translate_sql_rejects_unparseable_sql(backend):
    with pytest.raises(BackendExecutionError) as info:
        backend._translate_sql("SELECT FROM WHERE")

    assert "translation failed" in str(info.value)


def test_translate_sql_rejects_multi_statement_sql(backend):
    with pytest.raises(BackendExecutionError) as info:
        backend._translate_sql("SELECT 1; SELECT 2")

    assert "one SQL statement" in str(info.value)


def test_translate_sql_keeps_nullif_and_case_when(backend):
    sql = (
        "SELECT CAST(SUM(CASE WHEN is_conversion THEN 1 ELSE 0 END) AS FLOAT) "
        "/ NULLIF(COUNT(*), 0) as value FROM sessions_aggregated"
    )

    translated = backend._translate_sql(sql)

    assert "nullIf(COUNT(*), 0)" in translated
    assert "CASE WHEN is_conversion THEN 1 ELSE 0 END" in translated
    assert "Float64" in translated


def test_request_sends_post_with_basic_auth_and_database(backend):
    captured: dict = {}

    def fake_urlopen(req, timeout=None):  # noqa: ARG001
        captured["url"] = req.full_url
        captured["data"] = req.data
        captured["method"] = req.get_method()
        captured["auth"] = req.get_header("Authorization")
        return _http_response(b'{"data":[{"value":1}]}')

    with patch("src.serving.backends.clickhouse_backend.urlopen", side_effect=fake_urlopen):
        rows = backend.execute("SELECT 1 AS value")

    assert rows == [{"value": 1}]
    assert captured["method"] == "POST"
    assert captured["auth"].startswith("Basic ")
    assert "database=agentflow" in captured["url"]
    assert "default_format=JSON" in captured["url"]
    assert captured["data"] == b"SELECT 1 AS value"


def test_unknown_table_http_error_maps_to_missing_table_exception(backend):
    body = b"Code: 60. DB::Exception: Table agentflow.missing doesn't exist"
    err = HTTPError(
        url="http://ch.example:8123/",
        code=404,
        msg="Not Found",
        hdrs=None,
        fp=BytesIO(body),
    )

    with patch("src.serving.backends.clickhouse_backend.urlopen", side_effect=err):
        with pytest.raises(BackendMissingTableError):
            backend.execute("SELECT * FROM agentflow.missing")


def test_other_http_error_maps_to_execution_error(backend):
    body = b"Code: 47. DB::Exception: Unknown identifier"
    err = HTTPError(
        url="http://ch.example:8123/",
        code=400,
        msg="Bad Request",
        hdrs=None,
        fp=BytesIO(body),
    )

    with patch("src.serving.backends.clickhouse_backend.urlopen", side_effect=err):
        with pytest.raises(BackendExecutionError) as info:
            backend.execute("SELECT bogus")

    assert "Unknown identifier" in str(info.value)


def test_url_error_maps_to_execution_error(backend):
    with patch(
        "src.serving.backends.clickhouse_backend.urlopen",
        side_effect=URLError("connection refused"),
    ):
        with pytest.raises(BackendExecutionError) as info:
            backend.execute("SELECT 1")

    assert "connection refused" in str(info.value)


def test_table_columns_returns_empty_on_missing_table(backend):
    body = b"Code: 60. DB::Exception: Table agentflow.absent doesn't exist"
    err = HTTPError(
        url="http://ch.example:8123/",
        code=404,
        msg="Not Found",
        hdrs=None,
        fp=BytesIO(body),
    )

    with patch("src.serving.backends.clickhouse_backend.urlopen", side_effect=err):
        cols = backend.table_columns("absent")

    assert cols == set()


def test_table_columns_returns_empty_on_unknown_database(backend):
    body = b"Code: 81. DB::Exception: UNKNOWN_DATABASE"
    err = HTTPError(
        url="http://ch.example:8123/",
        code=400,
        msg="Bad Request",
        hdrs=None,
        fp=BytesIO(body),
    )

    with patch("src.serving.backends.clickhouse_backend.urlopen", side_effect=err):
        cols = backend.table_columns("anything")

    assert cols == set()


def test_table_columns_parses_describe_output(backend):
    payload = json.dumps(
        {"data": [{"name": "order_id", "type": "String"}, {"name": "total", "type": "Float64"}]}
    ).encode()

    with patch(
        "src.serving.backends.clickhouse_backend.urlopen",
        return_value=_http_response(payload),
    ):
        cols = backend.table_columns("orders_v2")

    assert cols == {"order_id", "total"}


def test_explain_returns_one_tuple_per_plan_line(backend):
    payload = b"Expression\n  ReadFromMergeTree\n"

    with patch(
        "src.serving.backends.clickhouse_backend.urlopen",
        return_value=_http_response(payload),
    ):
        plan = backend.explain("SELECT 1")

    assert plan == [("Expression",), ("  ReadFromMergeTree",)]


def test_health_reports_ok_on_select_one(backend):
    payload = b'{"data":[{"value":1}]}'

    with patch(
        "src.serving.backends.clickhouse_backend.urlopen",
        return_value=_http_response(payload),
    ):
        report = backend.health()

    assert report["status"] == "ok"
    assert report["backend"] == "clickhouse"
    assert report["host"] == "ch.example"
    assert report["database"] == "agentflow"


def test_health_reports_error_on_url_error(backend):
    with patch(
        "src.serving.backends.clickhouse_backend.urlopen",
        side_effect=URLError("transport down"),
    ):
        report = backend.health()

    assert report["status"] == "error"
    assert "transport down" in report["error"]


def test_secure_flag_switches_scheme_to_https():
    secure_backend = ClickHouseBackend(
        host="ch.secure",
        port=8443,
        user="u",
        password="p",
        database="db",
        secure=True,
    )

    assert secure_backend._base_url == "https://ch.secure:8443"


def test_secure_backend_builds_ssl_context_with_trust_store():
    """H-C2 / audit-2026-05: HTTPS targets must validate the server
    cert against the system trust store explicitly, not rely on urllib's
    default-no-context behaviour."""
    secure_backend = ClickHouseBackend(
        host="ch.secure",
        port=8443,
        user="u",
        password="p",
        database="db",
        secure=True,
    )
    assert secure_backend._ssl_context is not None
    # `create_default_context()` enables hostname verification + CERT_REQUIRED.
    import ssl

    assert secure_backend._ssl_context.verify_mode == ssl.CERT_REQUIRED
    assert secure_backend._ssl_context.check_hostname is True


def test_insecure_backend_omits_ssl_context(backend):
    """Plain-HTTP backends must not attach an SSL context (mock-friendly,
    matches the test signature used by the rest of this module)."""
    assert backend._ssl_context is None


class TestTranslateSqlLiteralProtection:
    """H-C2: dialect rewrites must not corrupt user data embedded in `'...'`
    string literals. The sqlglot transpile guarantees this structurally (the
    parser knows what a literal is), unlike the regex chain it replaced —
    these tests pin that property against regressions back to text rewrites."""

    def test_float_token_inside_literal_is_preserved(self, backend):
        sql = "SELECT 'price tag ::FLOAT cents' FROM t"
        translated = backend._translate_sql(sql)
        assert "'price tag ::FLOAT cents'" in translated

    def test_now_token_inside_literal_is_preserved(self, backend):
        sql = "SELECT 'event=NOW() captured' AS note FROM t"
        translated = backend._translate_sql(sql)
        assert "'event=NOW() captured'" in translated

    def test_count_star_inside_literal_is_preserved(self, backend):
        sql = "SELECT 'metric=COUNT(*) total' AS lbl FROM t"
        translated = backend._translate_sql(sql)
        assert "'metric=COUNT(*) total'" in translated

    def test_true_false_inside_literal_is_preserved(self, backend):
        sql = "SELECT 'flag is TRUE always' AS note FROM t WHERE alive = TRUE"
        translated = backend._translate_sql(sql)
        assert "'flag is TRUE always'" in translated

    def test_cast_inside_literal_is_preserved(self, backend):
        sql = "SELECT 'doc: CAST(x AS FLOAT)' AS note FROM t"
        translated = backend._translate_sql(sql)
        assert "'doc: CAST(x AS FLOAT)'" in translated

    def test_escaped_quote_in_literal_is_preserved(self, backend):
        sql = "SELECT 'it''s ::FLOAT' AS note FROM t"
        translated = backend._translate_sql(sql)
        assert "'it''s ::FLOAT'" in translated

    def test_filter_token_inside_literal_is_preserved(self, backend):
        # A literal containing the word FILTER must survive even though the
        # FILTER-clause rewrite runs on the same statement.
        sql = "SELECT 'mode=FILTER (WHERE x)' AS lbl, COUNT(*) FILTER (WHERE ok) AS n FROM t"
        translated = backend._translate_sql(sql)
        assert "'mode=FILTER (WHERE x)'" in translated
        assert "countIf(ok)" in translated


class TestTranslateSqlInjectionSafety:
    """A-3 (audit_codex_03_06_26): the ClickHouse path inlines values via
    `_quote_literal` instead of binding `?` params. Prove a malicious value
    cannot break out of its string literal once `_translate_sql` re-escapes it
    for ClickHouse — `TestTranslateSqlLiteralProtection` above pins data
    *fidelity* (legit tokens survive); this pins *security* (attacks stay
    inert), and specifically covers the backslash vectors ClickHouse honours
    as escapes but DuckDB does not."""

    @pytest.mark.parametrize("payload", CLICKHOUSE_ATTACK_VECTORS)
    def test_quoted_value_cannot_escape_its_literal(self, backend, payload):
        # Mirror the semantic layer's ClickHouse branch: a single-quoted
        # literal (`'` doubled to `''`) inlined into the WHERE clause.
        quoted = "'" + str(payload).replace("'", "''") + "'"
        sql = f'SELECT * FROM "orders_v2" WHERE "order_id" = {quoted} LIMIT 1'

        translated = backend._translate_sql(sql)

        # Re-parse the emitted ClickHouse SQL: the payload must remain inert
        # data, i.e. exactly one plain SELECT whose WHERE is a single equality,
        # with none of the structures an injection would introduce.
        statements = [s for s in sqlglot.parse(translated, dialect="clickhouse") if s is not None]
        assert len(statements) == 1, f"payload split the statement: {translated!r}"
        stmt = statements[0]
        assert isinstance(stmt, exp.Select), f"not a plain SELECT: {translated!r}"
        injected = list(
            stmt.find_all(exp.Or, exp.Union, exp.Drop, exp.Delete, exp.Insert, exp.Alter)
        )
        assert not injected, (
            f"injection leaked {[type(n).__name__ for n in injected]}: {translated!r}"
        )
        where = stmt.find(exp.Where)
        assert where is not None, f"WHERE clause vanished: {translated!r}"
        assert isinstance(where.this, exp.EQ), f"WHERE is not a simple equality: {translated!r}"


def test_initialize_demo_data_sends_native_clickhouse_ddl_untranslated(backend):
    """The demo DDL is already ClickHouse SQL (ENGINE clauses, String / UInt8
    types) — it must bypass the duckdb→clickhouse transpile, which would
    reject it at parse time. The mutable serving tables are ReplacingMergeTree
    versioned by the MATERIALIZED ``af_updated_at`` column (upsert = append a
    new version; reads run with final=1); the append-only ``pipeline_events``
    journal stays plain MergeTree."""
    sent: list[str] = []

    def fake_urlopen(req, timeout=None):  # noqa: ARG001
        sent.append(req.data.decode("utf-8"))
        # Non-empty count() so the seed INSERTs are skipped after the DDL.
        return _http_response(b'{"data":[{"value":1}]}')

    with patch("src.serving.backends.clickhouse_backend.urlopen", side_effect=fake_urlopen):
        backend.initialize_demo_data()

    create_statements = [sql for sql in sent if "CREATE TABLE" in sql]
    assert create_statements, "demo init must issue CREATE TABLE statements"
    replacing = [sql for sql in create_statements if "ReplacingMergeTree(af_updated_at)" in sql]
    plain = [sql for sql in create_statements if "ENGINE = MergeTree()" in sql]
    assert len(replacing) == 4, "orders/products/sessions/users must be ReplacingMergeTree"
    assert len(plain) == 1, "the journal must stay append-only MergeTree"
    assert "pipeline_events" in plain[0]
    for sql in replacing:
        assert "af_updated_at DateTime64(3) MATERIALIZED now64(3)" in sql, (
            "version column must be MATERIALIZED so it stays out of SELECT * and inserts"
        )


def test_table_columns_sends_describe_untranslated(backend):
    captured: dict = {}

    def fake_urlopen(req, timeout=None):  # noqa: ARG001
        captured["data"] = req.data
        return _http_response(b'{"data":[{"name":"order_id","type":"String"}]}')

    with patch("src.serving.backends.clickhouse_backend.urlopen", side_effect=fake_urlopen):
        cols = backend.table_columns("orders_v2")

    assert cols == {"order_id"}
    assert captured["data"] == b"DESCRIBE TABLE orders_v2"


def test_explain_translates_inner_sql_before_wrapping(backend):
    """EXPLAIN itself is a ClickHouse wrapper, but the wrapped query comes
    from the DuckDB-flavored semantic layer and must be transpiled."""
    captured: dict = {}

    def fake_urlopen(req, timeout=None):  # noqa: ARG001
        captured["data"] = req.data.decode("utf-8")
        return _http_response(b"Expression\n")

    with patch("src.serving.backends.clickhouse_backend.urlopen", side_effect=fake_urlopen):
        backend.explain("SELECT COUNT(*) FILTER (WHERE ok) AS n FROM t")

    assert captured["data"].startswith("EXPLAIN ")
    assert "countIf(ok)" in captured["data"]
    assert "FILTER" not in captured["data"]


def test_scalar_returns_first_value_or_none(backend):
    payload = b'{"data":[{"only":42}]}'
    with patch(
        "src.serving.backends.clickhouse_backend.urlopen",
        return_value=_http_response(payload),
    ):
        assert backend.scalar("SELECT 42 AS only") == 42

    empty = b'{"data":[]}'
    with patch(
        "src.serving.backends.clickhouse_backend.urlopen",
        return_value=_http_response(empty),
    ):
        assert backend.scalar("SELECT 1 WHERE FALSE") is None


# ── ReplacingMergeTree read/write model ──────────────────────────


def test_execute_reads_with_final_setting(backend):
    """Every read must carry final=1 so ReplacingMergeTree versions collapse
    at query time — without it a freshly upserted row would read as a
    duplicate until a background merge happens to run."""
    captured: dict = {}

    def fake_urlopen(req, timeout=None):  # noqa: ARG001
        captured["url"] = req.full_url
        return _http_response(b'{"data":[]}')

    with patch("src.serving.backends.clickhouse_backend.urlopen", side_effect=fake_urlopen):
        backend.execute("SELECT COUNT(*) AS value FROM orders_v2")

    assert "final=1" in captured["url"]


def test_ddl_and_inserts_do_not_carry_final(backend):
    urls: list[str] = []

    def fake_urlopen(req, timeout=None):  # noqa: ARG001
        urls.append(req.full_url)
        return _http_response(b'{"data":[{"value":1}]}')

    with patch("src.serving.backends.clickhouse_backend.urlopen", side_effect=fake_urlopen):
        backend.ensure_schema()
        backend.insert_rows("pipeline_events", [{"event_id": "e1", "topic": "t"}])

    write_urls = [url for url in urls if "final=1" in url]
    assert write_urls == [], "final is a read-time setting; writes must not carry it"


def test_table_columns_hides_materialized_version_column(backend):
    """`af_updated_at` is MATERIALIZED — excluded from SELECT * and inserts —
    so exposing it via table_columns would fork the logical schema from the
    DuckDB store and the entity contracts."""
    payload = (
        b'{"data":[{"name":"order_id","default_type":""},'
        b'{"name":"status","default_type":""},'
        b'{"name":"af_updated_at","default_type":"MATERIALIZED"},'
        b'{"name":"alias_col","default_type":"ALIAS"}]}'
    )
    with patch(
        "src.serving.backends.clickhouse_backend.urlopen",
        return_value=_http_response(payload),
    ):
        assert backend.table_columns("orders_v2") == {"order_id", "status"}


# ── insert_rows (JSONEachRow) ────────────────────────────────────


def test_insert_rows_formats_jsoneachrow(backend):
    captured: dict = {}

    def fake_urlopen(req, timeout=None):  # noqa: ARG001
        captured["data"] = req.data.decode("utf-8")
        return _http_response(b"")

    row = {
        "order_id": "ORD-1",
        "total_amount": 12.5,
        "in_stock": True,
        "created_at": datetime(2026, 7, 2, 10, 30, 0),
        "entity_id": None,
    }
    with patch("src.serving.backends.clickhouse_backend.urlopen", side_effect=fake_urlopen):
        backend.insert_rows("orders_v2", [row])

    header, payload = captured["data"].split("\n", 1)
    assert header == (
        "INSERT INTO agentflow.orders_v2 "
        "(order_id, total_amount, in_stock, created_at, entity_id) FORMAT JSONEachRow"
    )
    decoded = json.loads(payload)
    assert decoded == {
        "order_id": "ORD-1",
        "total_amount": 12.5,
        "in_stock": 1,
        "created_at": "2026-07-02 10:30:00",
        "entity_id": None,
    }


def test_insert_rows_rejects_hostile_identifiers(backend):
    with patch(
        "src.serving.backends.clickhouse_backend.urlopen",
        return_value=_http_response(b""),
    ):
        with pytest.raises(BackendExecutionError, match="invalid table name"):
            backend.insert_rows("orders_v2; DROP TABLE x", [{"a": 1}])
        with pytest.raises(BackendExecutionError, match="invalid column name"):
            backend.insert_rows("orders_v2", [{"a) VALUES (1); --": 1}])
        with pytest.raises(BackendExecutionError, match="one column set"):
            backend.insert_rows("orders_v2", [{"a": 1}, {"b": 2}])


def test_insert_rows_noop_on_empty(backend):
    with patch("src.serving.backends.clickhouse_backend.urlopen") as mocked:
        backend.insert_rows("orders_v2", [])
    mocked.assert_not_called()


# ── scope preservation across the transpile (rewrite-after-guard seam) ──


def test_translate_preserves_tenant_schema_qualification(backend):
    """Tenant isolation is a schema qualification applied *before* this
    backend rewrites the SQL; the transpile must carry it through."""
    translated = backend._translate_sql(
        'SELECT COUNT(*) AS n FROM "acme_corp"."orders_v2" WHERE status = \'paid\''
    )
    assert "acme_corp" in translated
    assert "orders_v2" in translated


def test_assert_scope_preserved_fails_closed_on_dropped_qualifier(backend):
    """Counterfactual for the guard itself: a translation that loses the
    tenant schema (or swaps the table) must refuse to execute."""
    source = sqlglot.parse_one('SELECT * FROM "acme_corp"."orders_v2"', read="duckdb")
    with pytest.raises(BackendExecutionError, match="table references"):
        backend._assert_scope_preserved(source, "SELECT * FROM orders_v2")
    with pytest.raises(BackendExecutionError, match="table references"):
        backend._assert_scope_preserved(source, 'SELECT * FROM "acme_corp"."users_enriched"')
    # And the well-behaved translation passes.
    backend._assert_scope_preserved(source, 'SELECT * FROM "acme_corp"."orders_v2"')


@pytest.mark.parametrize(
    "sql",
    [
        'SELECT * FROM "acme"."orders_v2" o JOIN "acme"."users_enriched" u ON o.user_id = u.user_id',
        'WITH t AS (SELECT * FROM "acme"."orders_v2") SELECT * FROM t',
        'SELECT * FROM (SELECT order_id FROM "acme"."orders_v2") s',
        'SELECT * FROM "acme"."orders_v2" WHERE order_id IN (SELECT order_id FROM "acme"."orders_v2")',
    ],
)
def test_translate_preserves_tenant_refs_through_joins_ctes_subqueries(backend, sql: str):
    """S12: rewrite-after-guard must keep schema quals on complex shapes."""
    translated = backend._translate_sql(sql)
    assert '"acme"' in translated or "acme" in translated
    # No unscoped physical orders/users tables appear without the tenant qual.
    # (CTE alias `t` / subquery alias `s` are not physical tables.)
    reparsed = sqlglot.parse_one(translated, read="clickhouse")
    physical = [
        ((t.db or "").lower(), (t.name or "").lower())
        for t in reparsed.find_all(sqlglot.exp.Table)
        if t.name and t.name.lower() not in {"t", "s"}
    ]
    for db, name in physical:
        if name in {"orders_v2", "users_enriched"}:
            assert db == "acme", f"lost tenant qual on {name}: {translated}"


def test_create_database_bootstrap_does_not_set_session_database(backend):
    """Found live (2026-07-02, bare single-binary server): sending
    `?database=agentflow` on the CREATE DATABASE bootstrap statement fails with
    UNKNOWN_DATABASE before the database can be created. Docker images mask
    this by pre-creating the database via CLICKHOUSE_DB."""
    urls: list[str] = []

    def fake_urlopen(req, timeout=None):  # noqa: ARG001
        urls.append(req.full_url)
        return _http_response(b'{"data":[{"value":1}]}')

    with patch("src.serving.backends.clickhouse_backend.urlopen", side_effect=fake_urlopen):
        backend.ensure_schema()

    assert "database=agentflow" not in urls[0], "bootstrap must not set the session database"
    assert all("database=agentflow" in url for url in urls[1:]), (
        "every post-bootstrap statement runs against the serving database"
    )
