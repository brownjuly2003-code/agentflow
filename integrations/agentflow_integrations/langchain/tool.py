from agentflow import AgentFlowClient
from langchain.tools import BaseTool
from pydantic import ConfigDict, Field


class AgentFlowTool(BaseTool):
    client: AgentFlowClient = Field(exclude=True)

    model_config = ConfigDict(arbitrary_types_allowed=True)


class OrderLookupTool(AgentFlowTool):
    name: str = "agentflow_order_lookup"
    description: str = "Look up real-time order status, items, and payment info by order ID."

    def _run(self, order_id: str) -> str:
        order = self.client.get_order(order_id)
        return order.model_dump_json(indent=2)


class MetricQueryTool(AgentFlowTool):
    name: str = "agentflow_metric"
    description: str = (
        "Query business metrics: revenue, order_count, avg_order_value, conversion_rate, "
        "active_sessions, error_rate. Specify metric name and optional time window "
        "(1h, 24h, 7d)."
    )

    def _run(self, metric: str, window: str = "1h") -> str:
        result = self.client.get_metric(metric, window)
        return f"{metric} ({window}): {result.value} {result.unit}"


class NLQueryTool(AgentFlowTool):
    name: str = "agentflow_query"
    description: str = (
        "Ask a natural language question about business data. Returns SQL result as JSON."
    )

    def _run(self, question: str) -> str:
        result = self.client.query(question)
        return result.model_dump_json()
