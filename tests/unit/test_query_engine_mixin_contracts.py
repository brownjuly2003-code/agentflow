from __future__ import annotations

import tomllib
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.serving.semantic_layer.catalog import DataCatalog
from src.serving.semantic_layer.query.entity_queries import EntityQueryMixin
from src.serving.semantic_layer.query.metric_queries import MetricQueryMixin
from src.serving.semantic_layer.query.nl_queries import NLQueryMixin
from src.serving.semantic_layer.query.sql_builder import SQLBuilderMixin


class _MinimalQueryHost(
    SQLBuilderMixin,
    NLQueryMixin,
    EntityQueryMixin,
    MetricQueryMixin,
):
    def __init__(self) -> None:
        self.catalog = DataCatalog()
        self._tenant_router = Mock()
        self._tenant_router.has_config.return_value = False
        self._tenant_router.get_duckdb_schema.return_value = None
        self._backend = Mock()
        self._backend.name = "duckdb"
        self._backend_name = self._backend.name
        self._duckdb_backend = Mock()
        self._duckdb_backend.name = "duckdb"

    def _table_columns(self, table_name: str) -> set[str]:
        del table_name
        return set()

    def _translate_question_to_sql(
        self,
        question: str,
        tenant_id: str | None = None,
    ) -> str:
        del question, tenant_id
        return "SELECT * FROM orders_v2"


def _pyproject_path() -> Path:
    return Path(__file__).resolve().parents[2] / "pyproject.toml"


@pytest.fixture
def host() -> _MinimalQueryHost:
    return _MinimalQueryHost()


def test_query_package_has_no_broad_attr_defined_override() -> None:
    pyproject = tomllib.loads(_pyproject_path().read_text(encoding="utf-8"))
    overrides = pyproject["tool"]["mypy"].get("overrides", [])

    assert not any(
        override.get("module") == "src.serving.semantic_layer.query.*"
        and "attr-defined" in override.get("disable_error_code", [])
        for override in overrides
    )


def test_get_entity_runs_against_minimal_host_contract(host: _MinimalQueryHost) -> None:
    host._backend.execute.return_value = [{"order_id": "ORD-1", "status": "confirmed"}]

    result = host.get_entity("order", "ORD-1")

    assert result == {"order_id": "ORD-1", "status": "confirmed"}
    host._backend.execute.assert_called_once()


def test_get_metric_runs_against_minimal_host_contract(host: _MinimalQueryHost) -> None:
    host._backend.scalar.return_value = 12.5

    result = host.get_metric("revenue")

    assert result == {"value": 12.5, "unit": "USD"}
    host._backend.scalar.assert_called_once()


def test_execute_nl_query_runs_against_minimal_host_contract(host: _MinimalQueryHost) -> None:
    host._backend.execute.return_value = [{"order_id": "ORD-1"}]

    result = host.execute_nl_query("show orders")

    assert result["data"] == [{"order_id": "ORD-1"}]
    assert result["sql"] == "SELECT * FROM orders_v2"
    host._backend.execute.assert_called_once_with("SELECT * FROM orders_v2")
