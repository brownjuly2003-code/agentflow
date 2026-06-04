"""Unit tests for the ClickHouse serving backend.

Closes the 0% line-coverage gap on `src/serving/backends/clickhouse_backend.py`
flagged in Codex audit p5. We mock `urllib.request.urlopen` so we never need
a real ClickHouse server — the goal is to verify SQL translation, HTTP error
mapping, and the health/missing-table paths.
"""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest

from src.serving.backends import BackendExecutionError, BackendMissingTableError
from src.serving.backends.clickhouse_backend import ClickHouseBackend


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
    """H-C2 / audit_kimi_25_05_26: HTTPS targets must validate the server
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


def test_initialize_demo_data_sends_native_clickhouse_ddl_untranslated(backend):
    """The demo DDL is already ClickHouse SQL (ENGINE = MergeTree, String /
    UInt8 types) — it must bypass the duckdb→clickhouse transpile, which
    would reject it at parse time."""
    sent: list[str] = []

    def fake_urlopen(req, timeout=None):  # noqa: ARG001
        sent.append(req.data.decode("utf-8"))
        # Non-empty count() so the seed INSERTs are skipped after the DDL.
        return _http_response(b'{"data":[{"value":1}]}')

    with patch("src.serving.backends.clickhouse_backend.urlopen", side_effect=fake_urlopen):
        backend.initialize_demo_data()

    create_statements = [sql for sql in sent if "CREATE TABLE" in sql]
    assert create_statements, "demo init must issue CREATE TABLE statements"
    for sql in create_statements:
        assert "ENGINE = MergeTree()" in sql, "native DDL must reach ClickHouse untouched"


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
