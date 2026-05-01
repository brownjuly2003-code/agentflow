# @yuliaedomskikh/agentflow-client

> Published npm package: **`@yuliaedomskikh/agentflow-client`**.

Install:

```bash
npm install @yuliaedomskikh/agentflow-client
```

```ts
import { AgentFlowClient } from "@yuliaedomskikh/agentflow-client";
const client = new AgentFlowClient("http://localhost:8000", "dev-key");
const order = await client.getOrder("ORD-20260404-1001");
console.log(order.status, (await client.getMetric("revenue", "24h")).value);
```

```ts
import {
  AgentFlowClient,
  RetryPolicy,
} from "@yuliaedomskikh/agentflow-client";

const client = new AgentFlowClient("http://localhost:8000", "dev-key");
client.configureResilience({
  retryPolicy: new RetryPolicy({ maxAttempts: 5 }),
});
```
