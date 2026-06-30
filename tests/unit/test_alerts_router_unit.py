"""Unit coverage for ``src.serving.api.routers.alerts`` — the alert-config CRUD
endpoints and their validation / response-shaping logic.

The dispatcher internals (``alert_dispatcher.create_alert`` etc.) and the live
HTTP path are covered by ``tests/integration/test_alerts.py``. These tests pin
the router's own behaviour at the unit layer with in-process fakes (no Docker,
no running app): tenant resolution, metric/window validation (404/422), the
not-found branches, and the ``secret``-exclusion on read/update responses — so
a regression in the alerts API contract fails fast.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException, Response

from src.serving.api.alerts.dispatcher import AlertRule
from src.serving.api.routers import alerts as alerts_module
from src.serving.api.routers.alerts import (
    AlertCreateRequest,
    AlertUpdateRequest,
    _tenant,
    _validate_metric_request,
    alert_history,
    list_my_alerts,
    modify_alert,
    register_alert,
    remove_alert,
)
from src.serving.api.routers.alerts import (
    test_alert as _test_alert_endpoint,
)

# ── Fakes ────────────────────────────────────────────────────────


def _rule(**overrides: Any) -> AlertRule:
    base: dict[str, Any] = {
        "id": "al-1",
        "name": "revenue guard",
        "tenant": "acme",
        "metric": "revenue",
        "window": "1h",
        "condition": "above",
        "threshold": 100.0,
        "webhook_url": "https://example.com/hook",
        "secret": "s3cr3t-signing-key",
        "cooldown_minutes": 30,
        "created_at": datetime(2026, 6, 13, tzinfo=UTC),
        "updated_at": datetime(2026, 6, 13, tzinfo=UTC),
    }
    base.update(overrides)
    return AlertRule(**base)


def _req(
    *,
    metrics: dict[str, Any] | None = None,
    tenant_key: Any = None,
    query_conn: Any = None,
) -> SimpleNamespace:
    catalog = SimpleNamespace(
        metrics=metrics
        if metrics is not None
        else {"revenue": SimpleNamespace(available_windows=["1h", "24h"])}
    )
    app = SimpleNamespace(
        state=SimpleNamespace(catalog=catalog, query_engine=SimpleNamespace(_conn=query_conn))
    )
    return SimpleNamespace(app=app, state=SimpleNamespace(tenant_key=tenant_key))


class _FakeDispatcher:
    def __init__(self) -> None:
        self.tested: list[AlertRule] = []

    async def send_test_alert(self, alert: AlertRule) -> dict[str, object]:
        self.tested.append(alert)
        return {"status": "sent", "alert_id": alert.id}


@pytest.fixture(autouse=True)
def _stub_config_path(monkeypatch: pytest.MonkeyPatch) -> None:
    # Every endpoint resolves the config path first; pin it so no test touches
    # the real config/alerts.yaml.
    monkeypatch.setattr(alerts_module, "get_alert_config_path", lambda app: Path("alerts.yaml"))


# ── _tenant ──────────────────────────────────────────────────────


def test_tenant_defaults_to_default_when_no_key() -> None:
    assert _tenant(_req()) == "default"


def test_tenant_uses_tenant_key_tenant() -> None:
    assert _tenant(_req(tenant_key=SimpleNamespace(tenant="acme"))) == "acme"


# ── _validate_metric_request ─────────────────────────────────────


def test_validate_metric_unknown_raises_404() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_metric_request(_req(), "ghost", "1h")
    assert exc.value.status_code == 404
    assert "Unknown metric" in exc.value.detail


def test_validate_metric_bad_window_raises_422() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_metric_request(_req(), "revenue", "7d")
    assert exc.value.status_code == 422
    assert "Unsupported window" in exc.value.detail


def test_validate_metric_ok_does_not_raise() -> None:
    _validate_metric_request(_req(), "revenue", "1h")


# ── register_alert ───────────────────────────────────────────────


async def test_register_alert_validates_creates_and_starts_dispatcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: dict[str, Any] = {}

    def fake_create(path: Path, **kwargs: Any) -> AlertRule:
        created.update(kwargs)
        return _rule(name=kwargs["name"], tenant=kwargs["tenant"])

    started: list[Any] = []
    monkeypatch.setattr(alerts_module, "create_alert", fake_create)
    monkeypatch.setattr(alerts_module, "ensure_alert_dispatcher", lambda app: started.append(app))

    payload = AlertCreateRequest(
        name="revenue guard",
        metric="revenue",
        window="24h",
        condition="above",
        threshold=100.0,
        webhook_url="https://example.com/hook",
    )
    result = await register_alert(payload, _req(tenant_key=SimpleNamespace(tenant="acme")))

    assert result["id"] == "al-1"
    assert created["tenant"] == "acme"
    assert created["metric"] == "revenue"
    assert started, "dispatcher was started after registration"


async def test_register_alert_rejects_unknown_metric(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        alerts_module,
        "create_alert",
        lambda *a, **k: pytest.fail("create_alert must not run when validation fails"),
    )
    payload = AlertCreateRequest(
        name="x",
        metric="ghost",
        window="1h",
        condition="above",
        threshold=1.0,
        webhook_url="https://example.com/hook",
    )
    with pytest.raises(HTTPException) as exc:
        await register_alert(payload, _req())
    assert exc.value.status_code == 404


# ── list_my_alerts ───────────────────────────────────────────────


async def test_list_alerts_excludes_signing_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        alerts_module, "list_alerts", lambda path, tenant: [_rule(), _rule(id="al-2")]
    )
    result = await list_my_alerts(_req())

    assert [a["id"] for a in result["alerts"]] == ["al-1", "al-2"]
    assert all("secret" not in a for a in result["alerts"])


# ── modify_alert ─────────────────────────────────────────────────


async def test_modify_alert_not_found_raises_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(alerts_module, "get_alert", lambda path, alert_id, tenant: None)
    with pytest.raises(HTTPException) as exc:
        await modify_alert("al-x", AlertUpdateRequest(threshold=5.0), _req())
    assert exc.value.status_code == 404


async def test_modify_alert_updates_and_excludes_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(alerts_module, "get_alert", lambda path, alert_id, tenant: _rule())
    monkeypatch.setattr(
        alerts_module, "update_alert", lambda path, alert_id, tenant, updates: _rule(threshold=5.0)
    )
    result = await modify_alert("al-1", AlertUpdateRequest(threshold=5.0), _req())

    assert result["threshold"] == 5.0
    assert "secret" not in result


async def test_modify_alert_lost_race_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    # get_alert sees the rule but update_alert finds it already gone.
    monkeypatch.setattr(alerts_module, "get_alert", lambda path, alert_id, tenant: _rule())
    monkeypatch.setattr(alerts_module, "update_alert", lambda path, alert_id, tenant, updates: None)
    with pytest.raises(HTTPException) as exc:
        await modify_alert("al-1", AlertUpdateRequest(threshold=5.0), _req())
    assert exc.value.status_code == 404


async def test_modify_alert_revalidates_new_metric(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(alerts_module, "get_alert", lambda path, alert_id, tenant: _rule())
    monkeypatch.setattr(
        alerts_module,
        "update_alert",
        lambda *a, **k: pytest.fail("update must not run when the new metric is invalid"),
    )
    with pytest.raises(HTTPException) as exc:
        await modify_alert("al-1", AlertUpdateRequest(metric="ghost"), _req())
    assert exc.value.status_code == 404


# ── remove_alert ─────────────────────────────────────────────────


async def test_remove_alert_returns_204(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(alerts_module, "deactivate_alert", lambda path, alert_id, tenant: True)
    result = await remove_alert("al-1", _req())
    assert isinstance(result, Response)
    assert result.status_code == 204


async def test_remove_alert_not_found_raises_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(alerts_module, "deactivate_alert", lambda path, alert_id, tenant: False)
    with pytest.raises(HTTPException) as exc:
        await remove_alert("al-x", _req())
    assert exc.value.status_code == 404


# ── test_alert ───────────────────────────────────────────────────


async def test_test_alert_sends_through_dispatcher(monkeypatch: pytest.MonkeyPatch) -> None:
    dispatcher = _FakeDispatcher()
    monkeypatch.setattr(alerts_module, "get_alert", lambda path, alert_id, tenant: _rule())
    monkeypatch.setattr(alerts_module, "ensure_alert_dispatcher", lambda app: dispatcher)

    result = await _test_alert_endpoint("al-1", _req())

    assert result == {"status": "sent", "alert_id": "al-1"}
    assert len(dispatcher.tested) == 1


async def test_test_alert_not_found_raises_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(alerts_module, "get_alert", lambda path, alert_id, tenant: None)
    with pytest.raises(HTTPException) as exc:
        await _test_alert_endpoint("al-x", _req())
    assert exc.value.status_code == 404


# ── alert_history ────────────────────────────────────────────────


class _CursorConn:
    """A connection stub that yields a closeable cursor — the history read
    offloads onto a dedicated cursor (audit_30 A2). get_alert_history is stubbed,
    so the cursor itself is never queried."""

    def cursor(self) -> _CursorConn:
        return self

    def close(self) -> None:
        pass


async def test_alert_history_returns_records(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(alerts_module, "get_alert", lambda path, alert_id, tenant: _rule())
    monkeypatch.setattr(
        alerts_module, "get_alert_history", lambda conn, alert_id: [{"fired_at": "2026-06-13"}]
    )
    result = await alert_history("al-1", _req(query_conn=_CursorConn()))
    assert result == {"history": [{"fired_at": "2026-06-13"}]}


async def test_alert_history_not_found_raises_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(alerts_module, "get_alert", lambda path, alert_id, tenant: None)
    with pytest.raises(HTTPException) as exc:
        await alert_history("al-x", _req())
    assert exc.value.status_code == 404
