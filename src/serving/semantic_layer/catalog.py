"""Data catalog — the semantic layer that gives meaning to raw tables.

Defines entities, metrics, and relationships so that AI agents can discover
what data is available and how to query it, without knowing table schemas.
"""

from dataclasses import dataclass, field


@dataclass
class EntityDefinition:
    name: str
    description: str
    table: str
    primary_key: str
    fields: dict[str, str]  # field_name -> description
    relationships: dict[str, str] = field(default_factory=dict)


@dataclass
class MetricDefinition:
    name: str
    description: str
    sql_template: str
    unit: str
    available_windows: list[str] = field(default_factory=lambda: ["5m", "15m", "1h", "6h", "24h"])


class DataCatalog:
    """Registry of all data assets available to agents."""

    def __init__(self):
        self.entities: dict[str, EntityDefinition] = {}
        self.metrics: dict[str, MetricDefinition] = {}
        self._register_defaults()

    def _register_defaults(self):
        self.register_entity(EntityDefinition(
            name="order",
            description="Customer orders with status and total",
            table="orders_v2",
            primary_key="order_id",
            fields={
                "order_id": "Unique order identifier (ORD-YYYYMMDD-NNNN)",
                "user_id": "Customer identifier",
                "status": "Current status: pending, confirmed, shipped, delivered, cancelled",
                "total_amount": "Order total in USD",
                "currency": "Currency code (USD, EUR, GBP)",
                "created_at": "Order creation timestamp",
            },
            relationships={"user": "user_id"},
        ))

        self.register_entity(EntityDefinition(
            name="user",
            description="Customer profile with order history summary",
            table="users_enriched",
            primary_key="user_id",
            fields={
                "user_id": "Unique user identifier",
                "total_orders": "Lifetime order count",
                "total_spent": "Lifetime spend in USD",
                "first_order_at": "First order timestamp",
                "last_order_at": "Most recent order timestamp",
                "preferred_category": "Most frequently ordered category",
            },
            relationships={"orders": "user_id", "sessions": "user_id"},
        ))

        self.register_entity(EntityDefinition(
            name="product",
            description="Product catalog with current pricing and stock",
            table="products_current",
            primary_key="product_id",
            fields={
                "product_id": "Unique product identifier",
                "name": "Product display name",
                "category": "Product category",
                "price": "Current price in USD",
                "in_stock": "Whether the product is currently available",
                "stock_quantity": "Current inventory count",
            },
        ))

        self.register_entity(EntityDefinition(
            name="session",
            description="User browsing sessions with funnel stage",
            table="sessions_aggregated",
            primary_key="session_id",
            fields={
                "session_id": "Unique session identifier",
                "user_id": "User identifier (null for anonymous)",
                "started_at": "Session start time",
                "ended_at": "Session end time",
                "duration_seconds": "Session duration",
                "event_count": "Number of events in session",
                "unique_pages": "Distinct pages visited",
                "funnel_stage": "Deepest stage: bounce/browse/product_view/add_to_cart/checkout",
                "is_conversion": "Whether the session resulted in a checkout",
            },
            relationships={"user": "user_id"},
        ))

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
        ))

    def register_entity(self, entity: EntityDefinition):
        self.entities[entity.name] = entity

    def register_metric(self, metric: MetricDefinition):
        self.metrics[metric.name] = metric
