"""Regression tests for M-C1 (audit_kimi_25_05_26): the initial
``SearchIndex.rebuild()`` call in the API lifespan must not be allowed to
crash the boot sequence. A degraded search surface is preferable to a
fully-down API."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from src.serving.api.main import app
from src.serving.semantic_layer import search_index as search_index_module


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
        "search_index_initial_rebuild_failed" in record.getMessage()
        for record in caplog.records
    ), "expected a warning log entry naming the initial-rebuild failure"
