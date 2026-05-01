# agentflow-client

> PyPI distribution name: **`agentflow-client`**. The package is published as
> `agentflow-client` 1.1.0 on PyPI. Python import remains `agentflow`.

Install from PyPI:

```bash
pip install agentflow-client
```

Inside the monorepo, the root runtime package is tracked separately as
`agentflow-runtime`, while the SDK keeps the `agentflow` import path and CLI.

For a local editable install while developing from this repository:

```bash
python -m pip install -e "./sdk"
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

The SDK exposes typed methods for v1 read, query, discovery, contract,
lineage, changelog, and batch routes. Admin and operational surfaces are
intentionally not wrapped as public typed methods: `/v1/admin/*`,
`/v1/webhooks`, `/v1/alerts`, `/v1/deadletter`, `/v1/slo`, and
`/v1/stream/events`.
