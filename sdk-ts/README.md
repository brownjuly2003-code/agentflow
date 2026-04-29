# @uedomskikh/agentflow-client

> npm package name: **`@uedomskikh/agentflow-client`**. Registry publishing is not
> complete as of 2026-04-29; until the first green `Publish TypeScript SDK`
> run, use the local workspace build (`npm install` in `sdk-ts`, then import
> the built `dist/` from a relative path or via npm link).

After registry publish:

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
