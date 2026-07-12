"""P2-3 wiring: the lifespan actually enforces the transport policy.

`tests/unit/test_transport_policy.py` proves the policy function; this
file proves main.py calls it before building anything — a production
boot over plaintext external ClickHouse must die in lifespan startup,
and a production+demo combination must never come up at all.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.serving.api.main import app
from src.serving.transport_policy import InsecureTransportError


def test_production_refuses_insecure_external_clickhouse_boot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTFLOW_PROFILE", "production")
    monkeypatch.setenv("SERVING_BACKEND", "clickhouse")
    monkeypatch.setenv("CLICKHOUSE_HOST", "ch.prod.internal")
    monkeypatch.delenv("CLICKHOUSE_SECURE", raising=False)

    with pytest.raises(InsecureTransportError, match="clickhouse"), TestClient(app):
        pass


def test_production_never_boots_the_demo_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTFLOW_PROFILE", "production")
    monkeypatch.setenv("AGENTFLOW_DEMO_MODE", "true")

    with pytest.raises(RuntimeError, match="demo"), TestClient(app):
        pass


def test_production_boots_on_local_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    # conftest pins SERVING_BACKEND=duckdb and REDIS_URL defaults to
    # loopback: nothing external, nothing plaintext, the gate stays quiet.
    monkeypatch.setenv("AGENTFLOW_PROFILE", "production")

    with TestClient(app):
        assert app.state.profile == "production"


def test_default_boot_is_dev_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENTFLOW_PROFILE", raising=False)
    monkeypatch.delenv("AGENTFLOW_DEMO_MODE", raising=False)

    with TestClient(app):
        assert app.state.profile == "dev"
