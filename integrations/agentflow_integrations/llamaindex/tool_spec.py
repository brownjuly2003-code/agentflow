from typing import Any

from agentflow import AgentFlowClient
from llama_index.core.tools.tool_spec.base import BaseToolSpec


class AgentFlowToolSpec(BaseToolSpec):
    spec_functions = ["get_order", "get_metric", "query"]

    def __init__(self, base_url: str, api_key: str):
        self.client = AgentFlowClient(base_url, api_key)

    def get_order(self, order_id: str) -> dict[str, Any]:
        return self.client.get_order(order_id).model_dump(mode="json")

    def get_metric(self, metric: str, window: str = "1h") -> dict[str, Any]:
        return self.client.get_metric(metric, window).model_dump(mode="json")

    def query(self, question: str) -> dict[str, Any] | list[dict[str, Any]]:
        return self.client.query(question).answer
