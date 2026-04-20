from agentflow import AgentFlowClient
from langchain.tools import BaseTool

from agentflow_integrations.langchain.tool import (
    MetricQueryTool,
    NLQueryTool,
    OrderLookupTool,
)


class AgentFlowToolkit:
    def __init__(self, base_url: str, api_key: str):
        self.client = AgentFlowClient(base_url, api_key)

    def get_tools(self) -> list[BaseTool]:
        return [
            OrderLookupTool(client=self.client),
            MetricQueryTool(client=self.client),
            NLQueryTool(client=self.client),
        ]
