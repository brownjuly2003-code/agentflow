import { describe, expect, it, vi } from "vitest";

import { AgentFlowClient } from "../index.ts";

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

describe("README quickstart example", () => {
  it("fetches an order and metric with an injected fetch", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "http://localhost:8000/v1/entity/order/ORD-20260404-1001") {
        return jsonResponse(200, {
          entity_type: "order",
          entity_id: "ORD-20260404-1001",
          data: {
            order_id: "ORD-20260404-1001",
            user_id: "USR-10001",
            status: "paid",
            total_amount: "42.50",
            currency: "USD",
            created_at: "2026-04-11T10:00:00Z",
          },
          last_updated: null,
          freshness_seconds: 4,
          meta: {},
        });
      }
      if (url === "http://localhost:8000/v1/metrics/revenue?window=24h") {
        return jsonResponse(200, {
          metric_name: "revenue",
          value: "42.50",
          unit: "USD",
          window: "24h",
          computed_at: "2026-04-11T10:00:00Z",
          components: null,
          meta: {},
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    const client = new AgentFlowClient("http://localhost:8000", "dev-key", {
      fetch: fetchMock,
    });

    const order = await client.getOrder("ORD-20260404-1001");
    const revenue = await client.getMetric("revenue", "24h");

    expect(order.status).toBe("paid");
    expect(order.total_amount).toBe(42.5);
    expect(revenue.value).toBe(42.5);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
