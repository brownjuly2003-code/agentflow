from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from src.serving.semantic_layer.catalog import DataCatalog
from src.serving.semantic_layer.query_engine import QueryEngine


def test_paginated_query_rejects_unsafe_sql(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = QueryEngine(catalog=DataCatalog(), db_path=":memory:")
    engine._tenant_router = Mock()
    engine._tenant_router.has_config.return_value = False
    engine._tenant_router.get_duckdb_schema.return_value = None
    backend = Mock()
    backend.name = "duckdb"
    engine._backend = backend
    engine._backend_name = backend.name
    monkeypatch.setattr(
        engine,
        "_translate_question_to_sql",
        lambda question, tenant_id=None: "SELECT * FROM information_schema.tables",
    )

    with pytest.raises(HTTPException) as exc_info:
        engine.paginated_query("show database tables")

    assert exc_info.value.status_code == 403
    backend.execute.assert_not_called()
