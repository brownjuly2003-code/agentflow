import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "integrations"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sdk"))

from agentflow.models import MetricResult, QueryResult
from agentflow_integrations.llamaindex import AgentFlowReader, AgentFlowToolSpec


class FakeClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key
        self.calls = []

    def query(self, question: str) -> QueryResult:
        self.calls.append(("query", question))
        return QueryResult(
            answer=[
                {
                    "order_id": "ORD-1",
                    "status": "pending",
                    "total_amount": 25.0,
                    "freshness_seconds": 3.5,
                    "quality_score": 0.99,
                }
            ],
            sql="SELECT * FROM orders",
        )

    def get_metric(self, name: str, window: str = "1h") -> MetricResult:
        self.calls.append(("get_metric", name, window))
        return MetricResult(
            metric_name=name,
            value=25.0,
            unit="USD",
            window=window,
            computed_at=datetime.now(UTC),
        )


def test_reader_loads_entity_rows_as_documents(monkeypatch):
    monkeypatch.setattr("agentflow_integrations.llamaindex.reader.AgentFlowClient", FakeClient)
    reader = AgentFlowReader("http://localhost:8000", "af-dev-key")

    documents = reader.load_data(entity_type="order")

    assert len(documents) == 1
    assert "ORD-1" in documents[0].text
    assert documents[0].metadata["entity_type"] == "order"
    assert documents[0].metadata["entity_id"] == "ORD-1"
    assert documents[0].metadata["freshness_seconds"] == 3.5
    assert documents[0].metadata["quality_score"] == 0.99
    assert reader.client.calls == [("query", "List order entities")]


def test_reader_loads_metrics_as_documents(monkeypatch):
    monkeypatch.setattr("agentflow_integrations.llamaindex.reader.AgentFlowClient", FakeClient)
    reader = AgentFlowReader("http://localhost:8000", "af-dev-key")

    documents = reader.load_data(metric_names=["revenue"], window="24h")

    assert len(documents) == 1
    assert "revenue" in documents[0].text
    assert documents[0].metadata["entity_type"] == "metric"
    assert documents[0].metadata["entity_id"] == "revenue"
    assert documents[0].metadata["window"] == "24h"
    assert reader.client.calls == [("get_metric", "revenue", "24h")]


def test_reader_combines_entities_and_metrics(monkeypatch):
    monkeypatch.setattr("agentflow_integrations.llamaindex.reader.AgentFlowClient", FakeClient)
    reader = AgentFlowReader("http://localhost:8000", "af-dev-key")

    documents = reader.load_data(entity_type="order", metric_names=["revenue"])

    assert len(documents) == 2
    assert reader.client.calls == [
        ("query", "List order entities"),
        ("get_metric", "revenue", "24h"),
    ]


def test_reader_returns_empty_list_without_sources(monkeypatch):
    monkeypatch.setattr("agentflow_integrations.llamaindex.reader.AgentFlowClient", FakeClient)
    reader = AgentFlowReader("http://localhost:8000", "af-dev-key")

    assert reader.load_data() == []
    assert reader.client.calls == []


def test_tool_spec_exposes_agentflow_functions(monkeypatch):
    monkeypatch.setattr("agentflow_integrations.llamaindex.tool_spec.AgentFlowClient", FakeClient)

    spec = AgentFlowToolSpec("http://localhost:8000", "af-dev-key")

    assert spec.spec_functions == ["get_order", "get_metric", "query"]
