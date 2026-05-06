# SDKs

AgentFlow publishes typed clients for Python and TypeScript. Both clients target
the same v1 HTTP surface for health, catalog, entity lookup, metrics, natural
language query, and batch calls.

## Python SDK

Install the published package:

```bash
pip install agentflow-client
```

Install from this repository while developing:

```bash
python -m pip install -e "./sdk"
```

Use the sync client:

```python
from agentflow import AgentFlowClient

client = AgentFlowClient("http://localhost:8000", api_key="demo-key")
order = client.get_order("ORD-20260404-1001")
metric = client.get_metric("revenue", "24h")

print(order.status)
print(metric.value)
```

Use the async client:

```python
from agentflow import AsyncAgentFlowClient


async def main() -> None:
    async with AsyncAgentFlowClient(
        "http://localhost:8000",
        api_key="demo-key",
    ) as client:
        order = await client.get_order("ORD-20260404-1001")
        print(order.status)
```

## TypeScript SDK

Install the published package:

```bash
npm install @yuliaedomskikh/agentflow-client
```

Use the client:

```typescript
import { AgentFlowClient } from "@yuliaedomskikh/agentflow-client";

const client = new AgentFlowClient("http://localhost:8000", "demo-key");
const order = await client.getOrder("ORD-20260404-1001");
const metric = await client.getMetric("revenue", "24h");

console.log(order.status);
console.log(metric.value);
```

## Resilience hooks

Both SDKs include retry and circuit-breaker primitives so well-behaved clients
can reduce repeated calls during degraded service windows.

=== "Python"

    ```python
    from agentflow import AgentFlowClient
    from agentflow.retry import RetryPolicy

    client = AgentFlowClient("http://localhost:8000", api_key="demo-key")
    client.configure_resilience(retry_policy=RetryPolicy(max_attempts=5))
    ```

=== "TypeScript"

    ```typescript
    import {
      AgentFlowClient,
      RetryPolicy,
    } from "@yuliaedomskikh/agentflow-client";

    const client = new AgentFlowClient("http://localhost:8000", "demo-key");
    client.configureResilience({
      retryPolicy: new RetryPolicy({ maxAttempts: 5 }),
    });
    ```

## Coverage notes

First-class SDK helpers cover the core agent read/query flow. Admin,
dead-letter, alert, webhook, and some governance workflows are available over
HTTP and can be called with `httpx`, `fetch`, or another HTTP client when an
integration needs them.
