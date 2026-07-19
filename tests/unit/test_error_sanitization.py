"""Unit coverage for the client-facing error sanitizers (pre-pen-test audit S-2).

The query helpers wrap a ``BackendExecutionError`` (raw ClickHouse/DuckDB text —
engine type, SQL fragments, table/column names) as ``ValueError("... failed:
{backend_error}")`` and the batch path may surface it directly. The router
boundary must return a generic detail for those while keeping plain
request-validation messages verbatim. These pin that split without the HTTP
stack (the sanitizers are pure functions of the exception + request).
"""

from __future__ import annotations

from types import SimpleNamespace

from src.serving.api.routers.agent_query import _client_safe_error
from src.serving.api.routers.batch import _safe_item_error
from src.serving.backends import BackendExecutionError, BackendMissingTableError

_RAW = "Code: 60. DB::Exception: Table agentflow.orders_v2 doesn't exist on clickhouse-0"


def _req(correlation_id: str | None = "corr-123") -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(correlation_id=correlation_id))


def _reraise_from(cause: BackendExecutionError) -> ValueError:
    """A ValueError carrying a BackendExecutionError cause, as the query helpers
    produce with ``raise ValueError(...) from e`` — the cause chain is what the
    sanitizer keys on."""
    err = ValueError(f"Entity lookup failed: {cause}")
    err.__cause__ = cause
    return err


# ── _client_safe_error (entity/metric/NL routes) ─────────────────


def test_backend_wrapped_valueerror_is_genericised() -> None:
    exc = _reraise_from(BackendExecutionError(_RAW))
    http = _client_safe_error(exc, _req(), status_code=503)
    assert http.status_code == 503
    assert http.detail == "backend query failed (ref corr-123)"
    assert "clickhouse" not in http.detail
    assert "orders_v2" not in http.detail


def test_missing_table_subclass_is_also_genericised() -> None:
    # BackendMissingTableError is a BackendExecutionError subclass — same class
    # of raw engine text, must not leak.
    cause = BackendMissingTableError("orders_v2 not materialized on clickhouse-0")
    err = ValueError(f"Entity lookup failed: {cause}")
    err.__cause__ = cause
    http = _client_safe_error(err, _req(), status_code=503)
    assert http.detail == "backend query failed (ref corr-123)"


def test_plain_validation_valueerror_is_verbatim() -> None:
    # A request-level validation error carries no backend cause — keep it, it
    # helps the caller fix the request.
    http = _client_safe_error(ValueError("window must be one of 1h, 24h"), _req(), status_code=400)
    assert http.status_code == 400
    assert http.detail == "window must be one of 1h, 24h"


def test_generic_detail_without_correlation_id_has_no_ref() -> None:
    http = _client_safe_error(
        _reraise_from(BackendExecutionError(_RAW)), _req(None), status_code=503
    )
    assert http.detail == "backend query failed"


# ── _safe_item_error (batch route) ───────────────────────────────


def test_batch_direct_backend_error_is_genericised() -> None:
    msg = _safe_item_error(BackendExecutionError(_RAW), _req())
    assert msg == "backend query failed (ref corr-123)"
    assert "clickhouse" not in msg


def test_batch_wrapped_backend_error_is_genericised() -> None:
    msg = _safe_item_error(_reraise_from(BackendExecutionError(_RAW)), _req())
    assert msg == "backend query failed (ref corr-123)"


def test_batch_plain_validation_error_is_verbatim() -> None:
    # Matches the existing batch contract test: "Unknown metric" must reach the
    # caller so they can correct the item.
    msg = _safe_item_error(ValueError("Unknown metric 'ghost'"), _req())
    assert msg == "Unknown metric 'ghost'"
