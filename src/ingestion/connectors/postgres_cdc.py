"""PostgreSQL CDC connector configuration for Debezium.

Captures change events from the product catalog and user tables
via logical replication, routing them to Kafka topics.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class DebeziumConnectorConfig:
    """Generates Kafka Connect configuration for Debezium PostgreSQL source."""

    name: str
    database_hostname: str
    database_port: int
    database_user: str
    database_dbname: str
    table_include_list: str
    topic_prefix: str
    slot_name: str

    def to_connect_config(self) -> dict:
        return {
            "name": self.name,
            "config": {
                "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
                "database.hostname": self.database_hostname,
                "database.port": str(self.database_port),
                "database.user": self.database_user,
                "database.dbname": self.database_dbname,
                "table.include.list": self.table_include_list,
                "topic.prefix": self.topic_prefix,
                "slot.name": self.slot_name,
                "plugin.name": "pgoutput",
                "publication.autocreate.mode": "filtered",
                # Exactly-once delivery
                "provide.transaction.metadata": "true",
                "signal.data.collection": f"{self.database_dbname}.public.debezium_signal",
                # Schema handling
                "key.converter": "org.apache.kafka.connect.json.JsonConverter",
                "value.converter": "org.apache.kafka.connect.json.JsonConverter",
                "key.converter.schemas.enable": "false",
                "value.converter.schemas.enable": "true",
                # Snapshot
                "snapshot.mode": "initial",
                # Heartbeat to keep replication slot active
                "heartbeat.interval.ms": "30000",
                # Transforms: route to canonical topic names
                "transforms": "route",
                "transforms.route.type": "org.apache.kafka.connect.transforms.RegexRouter",
                "transforms.route.regex": f"{self.topic_prefix}\\.public\\.(.*)",
                "transforms.route.replacement": "$1.cdc",
            },
        }


# Pre-configured connectors for the platform
PRODUCT_CATALOG_CDC = DebeziumConnectorConfig(
    name="product-catalog-cdc",
    database_hostname="postgres",
    database_port=5432,
    database_user="cdc_reader",
    database_dbname="ecommerce",
    table_include_list="public.products,public.categories",
    topic_prefix="ecommerce",
    slot_name="product_catalog_slot",
)

USER_PROFILES_CDC = DebeziumConnectorConfig(
    name="user-profiles-cdc",
    database_hostname="postgres",
    database_port=5432,
    database_user="cdc_reader",
    database_dbname="ecommerce",
    table_include_list="public.users,public.user_preferences",
    topic_prefix="ecommerce",
    slot_name="user_profiles_slot",
)
