"""Regression tests for M-C1 (audit-2026-05): the initial
``SearchIndex.rebuild()`` call in the API lifespan must not be allowed to
crash the boot sequence. A degraded search surface is preferable to a
fully-down API."""

from __future__ import annotations

import logging
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentflow_runtime.serving.api import main as main_module
from agentflow_runtime.serving.api.main import app
from agentflow_runtime.serving.semantic_layer import search_index as search_index_module


def test_lifespan_survives_search_rebuild_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def _explode(self) -> None:  # type: ignore[no-untyped-def]
        raise RuntimeError("simulated catalogue load failure")

    monkeypatch.setattr(search_index_module.SearchIndex, "rebuild", _explode)

    with caplog.at_level(logging.WARNING):
        with TestClient(app) as client:
            response = client.get("/v1/health")
            assert response.status_code == 200
            # The periodic background rebuilder must still be scheduled even
            # when the initial sync rebuild raised — otherwise the search
            # surface would never recover for the lifetime of the process.
            assert app.state.search_index_rebuild_task is not None

    assert any(
        "search_index_initial_rebuild_failed" in record.getMessage() for record in caplog.records
    ), "expected a warning log entry naming the initial-rebuild failure"


def test_startup_failure_closes_initialized_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = Mock()
    pool.initialize.return_value = None
    monkeypatch.setattr(main_module, "DuckDBPool", Mock(return_value=pool))
    monkeypatch.setattr(
        main_module,
        "QueryEngine",
        Mock(side_effect=RuntimeError("simulated query-engine startup failure")),
    )
    isolated_app = FastAPI(lifespan=main_module.lifespan)

    with pytest.raises(RuntimeError, match="simulated query-engine startup failure"):
        with TestClient(isolated_app):
            pass

    pool.close.assert_called_once_with()
