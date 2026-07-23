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

export interface RequestOptions {
  signal?: AbortSignal;
}

export interface EntityReadOptions extends RequestOptions {
  asOf?: Date | string;
}

export interface MetricReadOptions extends EntityReadOptions {}

export interface QueryOptions extends RequestOptions {
  limit?: number;
  cursor?: string;
  idempotencyKey?: string;
}

export interface PaginationOptions extends RequestOptions {
  pageSize?: number;
}

export interface ExplainQueryOptions extends RequestOptions {
  contractVersion?: string;
}

export interface SearchOptions extends RequestOptions {
  limit?: number;
  entityTypes?: string[];
}

export interface IdempotentRequestOptions extends RequestOptions {
  idempotencyKey?: string;
}

export type MetricName =
  | "revenue"
  | "order_count"
  | "avg_order_value"
  | "conversion_rate"
  | "active_sessions"
  | "error_rate";

export type TimeWindow = "5m" | "15m" | "1h" | "6h" | "24h" | "7d" | "now";

export interface EntityEnvelope<TData extends object> {
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
  type?: string;
  required: boolean;
  description?: string | null;
  values?: string[] | null;
  unit?: string | null;
}

export interface ContractResponse {
  entity: string;
  version: string;
  released?: string;
  status?: string;
  fields: ContractField[];
  breaking_changes?: Array<Record<string, unknown>>;
}

export interface QueryExplanation {
  question: string;
  sql: string;
  tables_accessed: string[];
  estimated_rows?: number | null;
  engine: string;
  warning?: string | null;
}

export interface SearchResult {
  type: "entity" | "metric" | "catalog_field";
  id: string;
  entity_type: string | null;
  score: number;
  snippet: string;
  endpoint: string;
}

export interface SearchResults {
  query: string;
  results: SearchResult[];
}

export interface ContractSummary {
  entity: string;
  version: string;
  released: string;
  status: string;
}

export interface ContractDiff {
  entity: string;
  from_version: string;
  to_version: string;
  breaking_changes: Array<Record<string, unknown>>;
  additive_changes: Array<Record<string, unknown>>;
}

export interface ContractValidation {
  entity: string;
  base_version: string;
  candidate_version: string;
  breaking_changes?: Array<Record<string, unknown>>;
  safe_changes?: Array<Record<string, unknown>>;
  is_breaking: boolean;
  requires_version_bump: boolean;
}

export interface LineageNode {
  layer: string;
  system: string;
  table_or_topic: string;
  processed_at?: string | null;
  quality_score?: number | null;
}

export interface Lineage {
  entity_type: string;
  entity_id: string;
  lineage: LineageNode[];
  freshness_seconds: number;
  validated: boolean;
  enriched: boolean;
}

export interface ChangelogVersion {
  date: string;
  status: string;
  changes: string[];
}

export interface Changelog {
  latest_version: string;
  versions: ChangelogVersion[];
}
