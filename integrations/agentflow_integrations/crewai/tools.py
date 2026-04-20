from typing import Any

from crewai_tools import BaseTool
from pydantic import ConfigDict, Field

from agentflow import AgentFlowClient


class AgentFlowCrewAITool(BaseTool):
    client: Any = Field(exclude=True)

    model_config = ConfigDict(arbitrary_types_allowed=True)


class OrderLookupTool(AgentFlowCrewAITool):
    name: str = "AgentFlow Order Lookup"
    description: str = (
        "Look up real-time order details by order ID. "
        "Returns status, total amount, customer ID, items count, and timestamps."
    )

    def _run(self, order_id: str) -> str:
        order = self.client.get_order(order_id)
        return order.model_dump_json(indent=2)


class MetricQueryTool(AgentFlowCrewAITool):
    name: str = "AgentFlow Metric Query"
    description: str = (
        "Query business metrics from the data platform. "
        "Available metrics: revenue, order_count, avg_order_value, "
        "conversion_rate, active_sessions, error_rate. "
        "Specify metric_name and optional window (1h, 24h, 7d)."
    )

    def _run(self, metric_name: str, window: str = "1h") -> str:
        result = self.client.get_metric(metric_name, window)
        return f"{metric_name} ({window}): {result.value} {result.unit}"


class NLQueryTool(AgentFlowCrewAITool):
    name: str = "AgentFlow Natural Language Query"
    description: str = (
        "Ask business questions in natural language. "
        "The platform translates to SQL and returns results. "
        "Example: 'Top 5 products by revenue today'"
    )

    def _run(self, question: str) -> str:
        result = self.client.query(question)
        return result.model_dump_json()


def get_agentflow_tools(base_url: str, api_key: str) -> list[BaseTool]:
    client = AgentFlowClient(base_url, api_key)
    return [
        OrderLookupTool(client=client),
        MetricQueryTool(client=client),
        NLQueryTool(client=client),
    ]
