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


class CatalogMetric(AgentFlowModel):
    description: str
    unit: str
    available_windows: list[str]


class CatalogResponse(AgentFlowModel):
    entities: dict[str, CatalogEntity]
    metrics: dict[str, CatalogMetric]
