import importlib
import sys
import types
from datetime import UTC, datetime

from agentflow.models import MetricResult, OrderEntity, QueryResult
from pydantic import BaseModel, ConfigDict


def load_crewai_modules(monkeypatch):
    fake_crewai_tools = types.ModuleType("crewai_tools")

    class FakeBaseTool(BaseModel):
        name: str = ""
        description: str = ""

        model_config = ConfigDict(arbitrary_types_allowed=True)

    fake_crewai_tools.BaseTool = FakeBaseTool
    monkeypatch.setitem(sys.modules, "crewai_tools", fake_crewai_tools)
    sys.modules.pop("agentflow_integrations.crewai", None)
    sys.modules.pop("agentflow_integrations.crewai.tools", None)

    tools_module = importlib.import_module("agentflow_integrations.crewai.tools")
    package_module = importlib.import_module("agentflow_integrations.crewai")

    return importlib.reload(package_module), importlib.reload(tools_module), FakeBaseTool


class FakeClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None):
        self.base_url = base_url
        self.api_key = api_key
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


def test_get_agentflow_tools_is_exported(monkeypatch):
    package_module, _, _ = load_crewai_modules(monkeypatch)

    assert callable(package_module.get_agentflow_tools)


def test_get_agentflow_tools_returns_three_base_tools(monkeypatch):
    package_module, tools_module, fake_base_tool = load_crewai_modules(monkeypatch)
    created = []

    class ToolkitClient(FakeClient):
        def __init__(self, base_url: str, api_key: str):
            super().__init__(base_url, api_key)
            created.append(self)

    monkeypatch.setattr(tools_module, "AgentFlowClient", ToolkitClient)

    tools = package_module.get_agentflow_tools("http://localhost:8000", "af-dev-key")

    assert len(tools) == 3
    assert [tool.name for tool in tools] == [
        "AgentFlow Order Lookup",
        "AgentFlow Metric Query",
        "AgentFlow Natural Language Query",
    ]
    assert all(isinstance(tool, fake_base_tool) for tool in tools)
    assert all(tool.client is created[0] for tool in tools)
    assert created[0].base_url == "http://localhost:8000"
    assert created[0].api_key == "af-dev-key"


def test_order_lookup_tool_calls_sdk_and_returns_json(monkeypatch):
    _, tools_module, _ = load_crewai_modules(monkeypatch)
    tool = tools_module.OrderLookupTool(client=FakeClient())

    result = tool._run("ORD-1")

    assert '"order_id": "ORD-1"' in result
    assert tool.client.calls == [("get_order", "ORD-1")]


def test_metric_query_tool_uses_default_window(monkeypatch):
    _, tools_module, _ = load_crewai_modules(monkeypatch)
    tool = tools_module.MetricQueryTool(client=FakeClient())

    result = tool._run("revenue")

    assert result == "revenue (1h): 42.5 USD"
    assert tool.client.calls == [("get_metric", "revenue", "1h")]


def test_metric_query_tool_passes_custom_window(monkeypatch):
    _, tools_module, _ = load_crewai_modules(monkeypatch)
    tool = tools_module.MetricQueryTool(client=FakeClient())

    result = tool._run("revenue", window="24h")

    assert result == "revenue (24h): 42.5 USD"
    assert tool.client.calls == [("get_metric", "revenue", "24h")]


def test_nl_query_tool_calls_sdk_and_returns_json(monkeypatch):
    _, tools_module, _ = load_crewai_modules(monkeypatch)
    tool = tools_module.NLQueryTool(client=FakeClient())

    result = tool._run("What's revenue today?")

    assert '"sql":"SELECT 1"' in result
    assert tool.client.calls == [("query", "What's revenue today?")]


def test_tools_have_agent_facing_descriptions(monkeypatch):
    _, tools_module, _ = load_crewai_modules(monkeypatch)

    assert "real-time order details" in (
        tools_module.OrderLookupTool(client=FakeClient()).description
    )
    assert "business metrics" in tools_module.MetricQueryTool(client=FakeClient()).description
    assert "natural language" in tools_module.NLQueryTool(client=FakeClient()).description
