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


def test_translate_sql_rewrites_now_filter_count_cast_and_intervals(backend):
    sql = (
        "SELECT NOW(), CAST(x AS FLOAT)::FLOAT, COUNT(*) FILTER (WHERE flag = TRUE) "
        "FROM t WHERE ts > NOW() - INTERVAL '5 minutes' AND alive = TRUE"
    )

    translated = backend._translate_sql(sql)

    assert "now()" in translated
    assert "NOW()" not in translated
    assert "countIf(flag = 1)" in translated
    assert "CAST(x AS Float64)" in translated
    assert "INTERVAL 5 MINUTE" in translated
    # Boolean rewrites
    assert "alive = 1" in translated
    # Stand-alone ::FLOAT remains stripped
    assert "::FLOAT" not in translated.upper().replace("FLOAT64", "")


def test_translate_sql_rewrites_count_star_and_nullif(backend):
    sql = "SELECT COUNT(*) AS n, NULLIF(value, 0) FROM t"

    translated = backend._translate_sql(sql)

    assert "count()" in translated
    assert "nullIf(value, 0)" in translated


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
