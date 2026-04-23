from datetime import UTC, datetime

from agentflow import AgentFlowClient
from agentflow.models import MetricResult, OrderEntity, QueryResult
from agentflow_integrations.langchain import (
    AgentFlowToolkit,
    MetricQueryTool,
    NLQueryTool,
    OrderLookupTool,
)


class FakeClient(AgentFlowClient):
    def __init__(self):
        self.calls = []

    def get_order(self, order_id: str) -> OrderEntity:
        self.calls.append(("get_order", order_id))
        return OrderEntity(
            order_id=order_id,
            user_id="USR-1",
            status="pending",
            total_amount=19.99,
            currency="USD",
            created_at=datetime.now(UTC),
        )

    def get_metric(self, name: str, window: str = "1h") -> MetricResult:
        self.calls.append(("get_metric", name, window))
        return MetricResult(
            metric_name=name,
            value=42.5,
            unit="USD",
            window=window,
            computed_at=datetime.now(UTC),
        )

    def query(self, question: str) -> QueryResult:
        self.calls.append(("query", question))
        return QueryResult(answer=[{"metric": "revenue", "value": 42.5}], sql="SELECT 1")


def test_toolkit_returns_three_tools_with_shared_client(monkeypatch):
    created = []

    class ToolkitClient(FakeClient):
        def __init__(self, base_url: str, api_key: str):
            super().__init__()
            self.base_url = base_url
            self.api_key = api_key
            created.append(self)

    monkeypatch.setattr("agentflow_integrations.langchain.toolkit.AgentFlowClient", ToolkitClient)

    toolkit = AgentFlowToolkit("http://localhost:8000", api_key="af-dev-key")
    tools = toolkit.get_tools()

    assert len(tools) == 3
    assert [tool.name for tool in tools] == [
        "agentflow_order_lookup",
        "agentflow_metric",
        "agentflow_query",
    ]
    assert all(tool.client is created[0] for tool in tools)


def test_order_lookup_tool_calls_sdk_and_returns_json():
    client = FakeClient()
    tool = OrderLookupTool(client=client)

    result = tool._run("ORD-1")

    assert ('"order_id": "ORD-1"') in result
    assert client.calls == [("get_order", "ORD-1")]


def test_metric_query_tool_uses_default_window():
    client = FakeClient()
    tool = MetricQueryTool(client=client)

    result = tool._run("revenue")

    assert result == "revenue (1h): 42.5 USD"
    assert client.calls == [("get_metric", "revenue", "1h")]


def test_metric_query_tool_passes_custom_window():
    client = FakeClient()
    tool = MetricQueryTool(client=client)

    result = tool._run("revenue", window="24h")

    assert result == "revenue (24h): 42.5 USD"
    assert client.calls == [("get_metric", "revenue", "24h")]


def test_nl_query_tool_calls_sdk_and_returns_json():
    client = FakeClient()
    tool = NLQueryTool(client=client)

    result = tool._run("What's revenue today?")

    assert '"sql":"SELECT 1"' in result
    assert client.calls == [("query", "What's revenue today?")]


def test_tools_have_agent_facing_descriptions():
    assert "order status" in OrderLookupTool(client=FakeClient()).description
    assert "business metrics" in MetricQueryTool(client=FakeClient()).description
    assert "natural language question" in NLQueryTool(client=FakeClient()).description
