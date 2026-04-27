from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AgentFlowModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class EntityEnvelope(AgentFlowModel):
    entity_type: str
    entity_id: str
    data: dict[str, Any]
    last_updated: datetime | None = None
    freshness_seconds: float | None = None
    meta: "EntityMeta | None" = None


class EntityMeta(AgentFlowModel):
    as_of: str | None = None
    is_historical: bool = False
    freshness_seconds: float | None = None


class OrderEntity(AgentFlowModel):
    order_id: str
    user_id: str
    status: str
    total_amount: float
    currency: str
    created_at: datetime
    is_overdue: bool = False

    @model_validator(mode="after")
    def compute_is_overdue(self):
        created_at = self.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        self.is_overdue = (
            self.status not in {"delivered", "cancelled"}
            and created_at <= datetime.now(UTC) - timedelta(hours=24)
        )
        return self


class UserEntity(AgentFlowModel):
    user_id: str
    total_orders: int
    total_spent: float
    first_order_at: datetime
    last_order_at: datetime
    preferred_category: str


class ProductEntity(AgentFlowModel):
    product_id: str
    name: str
    category: str
    price: float
    in_stock: bool
    stock_quantity: int


class SessionEntity(AgentFlowModel):
    session_id: str
    user_id: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    duration_seconds: float | None = None
    event_count: int
    unique_pages: int
    funnel_stage: str
    is_conversion: bool


class MetricResult(AgentFlowModel):
    metric_name: str
    value: float
    unit: str
    window: str
    computed_at: datetime
    components: dict[str, Any] | None = None
    meta: "MetricMeta | None" = None


class MetricMeta(AgentFlowModel):
    as_of: str | None = None
    is_historical: bool = False
    freshness_seconds: float | None = None


class QueryResult(AgentFlowModel):
    answer: dict[str, Any] | list[dict[str, Any]]
    sql: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class HealthComponent(AgentFlowModel):
    name: str
    status: str
    message: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    source: str


class HealthStatus(AgentFlowModel):
    status: str
    checked_at: datetime
    components: list[HealthComponent]
    freshness_seconds: float | None = None

    @model_validator(mode="after")
    def compute_freshness_seconds(self):
        for component in self.components:
            if component.name == "freshness":
                last_event_age = component.metrics.get("last_event_age_seconds")
                self.freshness_seconds = (
                    float(last_event_age) if last_event_age is not None else None
                )
                break
        return self


class CatalogEntity(AgentFlowModel):
    description: str
    fields: dict[str, str]
    primary_key: str
    contract_version: str | None = None


class CatalogMetric(AgentFlowModel):
    description: str
    unit: str
    available_windows: list[str]
    contract_version: str | None = None


class CatalogStreamingSource(AgentFlowModel):
    path: str
    transport: str
    description: str
    filters: dict[str, Any] = Field(default_factory=dict)


class CatalogAuditSource(AgentFlowModel):
    path: str
    description: str
    layers: list[str] = Field(default_factory=list)


class CatalogResponse(AgentFlowModel):
    entities: dict[str, CatalogEntity]
    metrics: dict[str, CatalogMetric]
    streaming_sources: dict[str, CatalogStreamingSource] = Field(default_factory=dict)
    audit_sources: dict[str, CatalogAuditSource] = Field(default_factory=dict)


class QueryExplanation(AgentFlowModel):
    question: str
    sql: str
    tables_accessed: list[str]
    estimated_rows: int | None = None
    engine: str
    warning: str | None = None


class SearchResult(AgentFlowModel):
    type: str
    id: str
    entity_type: str | None = None
    score: float
    snippet: str
    endpoint: str


class SearchResults(AgentFlowModel):
    query: str
    results: list[SearchResult]


class ContractField(AgentFlowModel):
    name: str
    type: str
    required: bool
    description: str | None = None
    values: list[str] | None = None
    unit: str | None = None


class ContractSummary(AgentFlowModel):
    entity: str
    version: str
    released: str
    status: str


class EntityContract(AgentFlowModel):
    entity: str
    version: str
    released: str
    status: str
    fields: list[ContractField]
    breaking_changes: list[dict[str, Any]] = Field(default_factory=list)


class ContractDiff(AgentFlowModel):
    entity: str
    from_version: str
    to_version: str
    breaking_changes: list[dict[str, Any]] = Field(default_factory=list)
    additive_changes: list[dict[str, Any]] = Field(default_factory=list)


class ContractValidation(AgentFlowModel):
    entity: str
    base_version: str
    candidate_version: str
    breaking_changes: list[dict[str, Any]] = Field(default_factory=list)
    safe_changes: list[dict[str, Any]] = Field(default_factory=list)
    is_breaking: bool
    requires_version_bump: bool


class LineageNode(AgentFlowModel):
    layer: str
    system: str
    table_or_topic: str
    processed_at: datetime | None = None
    quality_score: float | None = None


class Lineage(AgentFlowModel):
    entity_type: str
    entity_id: str
    lineage: list[LineageNode]
    freshness_seconds: float
    validated: bool
    enriched: bool


class ChangelogVersion(AgentFlowModel):
    date: str
    status: str
    changes: list[str]


class Changelog(AgentFlowModel):
    latest_version: str
    versions: list[ChangelogVersion]
