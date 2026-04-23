from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from agentflow.exceptions import (  # noqa: E402
    AuthError,
    DataFreshnessError,
    EntityNotFoundError,
    RateLimitError,
)
from agentflow_integrations.mcp.server import (  # noqa: E402
    AGENTFLOW_TOOLS,
    build_server,
    handle_tool_call,
)


@pytest.fixture
def fake_client() -> MagicMock:
    client = MagicMock()
    order_model = MagicMock()
    order_model.model_dump.return_value = {
        "order_id": "ORD-1",
        "status": "delivered",
        "total_amount": 42.0,
    }
    client.get_order.return_value = order_model

    metric_model = MagicMock()
    metric_model.model_dump.return_value = {
        "name": "revenue",
        "window": "1h",
        "value": 1234.56,
        "unit": "USD",
    }
    client.get_metric.return_value = metric_model

    query_model = MagicMock()
    query_model.model_dump.return_value = {
        "answer": [{"day": "2026-04-22", "count": 17}],
        "sql": "SELECT day, count(*) FROM orders GROUP BY day",
    }
    client.query.return_value = query_model

    health_model = MagicMock()
    health_model.model_dump.return_value = {
        "status": "healthy",
        "freshness_seconds": 12,
    }
    client.health.return_value = health_model

    catalog_model = MagicMock()
    catalog_model.model_dump.return_value = {
        "entities": ["order", "user", "product", "session"],
        "metrics": ["revenue", "order_count"],
    }
    client.catalog.return_value = catalog_model

    return client


def _single_text(content_blocks) -> dict[str, Any]:
    assert len(content_blocks) == 1
    block = content_blocks[0]
    assert block.type == "text"
    return json.loads(block.text)


def test_tool_catalog_exposes_expected_tools() -> None:
    names = {tool.name for tool in AGENTFLOW_TOOLS}
    assert names == {
        "entity_lookup",
        "metric_query",
        "nl_query",
        "health_check",
        "list_entities",
    }


def test_tool_schemas_declare_required_arguments() -> None:
    by_name = {tool.name: tool for tool in AGENTFLOW_TOOLS}
    assert by_name["entity_lookup"].inputSchema["required"] == [
        "entity_type",
        "entity_id",
    ]
    assert by_name["metric_query"].inputSchema["required"] == ["name"]
    assert by_name["nl_query"].inputSchema["required"] == ["question"]
    assert by_name["health_check"].inputSchema["properties"] == {}
    assert by_name["list_entities"].inputSchema["properties"] == {}


def test_entity_lookup_dispatches_to_typed_sdk_method(fake_client: MagicMock) -> None:
    blocks = handle_tool_call(
        "entity_lookup",
        {"entity_type": "order", "entity_id": "ORD-1"},
        fake_client,
    )

    fake_client.get_order.assert_called_once_with("ORD-1")
    assert _single_text(blocks) == {
        "order_id": "ORD-1",
        "status": "delivered",
        "total_amount": 42.0,
    }


def test_entity_lookup_rejects_unknown_type(fake_client: MagicMock) -> None:
    blocks = handle_tool_call(
        "entity_lookup",
        {"entity_type": "transaction", "entity_id": "TX-1"},
        fake_client,
    )

    payload = _single_text(blocks)
    assert payload["error"] == "invalid_argument"
    assert "transaction" in payload["message"]
    fake_client.get_order.assert_not_called()


def test_metric_query_applies_window_default(fake_client: MagicMock) -> None:
    blocks = handle_tool_call("metric_query", {"name": "revenue"}, fake_client)

    fake_client.get_metric.assert_called_once_with("revenue", "1h")
    payload = _single_text(blocks)
    assert payload["value"] == 1234.56


def test_metric_query_honors_explicit_window(fake_client: MagicMock) -> None:
    handle_tool_call(
        "metric_query",
        {"name": "error_rate", "window": "24h"},
        fake_client,
    )
    fake_client.get_metric.assert_called_once_with("error_rate", "24h")


def test_nl_query_passes_through_limit(fake_client: MagicMock) -> None:
    blocks = handle_tool_call(
        "nl_query",
        {"question": "orders today?", "limit": 25},
        fake_client,
    )

    fake_client.query.assert_called_once_with("orders today?", limit=25)
    assert _single_text(blocks)["sql"].startswith("SELECT")


def test_health_check_and_list_entities(fake_client: MagicMock) -> None:
    health = _single_text(handle_tool_call("health_check", {}, fake_client))
    catalog = _single_text(handle_tool_call("list_entities", None, fake_client))
    assert health["status"] == "healthy"
    assert "order" in catalog["entities"]


def test_unknown_tool_returns_error(fake_client: MagicMock) -> None:
    blocks = handle_tool_call("reboot_kafka", {}, fake_client)
    payload = _single_text(blocks)
    assert payload["error"].startswith("Unknown tool")


@pytest.mark.parametrize(
    ("exc", "expected_code"),
    [
        (EntityNotFoundError("order", "ORD-missing"), "not_found"),
        (AuthError("missing key"), "auth"),
        (RateLimitError("slow down"), "rate_limit"),
        (DataFreshnessError("stale pipeline"), "stale_data"),
    ],
)
def test_sdk_exceptions_are_mapped_to_error_codes(
    fake_client: MagicMock,
    exc: Exception,
    expected_code: str,
) -> None:
    fake_client.get_order.side_effect = exc
    blocks = handle_tool_call(
        "entity_lookup",
        {"entity_type": "order", "entity_id": "ORD-missing"},
        fake_client,
    )
    payload = _single_text(blocks)
    assert payload["error"] == expected_code


def test_build_server_registers_tool_handlers() -> None:
    server = build_server(client_factory=MagicMock)
    # The low-level Server does not expose a public registry, but the
    # decorator registration stores handlers on `request_handlers` keyed
    # by request type. Confirm at minimum the server name is set and
    # initialization options can be derived.
    assert server.name == "agentflow"
    init_options = server.create_initialization_options()
    assert init_options.server_name == "agentflow"
