import { describe, expect, it, vi } from "vitest";

import {
  AgentFlowClient,
  CircuitBreaker,
  CircuitOpenError,
  RetryPolicy,
} from "../index.ts";

function jsonResponse(
  status: number,
  payload: unknown,
): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "content-type": "application/json",
    },
  });
}

describe("AgentFlowClient configureResilience", () => {
  it("returns self and updates resilience policies", () => {
    const client = new AgentFlowClient("https://api.example.test", "test-key", {
      fetch: vi.fn(),
    });
    const retryPolicy = new RetryPolicy({ maxAttempts: 2, jitterFactor: 0 });
    const circuitBreaker = new CircuitBreaker({ failureThreshold: 2 });

    const result = client.configureResilience({ retryPolicy, circuitBreaker });

    expect(result).toBe(client);
    expect(client.retryPolicy).toBe(retryPolicy);
    expect(client.circuitBreaker).toBe(circuitBreaker);
  });

  it("applies default resilience configuration", () => {
    const client = new AgentFlowClient("https://api.example.test", "test-key", {
      fetch: vi.fn(),
    });

    expect(client.retryPolicy).toBeInstanceOf(RetryPolicy);
    expect(client.circuitBreaker).toBeInstanceOf(CircuitBreaker);
  });

  it("blocks requests once the circuit is open", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse(503, { detail: "temporarily unavailable" }),
    );
    const client = new AgentFlowClient("https://api.example.test", "test-key", {
      fetch: fetchMock,
    }).configureResilience({
      retryPolicy: new RetryPolicy({
        maxAttempts: 1,
        initialDelayMs: 0,
        jitterFactor: 0,
      }),
      circuitBreaker: new CircuitBreaker({
        failureThreshold: 1,
        resetTimeoutMs: 999_000,
      }),
    });

    await expect(client.health()).rejects.toThrow();
    await expect(client.health()).rejects.toBeInstanceOf(CircuitOpenError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
