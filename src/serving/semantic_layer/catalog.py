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


class DataCatalog:
    """Registry of all data assets available to agents."""

    def __init__(self, contract_registry: ContractRegistry | None = None):
        self.entities: dict[str, EntityDefinition] = {}
        self.metrics: dict[str, MetricDefinition] = {}
        self.contract_registry = contract_registry or ContractRegistry()
        self._register_defaults()

    def _register_defaults(self):
        for entity in load_entity_contracts():
            entity.contract_version = self.contract_registry.latest_contract_version(
                entity.name
            )
            self.register_entity(entity)

        # Metrics
        self.register_metric(MetricDefinition(
            name="revenue",
            description="Total revenue from completed orders",
            sql_template=(
                "SELECT SUM(total_amount) as value "
                "FROM orders_v2 "
                "WHERE status != 'cancelled' "
                "AND created_at >= NOW() - INTERVAL '{window}'"
            ),
            unit="USD",
            contract_version=self.contract_registry.latest_contract_version("metric.revenue"),
        ))

        self.register_metric(MetricDefinition(
            name="order_count",
            description="Number of orders placed",
            sql_template=(
                "SELECT COUNT(*) as value "
                "FROM orders_v2 "
                "WHERE created_at >= NOW() - INTERVAL '{window}'"
            ),
            unit="count",
            contract_version=self.contract_registry.latest_contract_version("metric.order_count"),
        ))

        self.register_metric(MetricDefinition(
            name="avg_order_value",
            description="Average order value",
            sql_template=(
                "SELECT AVG(total_amount) as value "
                "FROM orders_v2 "
                "WHERE status != 'cancelled' "
                "AND created_at >= NOW() - INTERVAL '{window}'"
            ),
            unit="USD",
            contract_version=self.contract_registry.latest_contract_version("metric.avg_order_value"),
        ))

        self.register_metric(MetricDefinition(
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
            contract_version=self.contract_registry.latest_contract_version("metric.conversion_rate"),
        ))

        self.register_metric(MetricDefinition(
            name="active_sessions",
            description="Currently active user sessions",
            sql_template=(
                "SELECT COUNT(*) as value "
                "FROM sessions_aggregated "
                "WHERE ended_at IS NULL "
                "OR ended_at >= NOW() - INTERVAL '30 minutes'"
            ),
            unit="count",
            available_windows=["now"],
            contract_version=self.contract_registry.latest_contract_version("metric.active_sessions"),
        ))

        self.register_metric(MetricDefinition(
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
            contract_version=self.contract_registry.latest_contract_version("metric.error_rate"),
        ))

    def register_entity(self, entity: EntityDefinition):
        self.entities[entity.name] = entity

    def register_metric(self, metric: MetricDefinition):
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
            }
            for name, metric in self.metrics.items()
        }
