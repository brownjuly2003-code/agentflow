# @uedomskikh/agentflow-client

> Published npm package: **`@uedomskikh/agentflow-client`**.

Install:

```bash
npm install @uedomskikh/agentflow-client
```

```ts
import { AgentFlowClient } from "@uedomskikh/agentflow-client";
const client = new AgentFlowClient("http://localhost:8000", "dev-key");
const order = await client.getOrder("ORD-20260404-1001");
console.log(order.status, (await client.getMetric("revenue", "24h")).value);
```

```ts
import {
  AgentFlowClient,
  RetryPolicy,
} from "@uedomskikh/agentflow-client";

const client = new AgentFlowClient("http://localhost:8000", "dev-key");
client.configureResilience({
  retryPolicy: new RetryPolicy({ maxAttempts: 5 }),
});
```
