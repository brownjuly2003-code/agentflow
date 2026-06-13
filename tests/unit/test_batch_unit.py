"""Unit coverage for ``src.serving.api.routers.batch`` — the per-item batch
executors and the concurrent ``batch_query`` handler.

The full HTTP path (auth middleware, a real ``QueryEngine``, the PII config) is
covered by ``tests/integration/test_batch.py``. These tests pin batch.py's own
orchestration logic at the unit layer with in-process fakes (no Docker, no
running app): param validation, entity/metric/query routing, the engine
kwarg-compatibility fallback, per-item error isolation, and wall-time
reporting — so a regression in batch routing fails fast.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.serving.api.routers import batch as batch_module
from src.serving.api.routers.batch import (
    BatchItem,
    BatchRequest,
    BatchResult,
    _execute_entity_item,
    _execute_item,
    _execute_metric_item,
    _execute_query_item,
    _run_engine_call,
    batch_query,
)

# ── Fakes ────────────────────────────────────────────────────────


class _FakeCursor:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakeConn:
    """Stands in for a DuckDB connection; ``_run_engine_call`` only calls
    ``.cursor()`` on it and ``.close()`` on the returned cursor."""

    def __init__(self) -> None:
        self.cursors: list[_FakeCursor] = []

    def cursor(self) -> _FakeCursor:
        cursor = _FakeCursor()
        self.cursors.append(cursor)
        return cursor


class _ModernEngine:
    """Engine fake that accepts the modern ``tenant_id`` / ``allowed_tables``
    kwargs (the production engine contract)."""

    def __init__(
        self,
        *,
        entity: dict[str, Any] | None = None,
        metric: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> None:
        self._conn = _FakeConn()
        self._entity = entity
        self._metric = metric or {"value": 0, "unit": "USD"}
        self._query = query or {"data": [], "sql": "SELECT 1", "row_count": 0}
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def get_entity(
        self, entity_type: str, entity_id: str, tenant_id: str | None = None
    ) -> dict[str, Any] | None:
        self.calls.append(("get_entity", (entity_type, entity_id), {"tenant_id": tenant_id}))
        return self._entity

    def get_metric(
        self, metric_name: str, window: str = "1h", tenant_id: str | None = None
    ) -> dict[str, Any]:
        self.calls.append(("get_metric", (metric_name, window), {"tenant_id": tenant_id}))
        return self._metric

    def execute_nl_query(
        self,
        question: str,
        context: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        allowed_tables: Any = None,
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "execute_nl_query",
                (question,),
                {"tenant_id": tenant_id, "allowed_tables": allowed_tables},
            )
        )
        return self._query


class _LegacyEngine:
    """Engine fake predating the ``tenant_id`` / ``allowed_tables`` kwargs — it
    raises ``TypeError`` when called with them, exercising the kwarg fallback."""

    def __init__(
        self,
        *,
        entity: dict[str, Any] | None = None,
        metric: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> None:
        self._conn = _FakeConn()
        self._entity = entity
        self._metric = metric or {"value": 0, "unit": "USD"}
        self._query = query or {"data": [], "sql": "SELECT 1", "row_count": 0}
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def get_entity(self, entity_type: str, entity_id: str) -> dict[str, Any] | None:
        self.calls.append(("get_entity", (entity_type, entity_id)))
        return self._entity

    def get_metric(self, metric_name: str, window: str = "1h") -> dict[str, Any]:
        self.calls.append(("get_metric", (metric_name, window)))
        return self._metric

    def execute_nl_query(
        self, question: str, context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.calls.append(("execute_nl_query", (question,)))
        return self._query


class _IdentityMasker:
    """No-op PII masker so the executors' masking calls are exercised without
    coupling the unit test to the live ``config/pii_fields.yaml``."""

    def mask(self, entity_type: str, payload: dict[str, Any], tenant: str) -> dict[str, Any]:
        return payload

    def mask_query_results(
        self, sql: str, data: Any, tenant: str, table_to_entity: dict[str, str]
    ) -> tuple[Any, bool]:
        return data, False


def _make_req(
    engine: Any,
    *,
    entities: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    tenant_key: Any = None,
    tenant_id: str | None = None,
    auth_manager: Any = None,
) -> SimpleNamespace:
    catalog = SimpleNamespace(
        entities=entities if entities is not None else {"order": SimpleNamespace(table="orders")},
        metrics=metrics if metrics is not None else {"revenue": SimpleNamespace(table="orders")},
    )
    app = SimpleNamespace(
        state=SimpleNamespace(catalog=catalog, query_engine=engine, auth_manager=auth_manager)
    )
    return SimpleNamespace(
        app=app, state=SimpleNamespace(tenant_key=tenant_key, tenant_id=tenant_id)
    )


@pytest.fixture(autouse=True)
def _identity_masker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(batch_module, "_get_pii_masker", lambda: _IdentityMasker())
    # _execute_query_item delegates table-allowlist resolution to agent_query;
    # pin it here so the unit test exercises only batch.py's orchestration.
    monkeypatch.setattr(
        batch_module, "_allowed_tables_for_request", lambda req: ["orders", "pipeline_events"]
    )


# ── _run_engine_call ─────────────────────────────────────────────


def test_run_engine_call_uses_isolated_cursor_and_closes_it() -> None:
    engine = _ModernEngine(metric={"value": 5, "unit": "USD"})
    result = _run_engine_call(engine, "get_metric", "revenue", "1h", tenant_id="acme")

    assert result == {"value": 5, "unit": "USD"}
    # A worker cursor was opened off the shared connection and then closed.
    assert len(engine._conn.cursors) == 1
    assert engine._conn.cursors[0].closed is True
    assert engine.calls == [("get_metric", ("revenue", "1h"), {"tenant_id": "acme"})]


def test_run_engine_call_closes_cursor_even_when_method_raises() -> None:
    class _Boom(_ModernEngine):
        def get_metric(self, metric_name: str, window: str = "1h", tenant_id: str | None = None):
            raise ValueError("boom")

    engine = _Boom()
    with pytest.raises(ValueError, match="boom"):
        _run_engine_call(engine, "get_metric", "revenue")
    assert engine._conn.cursors[0].closed is True


# ── _execute_entity_item ─────────────────────────────────────────


async def test_execute_entity_item_success_strips_last_updated() -> None:
    engine = _ModernEngine(entity={"order_id": "ORD-1", "_last_updated": "2026-06-13"})
    req = _make_req(engine, tenant_id="acme")
    item = BatchItem(id="e1", type="entity", params={"entity_type": "order", "entity_id": "ORD-1"})

    data = await _execute_entity_item(item, req)

    assert data == {"order_id": "ORD-1"}
    assert "_last_updated" not in data


async def test_execute_entity_item_non_string_params_raise_valueerror() -> None:
    req = _make_req(_ModernEngine())
    item = BatchItem(id="e1", type="entity", params={"entity_type": "order", "entity_id": 123})
    with pytest.raises(ValueError, match="requires string params"):
        await _execute_entity_item(item, req)


async def test_execute_entity_item_unknown_type_raises_valueerror() -> None:
    req = _make_req(_ModernEngine())
    item = BatchItem(id="e1", type="entity", params={"entity_type": "ghost", "entity_id": "X"})
    with pytest.raises(ValueError, match="Unknown entity type"):
        await _execute_entity_item(item, req)


async def test_execute_entity_item_missing_entity_raises_lookup_error() -> None:
    engine = _ModernEngine(entity=None)
    req = _make_req(engine)
    item = BatchItem(id="e1", type="entity", params={"entity_type": "order", "entity_id": "nope"})
    with pytest.raises(LookupError, match="order/nope not found"):
        await _execute_entity_item(item, req)


async def test_execute_entity_item_denied_by_auth_manager_raises_permission_error() -> None:
    engine = _ModernEngine(entity={"order_id": "ORD-1"})
    tenant_key = SimpleNamespace(name="agent", tenant="acme", allowed_entity_types=["user"])
    auth_manager = SimpleNamespace(is_entity_allowed=lambda key, entity_type: False)
    req = _make_req(engine, tenant_key=tenant_key, tenant_id="acme", auth_manager=auth_manager)
    item = BatchItem(id="e1", type="entity", params={"entity_type": "order", "entity_id": "ORD-1"})
    with pytest.raises(PermissionError, match="cannot access entity type 'order'"):
        await _execute_entity_item(item, req)


async def test_execute_entity_item_falls_back_when_engine_rejects_tenant_id() -> None:
    engine = _LegacyEngine(entity={"order_id": "ORD-1"})
    req = _make_req(engine, tenant_id="acme")
    item = BatchItem(id="e1", type="entity", params={"entity_type": "order", "entity_id": "ORD-1"})

    data = await _execute_entity_item(item, req)

    assert data == {"order_id": "ORD-1"}
    # The fallback retried without tenant_id and succeeded.
    assert engine.calls == [("get_entity", ("order", "ORD-1"))]


async def test_execute_entity_item_propagates_unrelated_typeerror() -> None:
    """A TypeError that is NOT about the kwarg signature is a genuine engine bug
    and must propagate, not be silently retried with a dropped kwarg (C-2)."""

    class _Buggy(_ModernEngine):
        def get_entity(self, entity_type: str, entity_id: str, tenant_id: str | None = None):
            raise TypeError("unrelated engine bug")

    req = _make_req(_Buggy(), tenant_id="acme")
    item = BatchItem(id="e1", type="entity", params={"entity_type": "order", "entity_id": "ORD-1"})
    with pytest.raises(TypeError, match="unrelated engine bug"):
        await _execute_entity_item(item, req)


# ── _execute_metric_item ─────────────────────────────────────────


async def test_execute_metric_item_success() -> None:
    engine = _ModernEngine(metric={"value": 42, "unit": "USD"})
    req = _make_req(engine, tenant_id="acme")
    item = BatchItem(id="m1", type="metric", params={"name": "revenue", "window": "24h"})

    data = await _execute_metric_item(item, req)

    assert data == {"value": 42, "unit": "USD"}
    assert engine.calls[0][1] == ("revenue", "24h")


async def test_execute_metric_item_defaults_window_to_one_hour() -> None:
    engine = _ModernEngine(metric={"value": 1, "unit": "USD"})
    req = _make_req(engine)
    item = BatchItem(id="m1", type="metric", params={"name": "revenue"})

    await _execute_metric_item(item, req)

    assert engine.calls[0][1] == ("revenue", "1h")


async def test_execute_metric_item_non_string_params_raise_valueerror() -> None:
    req = _make_req(_ModernEngine())
    item = BatchItem(id="m1", type="metric", params={"name": 5, "window": "1h"})
    with pytest.raises(ValueError, match="requires string params"):
        await _execute_metric_item(item, req)


async def test_execute_metric_item_unknown_metric_raises_valueerror() -> None:
    req = _make_req(_ModernEngine())
    item = BatchItem(id="m1", type="metric", params={"name": "ghost", "window": "1h"})
    with pytest.raises(ValueError, match="Unknown metric"):
        await _execute_metric_item(item, req)


async def test_execute_metric_item_falls_back_when_engine_rejects_tenant_id() -> None:
    engine = _LegacyEngine(metric={"value": 7, "unit": "USD"})
    req = _make_req(engine, tenant_id="acme")
    item = BatchItem(id="m1", type="metric", params={"name": "revenue", "window": "1h"})

    data = await _execute_metric_item(item, req)

    assert data == {"value": 7, "unit": "USD"}
    assert engine.calls == [("get_metric", ("revenue", "1h"))]


async def test_execute_metric_item_propagates_unrelated_typeerror() -> None:
    class _Buggy(_ModernEngine):
        def get_metric(self, metric_name: str, window: str = "1h", tenant_id: str | None = None):
            raise TypeError("unrelated engine bug")

    req = _make_req(_Buggy(), tenant_id="acme")
    item = BatchItem(id="m1", type="metric", params={"name": "revenue", "window": "1h"})
    with pytest.raises(TypeError, match="unrelated engine bug"):
        await _execute_metric_item(item, req)


# ── _execute_query_item ──────────────────────────────────────────


def _query_result() -> dict[str, Any]:
    return {
        "data": [{"product": "PROD-1"}],
        "sql": "SELECT product FROM orders",
        "row_count": 1,
        "execution_time_ms": 3,
        "freshness_seconds": 1.5,
    }


async def test_execute_query_item_success_returns_answer_and_metadata() -> None:
    engine = _ModernEngine(query=_query_result())
    req = _make_req(engine, tenant_id="acme")
    item = BatchItem(id="q1", type="query", params={"question": "top products"})

    data = await _execute_query_item(item, req)

    assert data["answer"] == [{"product": "PROD-1"}]
    assert data["sql"] == "SELECT product FROM orders"
    assert data["metadata"] == {
        "rows_returned": 1,
        "execution_time_ms": 3,
        "data_freshness_seconds": 1.5,
    }


async def test_execute_query_item_non_string_question_raises_valueerror() -> None:
    req = _make_req(_ModernEngine())
    item = BatchItem(id="q1", type="query", params={"question": 5})
    with pytest.raises(ValueError, match="requires string param 'question'"):
        await _execute_query_item(item, req)


async def test_execute_query_item_invalid_context_raises_valueerror() -> None:
    req = _make_req(_ModernEngine())
    item = BatchItem(
        id="q1", type="query", params={"question": "hi there", "context": "not-a-dict"}
    )
    with pytest.raises(ValueError, match="'context' must be an object"):
        await _execute_query_item(item, req)


async def test_execute_query_item_falls_back_dropping_kwargs() -> None:
    engine = _LegacyEngine(query=_query_result())
    req = _make_req(engine, tenant_id="acme")
    item = BatchItem(id="q1", type="query", params={"question": "top products"})

    data = await _execute_query_item(item, req)

    assert data["answer"] == [{"product": "PROD-1"}]
    # The fallback dropped both allowed_tables and tenant_id and succeeded.
    assert engine.calls == [("execute_nl_query", ("top products",))]


async def test_execute_query_item_propagates_unrelated_typeerror() -> None:
    class _Buggy(_ModernEngine):
        def execute_nl_query(
            self, question: str, context=None, tenant_id=None, allowed_tables=None
        ):
            raise TypeError("unrelated engine bug")

    req = _make_req(_Buggy(), tenant_id="acme")
    item = BatchItem(id="q1", type="query", params={"question": "top products"})
    with pytest.raises(TypeError, match="unrelated engine bug"):
        await _execute_query_item(item, req)


# ── _execute_item routing + error isolation ──────────────────────


async def test_execute_item_routes_entity_metric_query() -> None:
    engine = _ModernEngine(
        entity={"order_id": "ORD-1"},
        metric={"value": 1, "unit": "USD"},
        query=_query_result(),
    )
    req = _make_req(engine)

    entity = await _execute_item(
        BatchItem(id="e", type="entity", params={"entity_type": "order", "entity_id": "ORD-1"}), req
    )
    metric = await _execute_item(
        BatchItem(id="m", type="metric", params={"name": "revenue", "window": "1h"}), req
    )
    query = await _execute_item(
        BatchItem(id="q", type="query", params={"question": "top products"}), req
    )

    assert (entity.status, metric.status, query.status) == ("ok", "ok", "ok")
    assert entity.data == {"order_id": "ORD-1"}


async def test_execute_item_wraps_errors_as_error_result() -> None:
    req = _make_req(_ModernEngine())
    item = BatchItem(id="bad", type="metric", params={"name": "ghost", "window": "1h"})

    result = await _execute_item(item, req)

    assert isinstance(result, BatchResult)
    assert result.id == "bad"
    assert result.status == "error"
    assert "Unknown metric" in (result.error or "")


# ── batch_query handler ──────────────────────────────────────────


async def test_batch_query_reports_mixed_results_and_duration() -> None:
    engine = _ModernEngine(
        entity={"order_id": "ORD-1"},
        metric={"value": 1, "unit": "USD"},
        query=_query_result(),
    )
    req = _make_req(engine)
    request = BatchRequest(
        requests=[
            BatchItem(
                id="ok-entity", type="entity", params={"entity_type": "order", "entity_id": "ORD-1"}
            ),
            BatchItem(id="bad-metric", type="metric", params={"name": "ghost", "window": "1h"}),
            BatchItem(id="ok-query", type="query", params={"question": "top products"}),
        ]
    )

    response = await batch_query(request, req)

    assert [r.id for r in response.results] == ["ok-entity", "bad-metric", "ok-query"]
    assert [r.status for r in response.results] == ["ok", "error", "ok"]
    assert response.duration_ms >= 0
