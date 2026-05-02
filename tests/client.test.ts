import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AgentFlowClient,
  AgentFlowError,
  AuthError,
  CircuitBreaker,
  CircuitOpenError,
  CircuitState,
  DataFreshnessError,
  EntityNotFoundError,
  PermissionDeniedError,
  RateLimitError,
  RetryPolicy,
} from "../sdk-ts/index.ts";

function jsonResponse(
  status: number,
  payload: unknown,
  headers?: Record<string, string>,
): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "content-type": "application/json",
      ...headers,
    },
  });
}

function sseResponse(frames: string[]): Response {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream({
      start(controller) {
        for (const frame of frames) {
          controller.enqueue(encoder.encode(frame));
        }
        controller.close();
      },
    }),
    {
      status: 200,
      headers: { "content-type": "text/event-stream" },
    },
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AgentFlowClient", () => {
  it("gets an order entity", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      expect(String(input)).toBe("https://api.example.test/v1/entity/order/ORD-1");
      return jsonResponse(200, {
        entity_type: "order",
        entity_id: "ORD-1",
        data: {
          order_id: "ORD-1",
          user_id: "USR-1",
          status: "pending",
          total_amount: "19.99",
          currency: "USD",
          created_at: "2026-04-11T10:00:00Z",
        },
        last_updated: null,
        freshness_seconds: 12,
        meta: { is_historical: false },
      });
    });
    const client = new AgentFlowClient("https://api.example.test", "test-key", {
      fetch: fetchMock,
    });

    const order = await client.getOrder("ORD-1");

    expect(order.order_id).toBe("ORD-1");
    expect(order.total_amount).toBe(19.99);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["getUser", "user", "USR-1", { user_id: "USR-1", total_orders: 3, total_spent: "45.50", first_order_at: "2026-04-01T00:00:00Z", last_order_at: "2026-04-10T00:00:00Z", preferred_category: "books" }],
    ["getProduct", "product", "PROD-1", { product_id: "PROD-1", name: "Headphones", category: "audio", price: "99.99", in_stock: true, stock_quantity: 7 }],
    ["getSession", "session", "SES-1", { session_id: "SES-1", user_id: null, started_at: "2026-04-11T09:00:00Z", ended_at: null, duration_seconds: null, event_count: 4, unique_pages: 3, funnel_stage: "browse", is_conversion: false }],
  ])("gets %s entity", async (methodName, entityType, entityId, data) => {
    const fetchMock = vi.fn(async () =>
      jsonResponse(200, {
        entity_type: entityType,
        entity_id: entityId,
        data,
        last_updated: null,
        freshness_seconds: null,
        meta: {},
      }),
    );
    const client = new AgentFlowClient("https://api.example.test", "test-key", {
      fetch: fetchMock,
    });

    const entity = await client[methodName as "getUser" | "getProduct" | "getSession"](
      entityId,
    );

    expect((entity as Record<string, unknown>)[`${entityType}_id`]).toBe(entityId);
  });

  it("gets a metric with a custom window", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      expect(String(input)).toBe(
        "https://api.example.test/v1/metrics/revenue?window=24h",
      );
      return jsonResponse(200, {
        metric_name: "revenue",
        value: 125.5,
        unit: "USD",
        window: "24h",
        computed_at: "2026-04-11T10:00:00Z",
        components: { gross: 150 },
        meta: {},
      });
    });
    const client = new AgentFlowClient("https://api.example.test", "test-key", {
      fetch: fetchMock,
    });

    const metric = await client.getMetric("revenue", "24h");

    expect(metric.metric_name).toBe("revenue");
    expect(metric.window).toBe("24h");
  });

  it("posts natural-language queries", async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      expect(init?.method).toBe("POST");
      expect(init?.body).toBe(JSON.stringify({ question: "top products" }));
      return jsonResponse(200, {
        answer: [{ product_id: "PROD-1", revenue: 150 }],
        sql: "SELECT * FROM products",
        metadata: { rows_returned: 1, execution_time_ms: 8 },
      });
    });
    const client = new AgentFlowClient("https://api.example.test", "test-key", {
      fetch: fetchMock,
    });

    const result = await client.query("top products");

    expect(result.sql).toBe("SELECT * FROM products");
    expect(result.metadata.rows_returned).toBe(1);
  });

  it("returns catalog data", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse(200, {
        entities: {
          order: {
            description: "Orders",
            fields: { order_id: "ID" },
            primary_key: "order_id",
            contract_version: "2",
          },
        },
        metrics: {
          revenue: {
            description: "Revenue",
            unit: "USD",
            available_windows: ["1h", "24h"],
            contract_version: "1",
          },
        },
        streaming_sources: {
          events: {
            path: "/v1/stream/events",
            transport: "sse",
            description: "Real-time stream",
            filters: { event_type: ["order"], entity_id: "id" },
          },
        },
      }),
    );
    const client = new AgentFlowClient("https://api.example.test", "test-key", {
      fetch: fetchMock,
    });

    const catalog = await client.catalog();

    expect(catalog.entities.order.primary_key).toBe("order_id");
    expect(catalog.streaming_sources?.events.transport).toBe("sse");
  });

  it("reports freshness from health", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse(200, {
        status: "healthy",
        checked_at: "2026-04-11T10:00:00Z",
        components: [
          {
            name: "freshness",
            status: "healthy",
            message: "fresh",
            metrics: { last_event_age_seconds: 15, sla_seconds: 30 },
            source: "live",
          },
        ],
      }),
    );
    const client = new AgentFlowClient("https://api.example.test", "test-key", {
      fetch: fetchMock,
    });

    const fresh = await client.isFresh(60);

    expect(fresh).toBe(true);
  });

  it("throws DataFreshnessError when pipeline is not healthy", async () => {
    const client = new AgentFlowClient("https://api.example.test", "test-key", {
      fetch: vi.fn(async () =>
        jsonResponse(200, {
          status: "degraded",
          checked_at: "2026-04-11T10:00:00Z",
          components: [],
        }),
      ),
    });

    await expect(client.isFresh(60)).rejects.toBeInstanceOf(DataFreshnessError);
  });

  it("builds batch payloads and sends them to /v1/batch", async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      expect(init?.method).toBe("POST");
      expect(init?.body).toContain("\"requests\"");
      return jsonResponse(200, {
        results: [
          { id: "entity-1", status: "ok", data: { order_id: "ORD-1" } },
          { id: "metric-1", status: "ok", data: { metric_name: "revenue" } },
        ],
        duration_ms: 12,
      });
    });
    const client = new AgentFlowClient("https://api.example.test", "test-key", {
      fetch: fetchMock,
    });

    const result = await client.batch([
      client.batchEntity("order", "ORD-1", "entity-1"),
      client.batchMetric("revenue", "1h", "metric-1"),
    ]);

    expect(result.results).toHaveLength(2);
    expect(result.results[0]?.id).toBe("entity-1");
  });

  it("raises AuthError for 401 responses", async () => {
    const client = new AgentFlowClient("https://api.example.test", "bad-key", {
      fetch: vi.fn(async () => jsonResponse(401, { detail: "Invalid API key" })),
    });

    await expect(client.health()).rejects.toBeInstanceOf(AuthError);
  });

  it("raises PermissionDeniedError for 403 responses", async () => {
    const client = new AgentFlowClient("https://api.example.test", "test-key", {
      fetch: vi.fn(async () => jsonResponse(403, { detail: "Forbidden" })),
    });

    await expect(client.health()).rejects.toBeInstanceOf(PermissionDeniedError);
  });

  it("raises RateLimitError with retryAfter for 429 responses", async () => {
    const client = new AgentFlowClient("https://api.example.test", "test-key", {
      fetch: vi.fn(async () =>
        jsonResponse(
          429,
          { detail: "Rate limit exceeded" },
          { "retry-after": "60" },
        ),
      ),
      retryPolicy: new RetryPolicy({ maxAttempts: 1, jitterFactor: 0 }),
    });

    await expect(client.health()).rejects.toMatchObject({
      retryAfter: 60,
    });
    await expect(client.health()).rejects.toBeInstanceOf(RateLimitError);
  });

  it("raises EntityNotFoundError for missing entities", async () => {
    const client = new AgentFlowClient("https://api.example.test", "test-key", {
      fetch: vi.fn(async () =>
        jsonResponse(404, { detail: "order/ORD-404 not found" }),
      ),
    });

    await expect(client.getOrder("ORD-404")).rejects.toBeInstanceOf(
      EntityNotFoundError,
    );
  });

  it("wraps transport failures in AgentFlowError", async () => {
    const client = new AgentFlowClient("https://api.example.test", "test-key", {
      fetch: vi.fn(async () => {
        throw new Error("boom");
      }),
    });

    await expect(client.health()).rejects.toBeInstanceOf(AgentFlowError);
  });

  it("streams SSE events as an async generator", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      expect(String(input)).toBe(
        "https://api.example.test/v1/stream/events?event_type=order&entity_id=ORD-1",
      );
      return sseResponse([
        ": keepalive\n\n",
        "data: {\"event_id\":\"evt-1\",\"event_type\":\"order.created\",\"entity_id\":\"ORD-1\"}\n\n",
      ]);
    });
    const client = new AgentFlowClient("https://api.example.test", "test-key", {
      fetch: fetchMock,
    });

    const stream = client.streamEvents({ eventType: "order", entityId: "ORD-1" });
    const first = await stream.next();

    expect(first.value?.event_id).toBe("evt-1");
    expect(first.done).toBe(false);
  });
});

describe("RetryPolicy", () => {
  it("computes exponential backoff", () => {
    const policy = new RetryPolicy({
      maxAttempts: 5,
      initialDelayMs: 100,
      jitterFactor: 0,
    });

    expect(policy.computeDelay(0)).toBe(100);
    expect(policy.computeDelay(1)).toBe(200);
    expect(policy.computeDelay(2)).toBe(400);
  });

  it("respects retry-after delay", () => {
    const policy = new RetryPolicy();

    expect(policy.computeDelay(0, 3_000)).toBe(3_000);
  });

  it("caps at max delay", () => {
    const policy = new RetryPolicy({
      initialDelayMs: 100,
      maxDelayMs: 1_000,
      jitterFactor: 0,
    });

    expect(policy.computeDelay(10)).toBe(1_000);
  });
});

describe("CircuitBreaker", () => {
  it("opens after reaching failure threshold", () => {
    const breaker = new CircuitBreaker({ failureThreshold: 3 });

    breaker.recordFailure();
    breaker.recordFailure();
    breaker.recordFailure();

    expect(breaker.state).toBe(CircuitState.OPEN);
    expect(() => breaker.beforeCall()).toThrow(CircuitOpenError);
  });

  it("moves to half-open after timeout", () => {
    let now = 1_000;
    vi.spyOn(Date, "now").mockImplementation(() => now);
    const breaker = new CircuitBreaker({
      failureThreshold: 1,
      resetTimeoutMs: 100,
    });

    breaker.recordFailure();
    now += 150;
    breaker.beforeCall();

    expect(breaker.state).toBe(CircuitState.HALF_OPEN);
  });

  it("closes after a successful half-open probe", () => {
    let now = 1_000;
    vi.spyOn(Date, "now").mockImplementation(() => now);
    const breaker = new CircuitBreaker({
      failureThreshold: 1,
      resetTimeoutMs: 100,
    });

    breaker.recordFailure();
    now += 150;
    breaker.beforeCall();
    breaker.recordSuccess();

    expect(breaker.state).toBe(CircuitState.CLOSED);
  });

  it("reopens after a failed half-open probe", () => {
    let now = 1_000;
    vi.spyOn(Date, "now").mockImplementation(() => now);
    const breaker = new CircuitBreaker({
      failureThreshold: 1,
      resetTimeoutMs: 100,
    });

    breaker.recordFailure();
    now += 150;
    breaker.beforeCall();
    breaker.recordFailure();

    expect(breaker.state).toBe(CircuitState.OPEN);
  });

  it("allows only one half-open probe", () => {
    let now = 1_000;
    vi.spyOn(Date, "now").mockImplementation(() => now);
    const breaker = new CircuitBreaker({
      failureThreshold: 1,
      resetTimeoutMs: 100,
      halfOpenMaxCalls: 1,
    });

    breaker.recordFailure();
    now += 150;
    breaker.beforeCall();

    expect(() => breaker.beforeCall()).toThrow(CircuitOpenError);
  });
});

describe("AgentFlowClient resilience", () => {
  it("retries idempotent GET requests on 503", async () => {
    const fetchMock = vi.fn(async () => {
      if (fetchMock.mock.calls.length < 3) {
        return jsonResponse(503, { detail: "temporarily unavailable" });
      }
      return jsonResponse(200, {
        status: "healthy",
        checked_at: "2026-04-17T10:00:00Z",
        components: [],
      });
    });
    const client = new AgentFlowClient("https://api.example.test", "test-key", {
      fetch: fetchMock,
      retryPolicy: new RetryPolicy({
        maxAttempts: 3,
        initialDelayMs: 0,
        jitterFactor: 0,
      }),
    });

    const health = await client.health();

    expect(health.status).toBe("healthy");
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("does not retry POST requests by default", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse(503, { detail: "temporarily unavailable" }),
    );
    const client = new AgentFlowClient("https://api.example.test", "test-key", {
      fetch: fetchMock,
      retryPolicy: new RetryPolicy({
        maxAttempts: 3,
        initialDelayMs: 0,
        jitterFactor: 0,
      }),
    });

    await expect(
      client.batch([client.batchEntity("order", "ORD-1", "entity-1")]),
    ).rejects.toBeInstanceOf(AgentFlowError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("opens the circuit after repeated backend failures", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse(503, { detail: "temporarily unavailable" }),
    );
    const client = new AgentFlowClient("https://api.example.test", "test-key", {
      fetch: fetchMock,
      retryPolicy: new RetryPolicy({
        maxAttempts: 1,
        initialDelayMs: 0,
        jitterFactor: 0,
      }),
      circuitBreaker: new CircuitBreaker({
        failureThreshold: 2,
        resetTimeoutMs: 1_000,
      }),
    });

    await expect(client.health()).rejects.toBeInstanceOf(AgentFlowError);
    await expect(client.health()).rejects.toBeInstanceOf(AgentFlowError);
    await expect(client.health()).rejects.toBeInstanceOf(CircuitOpenError);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
