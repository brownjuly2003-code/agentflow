import {
  AgentFlowError,
  AuthError,
  DataFreshnessError,
  EntityNotFoundError,
  RateLimitError,
} from "./exceptions.js";
import type {
  BatchItem,
  BatchResponse,
  CatalogResponse,
  ContractResponse,
  EntityEnvelope,
  EventFilters,
  FetchLike,
  HealthStatus,
  MetricName,
  MetricResult,
  OrderEntity,
  PipelineEvent,
  ProductEntity,
  QueryResult,
  SessionEntity,
  TimeWindow,
  UserEntity,
} from "./models.js";
import { CircuitBreaker } from "./circuitBreaker.js";
import {
  RETRYABLE_STATUS,
  RetryPolicy,
  isRetryableMethod,
} from "./retry.js";
import { streamSseJson } from "./stream.js";

const ENTITY_NUMBER_FIELDS: Record<string, string[]> = {
  order: ["total_amount"],
  user: ["total_orders", "total_spent"],
  product: ["price", "stock_quantity"],
  session: ["duration_seconds", "event_count", "unique_pages"],
};

export class AgentFlowClient {
  private readonly baseUrl: string;
  private readonly apiKey: string;
  private readonly fetchImpl: FetchLike;
  private readonly timeoutMs: number;
  private readonly headers: HeadersInit | undefined;
  private readonly contractVersions: Record<string, string>;
  private readonly contractCache = new Map<string, ContractResponse>();
  public retryPolicy: RetryPolicy;
  public circuitBreaker: CircuitBreaker;

  constructor(
    baseUrl: string,
    apiKey: string,
    options: {
      fetch?: FetchLike;
      timeoutMs?: number;
      headers?: HeadersInit;
      contractVersion?: string;
    } = {},
  ) {
    const legacyOptions = options as typeof options & {
      retryPolicy?: RetryPolicy;
      circuitBreaker?: CircuitBreaker;
    };
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    this.apiKey = apiKey;
    this.fetchImpl = options.fetch ?? this.resolveFetch();
    this.timeoutMs = options.timeoutMs ?? 10_000;
    this.headers = options.headers;
    this.contractVersions = this.parseContractVersions(options.contractVersion);
    this.retryPolicy = legacyOptions.retryPolicy ?? new RetryPolicy();
    this.circuitBreaker = legacyOptions.circuitBreaker ?? new CircuitBreaker();
  }

  configureResilience(options: {
    retryPolicy?: RetryPolicy;
    circuitBreaker?: CircuitBreaker;
  }): this {
    if (options.retryPolicy) {
      this.retryPolicy = options.retryPolicy;
    }
    if (options.circuitBreaker) {
      this.circuitBreaker = options.circuitBreaker;
    }
    return this;
  }

  async getOrder(orderId: string): Promise<OrderEntity> {
    return this.getEntity<OrderEntity>("order", orderId);
  }

  async getUser(userId: string): Promise<UserEntity> {
    return this.getEntity<UserEntity>("user", userId);
  }

  async getProduct(productId: string): Promise<ProductEntity> {
    return this.getEntity<ProductEntity>("product", productId);
  }

  async getSession(sessionId: string): Promise<SessionEntity> {
    return this.getEntity<SessionEntity>("session", sessionId);
  }

  async getMetric(
    name: MetricName | string,
    window = "1h" as TimeWindow | string,
  ): Promise<MetricResult> {
    const payload = await this.requestJson<MetricResult>(
      "GET",
      `/v1/metrics/${encodeURIComponent(name)}`,
      { params: { window } },
    );
    return {
      ...payload,
      value: this.toNumber(payload.value),
      components: payload.components ?? null,
    };
  }

  async query(question: string): Promise<QueryResult> {
    const payload = await this.requestJson<QueryResult>("POST", "/v1/query", {
      json: { question },
    });
    return {
      ...payload,
      metadata: this.normalizeQueryMetadata(payload.metadata ?? {}),
    };
  }

  async health(): Promise<HealthStatus> {
    const payload = await this.requestJson<Omit<HealthStatus, "freshness_seconds">>(
      "GET",
      "/v1/health",
    );
    return {
      ...payload,
      freshness_seconds: this.extractFreshnessSeconds(payload.components),
    };
  }

  async isFresh(maxAgeSeconds = 60): Promise<boolean> {
    const health = await this.health();
    if (health.status !== "healthy") {
      throw new DataFreshnessError(
        `Pipeline is ${health.status}; freshness check cannot be trusted`,
      );
    }
    if (health.freshness_seconds == null) {
      throw new DataFreshnessError("Pipeline freshness metric is unavailable");
    }
    return health.freshness_seconds < maxAgeSeconds;
  }

  async catalog(): Promise<CatalogResponse> {
    return this.requestJson<CatalogResponse>("GET", "/v1/catalog");
  }

  streamEvents(filters: EventFilters = {}): AsyncGenerator<PipelineEvent> {
    const self = this;
    return (async function* () {
      const response = await self.fetchResponse("GET", "/v1/stream/events", {
        params: {
          event_type: filters.eventType,
          entity_id: filters.entityId,
        },
        accept: "text/event-stream",
        signal: filters.signal,
      });
      yield* streamSseJson<PipelineEvent>(response, filters.signal);
    })();
  }

  async batch(requests: BatchItem[]): Promise<BatchResponse> {
    return this.requestJson<BatchResponse>("POST", "/v1/batch", {
      json: { requests },
    });
  }

  batchEntity(
    entityType: string,
    entityId: string,
    requestId?: string,
  ): BatchItem {
    return {
      id: requestId ?? this.requestId("entity"),
      type: "entity",
      params: {
        entity_type: entityType,
        entity_id: entityId,
      },
    };
  }

  batchMetric(
    name: MetricName | string,
    window = "1h" as TimeWindow | string,
    requestId?: string,
  ): BatchItem {
    return {
      id: requestId ?? this.requestId("metric"),
      type: "metric",
      params: { name, window },
    };
  }

  batchQuery(
    question: string,
    context?: Record<string, unknown>,
    requestId?: string,
  ): BatchItem {
    return {
      id: requestId ?? this.requestId("query"),
      type: "query",
      params: context == null ? { question } : { question, context },
    };
  }

  private resolveFetch(): FetchLike {
    if (typeof fetch !== "function") {
      throw new AgentFlowError(
        "Global fetch is unavailable. Pass options.fetch when constructing AgentFlowClient.",
      );
    }
    return fetch.bind(globalThis);
  }

  private parseContractVersions(
    contractVersion?: string,
  ): Record<string, string> {
    if (!contractVersion) {
      return {};
    }

    const [entity, rawVersion] = contractVersion.split(":", 2);
    if (!entity || !rawVersion) {
      throw new Error("contractVersion must use '<entity>:<version>' format.");
    }

    return {
      [entity]: rawVersion.startsWith("v") ? rawVersion.slice(1) : rawVersion,
    };
  }

  private async getEntity<T extends object>(
    entityType: string,
    entityId: string,
  ): Promise<T> {
    const envelope = await this.requestJson<EntityEnvelope<Record<string, unknown>>>(
      "GET",
      `/v1/entity/${encodeURIComponent(entityType)}/${encodeURIComponent(entityId)}`,
    );
    const versioned = await this.applyContractVersion(entityType, envelope.data);
    return this.normalizeEntity(entityType, versioned) as T;
  }

  private async applyContractVersion<T extends Record<string, unknown>>(
    entityType: string,
    payload: T,
  ): Promise<T> {
    const version = this.contractVersions[entityType];
    if (!version) {
      return payload;
    }

    const contract = await this.getContract(entityType, version);
    const requiredFields = contract.fields
      .filter((field) => field.required)
      .map((field) => field.name);
    const missingFields = requiredFields.filter((field) => !(field in payload));

    if (missingFields.length > 0) {
      throw new AgentFlowError(
        "Contract validation failed. Missing required fields: "
          + missingFields.join(", "),
      );
    }

    const allowedFields = new Set(contract.fields.map((field) => field.name));
    const filteredEntries = Object.entries(payload).filter(([key]) =>
      allowedFields.has(key),
    );
    return Object.fromEntries(filteredEntries) as T;
  }

  private async getContract(
    entityType: string,
    version: string,
  ): Promise<ContractResponse> {
    const cacheKey = `${entityType}:${version}`;
    const cached = this.contractCache.get(cacheKey);
    if (cached) {
      return cached;
    }

    const contract = await this.requestJson<ContractResponse>(
      "GET",
      `/v1/contracts/${encodeURIComponent(entityType)}/${encodeURIComponent(version)}`,
    );
    this.contractCache.set(cacheKey, contract);
    return contract;
  }

  private async requestJson<T>(
    method: string,
    path: string,
    options: {
      params?: Record<string, string | number | boolean | undefined>;
      json?: Record<string, unknown>;
      signal?: AbortSignal;
    } = {},
  ): Promise<T> {
    const response = await this.fetchResponse(method, path, options);
    const payload = await this.readJson(response);
    return payload as T;
  }

  private async fetchResponse(
    method: string,
    path: string,
    options: {
      params?: Record<string, string | number | boolean | undefined>;
      json?: Record<string, unknown>;
      signal?: AbortSignal;
      accept?: string;
    } = {},
  ): Promise<Response> {
    const url = new URL(`${this.baseUrl}${path}`);
    for (const [key, value] of Object.entries(options.params ?? {})) {
      if (value != null) {
        url.searchParams.set(key, String(value));
      }
    }
    const headers = {
      Accept: options.accept ?? "application/json",
      "X-API-Key": this.apiKey,
      ...(options.json ? { "Content-Type": "application/json" } : {}),
      ...this.objectHeaders(this.headers),
    };
    const canRetry = isRetryableMethod(method, headers);
    let attempt = 0;

    this.circuitBreaker.beforeCall();

    while (true) {
      const controller = new AbortController();
      const onAbort = () => controller.abort();
      options.signal?.addEventListener("abort", onAbort, { once: true });
      const timeoutId =
        this.timeoutMs > 0
          ? setTimeout(() => controller.abort(), this.timeoutMs)
          : undefined;

      try {
        const response = await this.fetchImpl(url.toString(), {
          method,
          headers,
          body: options.json ? JSON.stringify(options.json) : undefined,
          signal: controller.signal,
        });
        const retryAfterHeader = response.headers.get("retry-after");
        const retryAfterSeconds = retryAfterHeader == null
          ? undefined
          : Number(retryAfterHeader);

        if (
          canRetry
          && RETRYABLE_STATUS.has(response.status)
          && attempt < this.retryPolicy.maxAttempts - 1
        ) {
          const delayMs = this.retryPolicy.computeDelay(
            attempt,
            Number.isFinite(retryAfterSeconds) ? retryAfterSeconds! * 1_000 : undefined,
          );
          attempt += 1;
          await new Promise((resolve) => setTimeout(resolve, delayMs));
          continue;
        }

        if (response.status >= 500) {
          this.circuitBreaker.recordFailure();
        } else {
          this.circuitBreaker.recordSuccess();
        }

        if (!response.ok) {
          await this.throwHttpError(response, path);
        }

        return response;
      } catch (error) {
        if (
          error instanceof AgentFlowError
          || error instanceof AuthError
          || error instanceof RateLimitError
          || error instanceof EntityNotFoundError
        ) {
          throw error;
        }

        const timedOut = controller.signal.aborted && !options.signal?.aborted;
        const userAborted = controller.signal.aborted && !!options.signal?.aborted;

        if (!userAborted && canRetry && attempt < this.retryPolicy.maxAttempts - 1) {
          const delayMs = this.retryPolicy.computeDelay(attempt);
          attempt += 1;
          await new Promise((resolve) => setTimeout(resolve, delayMs));
          continue;
        }

        if (!userAborted) {
          this.circuitBreaker.recordFailure();
        }

        const message = timedOut
          ? `Request timed out after ${this.timeoutMs}ms`
          : error instanceof Error
            ? error.message
            : "Unknown request error";
        throw new AgentFlowError(`Request failed: ${message}`);
      } finally {
        if (timeoutId !== undefined) {
          clearTimeout(timeoutId);
        }
        options.signal?.removeEventListener("abort", onAbort);
      }
    }
  }

  private async throwHttpError(response: Response, path: string): Promise<never> {
    const payload = await this.readJson(response, true);
    const detail = this.errorDetail(payload, response);

    if (response.status === 401) {
      throw new AuthError(detail ?? "Unauthorized");
    }

    if (response.status === 429) {
      const retryAfterHeader = response.headers.get("retry-after");
      const retryAfter = retryAfterHeader ? Number(retryAfterHeader) : 0;
      throw new RateLimitError(detail ?? "Rate limit exceeded", retryAfter || 0);
    }

    if (response.status === 404) {
      const parts = path.split("/").filter(Boolean);
      if (parts.length >= 4 && parts[1] === "entity") {
        throw new EntityNotFoundError(parts[2]!, parts[3]!, detail ?? undefined);
      }
    }

    throw new AgentFlowError(detail ?? response.statusText, response.status);
  }

  private async readJson(
    response: Response,
    allowEmpty = false,
  ): Promise<Record<string, unknown>> {
    const contentType = response.headers.get("content-type") ?? "";
    if (!contentType.includes("application/json")) {
      if (allowEmpty) {
        return {};
      }
      throw new AgentFlowError(
        `Expected JSON response but received '${contentType || "unknown"}'`,
      );
    }

    const payload = (await response.json()) as unknown;
    if (payload && typeof payload === "object") {
      return payload as Record<string, unknown>;
    }
    if (allowEmpty) {
      return {};
    }
    throw new AgentFlowError("Response payload is not an object");
  }

  private errorDetail(
    payload: Record<string, unknown>,
    response: Response,
  ): string | undefined {
    const detail = payload.detail;
    if (typeof detail === "string") {
      return detail;
    }
    return response.statusText || undefined;
  }

  private extractFreshnessSeconds(
    components: Array<{ name: string; metrics: Record<string, unknown> }>,
  ): number | null {
    for (const component of components) {
      if (component.name === "freshness") {
        const value = component.metrics.last_event_age_seconds;
        return typeof value === "number" ? value : value == null ? null : Number(value);
      }
    }
    return null;
  }

  private normalizeEntity(
    entityType: string,
    entity: Record<string, unknown>,
  ): Record<string, unknown> {
    const normalized = { ...entity };
    for (const field of ENTITY_NUMBER_FIELDS[entityType] ?? []) {
      if (field in normalized) {
        normalized[field] = this.toNullableNumber(normalized[field]);
      }
    }
    return normalized;
  }

  private normalizeQueryMetadata(
    metadata: Record<string, unknown>,
  ): Record<string, unknown> {
    const normalized = { ...metadata };
    for (const field of [
      "rows_returned",
      "execution_time_ms",
      "data_freshness_seconds",
    ]) {
      if (field in normalized) {
        normalized[field] = this.toNullableNumber(normalized[field]);
      }
    }
    return normalized;
  }

  private toNumber(value: unknown): number {
    return typeof value === "number" ? value : Number(value);
  }

  private toNullableNumber(value: unknown): number | null {
    if (value == null) {
      return null;
    }
    return this.toNumber(value);
  }

  private objectHeaders(headers?: HeadersInit): Record<string, string> {
    if (!headers) {
      return {};
    }
    if (headers instanceof Headers) {
      return Object.fromEntries(headers.entries());
    }
    if (Array.isArray(headers)) {
      return Object.fromEntries(headers);
    }
    return headers;
  }

  private requestId(prefix: "entity" | "metric" | "query"): string {
    const token = globalThis.crypto?.randomUUID?.().replace(/-/g, "").slice(0, 8)
      ?? Math.random().toString(16).slice(2, 10);
    return `${prefix}-${token}`;
  }
}
