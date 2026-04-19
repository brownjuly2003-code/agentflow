import type { CircuitBreaker } from "./circuitBreaker.js";
import type { RetryPolicy } from "./retry.js";

export type FetchLike = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

export interface ClientOptions {
  fetch?: FetchLike;
  timeoutMs?: number;
  headers?: HeadersInit;
  contractVersion?: string;
  retryPolicy?: RetryPolicy;
  circuitBreaker?: CircuitBreaker;
}

export type MetricName =
  | "revenue"
  | "order_count"
  | "avg_order_value"
  | "conversion_rate"
  | "active_sessions"
  | "error_rate";

export type TimeWindow = "5m" | "15m" | "1h" | "6h" | "24h" | "7d" | "now";

export interface EntityEnvelope<TData extends Record<string, unknown>> {
  entity_type: string;
  entity_id: string;
  data: TData;
  last_updated: string | null;
  freshness_seconds: number | null;
  meta?: Record<string, unknown>;
}

export interface OrderEntity {
  order_id: string;
  user_id: string;
  status: string;
  total_amount: number;
  currency: string;
  created_at: string;
  is_overdue?: boolean;
}

export interface UserEntity {
  user_id: string;
  total_orders: number;
  total_spent: number;
  first_order_at: string;
  last_order_at: string;
  preferred_category: string;
}

export interface ProductEntity {
  product_id: string;
  name: string;
  category: string;
  price: number;
  in_stock: boolean;
  stock_quantity: number;
}

export interface SessionEntity {
  session_id: string;
  user_id: string | null;
  started_at: string;
  ended_at: string | null;
  duration_seconds: number | null;
  event_count: number;
  unique_pages: number;
  funnel_stage: string;
  is_conversion: boolean;
}

export interface MetricResult {
  metric_name: string;
  value: number;
  unit: string;
  window: string;
  computed_at: string;
  components: Record<string, unknown> | null;
  meta?: Record<string, unknown>;
}

export interface QueryMetadata {
  rows_returned?: number;
  execution_time_ms?: number;
  data_freshness_seconds?: number | null;
  [key: string]: unknown;
}

export interface QueryResult {
  answer: Record<string, unknown> | Array<Record<string, unknown>>;
  sql: string | null;
  metadata: QueryMetadata;
}

export interface HealthComponent {
  name: string;
  status: string;
  message: string;
  metrics: Record<string, unknown>;
  source: string;
}

export interface HealthStatus {
  status: string;
  checked_at: string;
  components: HealthComponent[];
  freshness_seconds: number | null;
}

export interface CatalogEntity {
  description: string;
  fields: Record<string, string>;
  primary_key: string;
  contract_version?: string | null;
}

export interface CatalogMetric {
  description: string;
  unit: string;
  available_windows: string[];
  contract_version?: string | null;
}

export interface StreamingSource {
  path: string;
  transport: string;
  description: string;
  filters?: Record<string, unknown>;
}

export interface AuditSource {
  path: string;
  description: string;
  layers?: string[];
}

export interface CatalogResponse {
  entities: Record<string, CatalogEntity>;
  metrics: Record<string, CatalogMetric>;
  streaming_sources?: Record<string, StreamingSource>;
  audit_sources?: Record<string, AuditSource>;
}

export interface BatchItem {
  id: string;
  type: "entity" | "metric" | "query";
  params: Record<string, unknown>;
}

export interface BatchResult {
  id: string;
  status: "ok" | "error";
  data?: Record<string, unknown>;
  error?: string;
}

export interface BatchResponse {
  results: BatchResult[];
  duration_ms: number;
}

export interface EventFilters {
  eventType?: string;
  entityId?: string;
  signal?: AbortSignal;
}

export interface PipelineEvent {
  event_id: string;
  topic?: string | null;
  processed_at?: string | null;
  event_type?: string | null;
  entity_id?: string | null;
  latency_ms?: number | null;
  [key: string]: unknown;
}

export interface ContractField {
  name: string;
  required?: boolean;
}

export interface ContractResponse {
  entity: string;
  version: string;
  fields: ContractField[];
}
