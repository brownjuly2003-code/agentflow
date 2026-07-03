"""Data catalog — the semantic layer that gives meaning to raw tables.

Defines entities, metrics, and relationships so that AI agents can discover
what data is available and how to query it, without knowing table schemas.
"""

from dataclasses import dataclass, field

from src.serving.semantic_layer.contract_registry import ContractRegistry
from src.serving.semantic_layer.entity_type_registry import load_entity_contracts


@dataclass
class EntityDefinition:
    name: str
    description: str
    table: str
    primary_key: str
    fields: dict[str, str]  # field_name -> description
    relationships: dict[str, str] = field(default_factory=dict)
    contract_version: str | None = None


@dataclass
class MetricDefinition:
    name: str
    description: str
    sql_template: str
    unit: str
    available_windows: list[str] = field(default_factory=lambda: ["5m", "15m", "1h", "6h", "24h"])
    contract_version: str | None = None
    # Event->metric lineage: which pipeline event types move this metric and
    # through which serving table. Mirrors the write path in
    # src/processing/local_pipeline._process_event (orders_v2 <- order.*,
    # sessions_aggregated <- clickstream, pipeline_events <- every event);
    # tests/unit/test_catalog_lineage.py pins the mapping against the code.
    source_events: list[str] = field(default_factory=list)
    source_table: str | None = None


class DataCatalog:
    """Registry of all data assets available to agents."""

    def __init__(self, contract_registry: ContractRegistry | None = None):
        self.entities: dict[str, EntityDefinition] = {}
        self.metrics: dict[str, MetricDefinition] = {}
        self.contract_registry = contract_registry or ContractRegistry()
        self._register_defaults()

    def _register_defaults(self) -> None:
        for entity in load_entity_contracts():
            entity.contract_version = self.contract_registry.latest_contract_version(entity.name)
            self.register_entity(entity)

        # Metrics
        self.register_metric(
            MetricDefinition(
                name="revenue",
                description="Total revenue from non-cancelled orders",
                sql_template=(
                    "SELECT SUM(total_amount) as value "
                    "FROM orders_v2 "
                    "WHERE status != 'cancelled' "
                    "AND created_at >= NOW() - INTERVAL '{window}'"
                ),
                unit="RUB",
                contract_version=self.contract_registry.latest_contract_version("metric.revenue"),
                source_events=["order.created", "order.updated", "order.cancelled"],
                source_table="orders_v2",
            )
        )

        self.register_metric(
            MetricDefinition(
                name="order_count",
                description="Number of non-cancelled orders",
                sql_template=(
                    # status filter aligned with revenue / avg_order_value so the
                    # three metrics are mutually consistent (avg = revenue/count);
                    # previously order_count counted cancelled orders too, so the
                    # identity did not hold. (audit_28_06_26.md #M4)
                    "SELECT COUNT(*) as value "
                    "FROM orders_v2 "
                    "WHERE status != 'cancelled' "
                    "AND created_at >= NOW() - INTERVAL '{window}'"
                ),
                unit="count",
                contract_version=self.contract_registry.latest_contract_version(
                    "metric.order_count"
                ),
                source_events=["order.created", "order.updated", "order.cancelled"],
                source_table="orders_v2",
            )
        )

        self.register_metric(
            MetricDefinition(
                name="avg_order_value",
                description="Average order value",
                sql_template=(
                    "SELECT AVG(total_amount) as value "
                    "FROM orders_v2 "
                    "WHERE status != 'cancelled' "
                    "AND created_at >= NOW() - INTERVAL '{window}'"
                ),
                unit="RUB",
                contract_version=self.contract_registry.latest_contract_version(
                    "metric.avg_order_value"
                ),
                source_events=["order.created", "order.updated", "order.cancelled"],
                source_table="orders_v2",
            )
        )

        self.register_metric(
            MetricDefinition(
                name="conversion_rate",
                description="Ratio of sessions that reached checkout",
                sql_template=(
                    "SELECT "
                    "CAST(SUM(CASE WHEN is_conversion THEN 1 ELSE 0 END) AS FLOAT) "
                    "/ NULLIF(COUNT(*), 0) as value "
                    "FROM sessions_aggregated "
                    "WHERE started_at >= NOW() - INTERVAL '{window}'"
                ),
                unit="ratio",
                contract_version=self.contract_registry.latest_contract_version(
                    "metric.conversion_rate"
                ),
                source_events=["click", "page_view", "add_to_cart"],
                source_table="sessions_aggregated",
            )
        )

        self.register_metric(
            MetricDefinition(
                name="active_sessions",
                description="Active user sessions (started in last 30 min, not ended)",
                sql_template=(
                    # Sessions that started recently and have not ended. The old
                    # 'ended_at IS NULL OR ended_at >= ...' counted every session
                    # ever, because the demo write path never sets ended_at, so
                    # 'ended_at IS NULL' was always true. Anchor on started_at so
                    # the count is actually time-bounded. (audit_28_06_26.md #11)
                    "SELECT COUNT(*) as value "
                    "FROM sessions_aggregated "
                    "WHERE started_at >= NOW() - INTERVAL '30 minutes' "
                    "AND ended_at IS NULL"
                ),
                unit="count",
                available_windows=["now"],
                contract_version=self.contract_registry.latest_contract_version(
                    "metric.active_sessions"
                ),
                source_events=["click", "page_view", "add_to_cart"],
                source_table="sessions_aggregated",
            )
        )

        self.register_metric(
            MetricDefinition(
                name="error_rate",
                description="Ratio of failed events in the pipeline",
                sql_template=(
                    "SELECT "
                    "CAST(COUNT(*) FILTER (WHERE topic = 'events.deadletter') AS FLOAT) "
                    "/ NULLIF(COUNT(*), 0) as value "
                    "FROM pipeline_events "
                    "WHERE processed_at >= NOW() - INTERVAL '{window}'"
                ),
                unit="ratio",
                contract_version=self.contract_registry.latest_contract_version(
                    "metric.error_rate"
                ),
                # Every pipeline event lands in pipeline_events (validated or
                # deadletter), so every event type moves this metric.
                source_events=[
                    "order.created",
                    "order.updated",
                    "order.cancelled",
                    "payment.initiated",
                    "payment.completed",
                    "payment.failed",
                    "click",
                    "page_view",
                    "add_to_cart",
                    "product.updated",
                ],
                source_table="pipeline_events",
            )
        )

    def register_entity(self, entity: EntityDefinition) -> None:
        self.entities[entity.name] = entity

    def register_metric(self, metric: MetricDefinition) -> None:
        self.metrics[metric.name] = metric

    def serialize_entities(self) -> dict[str, dict]:
        return {
            name: {
                "description": entity.description,
                "fields": entity.fields,
                "primary_key": entity.primary_key,
                "contract_version": entity.contract_version,
            }
            for name, entity in self.entities.items()
        }

    def serialize_metrics(self) -> dict[str, dict]:
        return {
            name: {
                "description": metric.description,
                "unit": metric.unit,
                "available_windows": metric.available_windows,
                "contract_version": metric.contract_version,
                "source_events": metric.source_events,
                "source_table": metric.source_table,
            }
            for name, metric in self.metrics.items()
        }
