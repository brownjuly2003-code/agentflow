# SDKs

Use an AgentFlow typed client after completing the
[quickstart](quickstart.md). This walkthrough runs the same entity read in
Python and TypeScript; the linked references own exact methods, advanced
configuration, and HTTP contracts.

## Choose a client

| Language | Package | Detailed owner |
| --- | --- | --- |
| Python | `agentflow-client` | [Python package reference](https://github.com/brownjuly2003-code/agentflow/blob/main/sdk/README.md) |
| TypeScript | `@yuliaedomskikh/agentflow-client` | [TypeScript package reference](https://github.com/brownjuly2003-code/agentflow/blob/main/sdk-ts/README.md) |

The package references own constructor options, async usage, resilience
configuration, and language-specific examples.

## Try the same read flow

=== "Python"

    ```bash
    pip install agentflow-client
    ```

    ```python
    from agentflow import AgentFlowClient

    client = AgentFlowClient("http://localhost:8000", api_key="demo-key")
    order = client.get_order("ORD-20260404-1001")
    print(order.status)
    ```

=== "TypeScript"

    ```bash
    npm install @yuliaedomskikh/agentflow-client
    ```

    ```typescript
    import { AgentFlowClient } from "@yuliaedomskikh/agentflow-client";

    const client = new AgentFlowClient("http://localhost:8000", "demo-key");
    const order = await client.getOrder("ORD-20260404-1001");
    console.log(order.status);
    ```

## Find the exact contract

- Use the [generated capability contract](sdk-capabilities.md) to check whether
  both clients expose a typed method.
- Use the [full API reference](api-reference.md) for authentication, parameters,
  response shapes, errors, and surfaces that require a general HTTP client.
