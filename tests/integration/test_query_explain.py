import sys
import types
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from src.serving.api.auth import TenantKey
from src.serving.api.main import app
from src.serving.semantic_layer.query_engine import QueryEngine

pytestmark = pytest.mark.integration


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _disable_auth(client: TestClient) -> None:
    manager = client.app.state.auth_manager
    manager.keys_by_value = {}
    manager._rate_windows.clear()


def _set_auth(client: TestClient, key: str = "explain-test-key") -> str:
    manager = client.app.state.auth_manager
    manager.keys_by_value = {
        key: TenantKey(
            key=key,
            name="explain-agent",
            tenant="acme",
            rate_limit_rpm=100,
            allowed_entity_types=None,
            created_at=datetime.now(UTC).date(),
        )
    }
    manager._rate_windows.clear()
    return key


def test_query_explain_requires_api_key_when_auth_is_configured(client):
    _set_auth(client)

    response = client.post(
        "/v1/query/explain",
        json={"question": "top 5 products by revenue today"},
    )

    assert response.status_code == 401
    assert "X-API-Key" in response.json()["detail"]


def test_query_explain_returns_sql_tables_estimate_and_warning(client):
    _disable_auth(client)

    response = client.post(
        "/v1/query/explain",
        json={"question": "What is the revenue today?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["question"] == "What is the revenue today?"
    assert payload["sql"].startswith("SELECT")
    assert payload["tables_accessed"] == ["orders_v2"]
    assert payload["estimated_rows"] is not None
    assert payload["engine"] == "rule_based"
    assert payload["warning"] == "Full table scan on orders_v2 (no index)"


def test_query_explain_does_not_execute_the_underlying_query(client, monkeypatch):
    _disable_auth(client)

    def fail_execute_nl_query(self, question: str, context=None):
        raise AssertionError("execute_nl_query must not be called")

    monkeypatch.setattr(QueryEngine, "execute_nl_query", fail_execute_nl_query)

    response = client.post(
        "/v1/query/explain",
        json={"question": "Show me top 3 products"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["tables_accessed"] == ["products_current"]


def test_query_explain_returns_400_for_untranslatable_question(client):
    _disable_auth(client)

    response = client.post(
        "/v1/query/explain",
        json={"question": "What is the meaning of life?"},
    )

    assert response.status_code == 400
    assert "Could not translate question" in response.json()["detail"]


def test_query_explain_reports_llm_engine_when_llm_translation_is_used(client, monkeypatch):
    _disable_auth(client)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "anthropic", types.ModuleType("anthropic"))

    from src.serving.semantic_layer import nl_engine

    monkeypatch.setattr(nl_engine, "_ANTHROPIC_KEY", "test-key")
    monkeypatch.setattr(
        nl_engine,
        "_llm_translate",
        lambda question, catalog: "SELECT order_id FROM orders_v2 LIMIT 5",
    )

    response = client.post(
        "/v1/query/explain",
        json={"question": "top 5 products by revenue today"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["engine"] == "llm"
    assert payload["sql"] == "SELECT order_id FROM orders_v2 LIMIT 5"
