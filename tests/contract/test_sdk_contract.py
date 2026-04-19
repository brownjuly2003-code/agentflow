import sys
from pathlib import Path

import pytest

pytest_plugins = ("tests.e2e.conftest",)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sdk"))

from agentflow import AgentFlowClient
from agentflow.exceptions import AuthError, EntityNotFoundError


pytestmark = pytest.mark.integration


@pytest.fixture
def client(base_url: str, ops_api_key: str):
    sdk_client = AgentFlowClient(base_url=base_url, api_key=ops_api_key)
    try:
        yield sdk_client
    finally:
        sdk_client._client.close()


def test_get_order_returns_typed_response(client: AgentFlowClient):
    order = client.get_order("ORD-20260404-1001")

    assert order.order_id == "ORD-20260404-1001"
    assert order.user_id == "USR-10001"
    assert order.total_amount > 0


def test_get_user_returns_typed_response(client: AgentFlowClient):
    user = client.get_user("USR-10001")

    assert user.user_id == "USR-10001"
    assert user.total_orders >= 1
    assert user.total_spent > 0


def test_query_returns_sql_and_rows(client: AgentFlowClient):
    result = client.query("Show me top 3 products", limit=3)

    assert result.sql
    assert isinstance(result.answer, list)
    assert len(result.answer) == 3
    assert result.metadata["rows_returned"] == 3


def test_paginate_returns_page_lists(client: AgentFlowClient):
    pages = list(client.paginate("Show me top 10 products", page_size=4))

    assert len(pages) == 3
    assert sum(len(page) for page in pages) == 10
    assert all(isinstance(page, list) for page in pages)
    assert all(isinstance(row, dict) for page in pages for row in page)


def test_invalid_api_key_raises_auth_error(base_url: str):
    sdk_client = AgentFlowClient(base_url=base_url, api_key="invalid")
    try:
        with pytest.raises(AuthError):
            sdk_client.get_order("ORD-20260404-1001")
    finally:
        sdk_client._client.close()


def test_missing_entity_raises_not_found(client: AgentFlowClient):
    with pytest.raises(EntityNotFoundError) as exc_info:
        client.get_order("ORD-99999999-0000")

    assert exc_info.value.entity_type == "order"
    assert exc_info.value.entity_id == "ORD-99999999-0000"
