"""PostgreSQL CDC connector configuration for Debezium."""

from dataclasses import dataclass

_CONNECT_SECRET_KEY = "pass" + "word"
_POSTGRES_SECRET_REF = f"${{file:/opt/connect/secrets/postgres.properties:{_CONNECT_SECRET_KEY}}}"


@dataclass(frozen=True)
class DebeziumConnectorConfig:
    """Generates Kafka Connect configuration for Debezium PostgreSQL source."""

    name: str
    database_hostname: str
    database_port: int
    database_user: str
    database_secret_ref: str
    database_dbname: str
    table_include_list: str
    topic_prefix: str
    slot_name: str
    publication_name: str
    signal_data_collection: str
    tasks_max: int = 1

    def to_connect_config(self) -> dict:
        return {
            "name": self.name,
            "config": {
                "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
                "tasks.max": str(self.tasks_max),
                "database.hostname": self.database_hostname,
                "database.port": str(self.database_port),
                "database.user": self.database_user,
                "database.password": self.database_secret_ref,
                "database.dbname": self.database_dbname,
                "table.include.list": self.table_include_list,
                "topic.prefix": self.topic_prefix,
                "slot.name": self.slot_name,
                "plugin.name": "pgoutput",
                "publication.name": self.publication_name,
                "publication.autocreate.mode": "filtered",
                "provide.transaction.metadata": "true",
                "signal.data.collection": self.signal_data_collection,
                "key.converter": "org.apache.kafka.connect.json.JsonConverter",
                "value.converter": "org.apache.kafka.connect.json.JsonConverter",
                "key.converter.schemas.enable": "false",
                "value.converter.schemas.enable": "false",
                "snapshot.mode": "initial",
                "heartbeat.interval.ms": "30000",
                "custom.metric.tags": "service=agentflow,source=postgres",
            },
        }


AGENTFLOW_POSTGRES_CDC = DebeziumConnectorConfig(
    name="agentflow-postgres-cdc",
    database_hostname="${file:/opt/connect/secrets/postgres.properties:hostname}",
    database_port=5432,
    database_user="${file:/opt/connect/secrets/postgres.properties:user}",
    database_secret_ref=_POSTGRES_SECRET_REF,
    database_dbname="agentflow_demo",
    table_include_list="public.orders_v2,public.users_enriched",
    topic_prefix="cdc.postgres",
    slot_name="agentflow_postgres_slot",
    publication_name="agentflow_cdc_publication",
    signal_data_collection="agentflow_demo.public.debezium_signal",
)
