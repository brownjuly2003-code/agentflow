# agentflow-client

```bash
pip install -e sdk/
```

```python
from agentflow import AgentFlowClient
client = AgentFlowClient("http://localhost:8000", api_key="dev-key")
order = client.get_order("ORD-20260404-1001")
print(order.status, client.get_metric("revenue", "24h").value)
```

```python
from agentflow import AgentFlowClient
from agentflow.retry import RetryPolicy

client = AgentFlowClient("http://localhost:8000", api_key="dev-key")
client.configure_resilience(retry_policy=RetryPolicy(max_attempts=5))
```

```python
from agentflow import AsyncAgentFlowClient

async def main() -> None:
    async with AsyncAgentFlowClient("http://localhost:8000", api_key="dev-key") as client:
        order = await client.get_order("ORD-20260404-1001")
        metric = await client.get_metric("revenue", "24h")
        print(order.status, metric.value)
```
