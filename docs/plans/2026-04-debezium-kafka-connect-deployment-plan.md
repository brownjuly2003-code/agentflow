# A04 Debezium + Kafka Connect Deployment Plan

**Status:** Draft for T25b implementation  
**Date:** 2026-04-25  
**Scope:** Research and deploy plan only; no implementation in this task.

Kafka Connect is the runtime that hosts source and sink connectors as workers. In this plan, Debezium PostgreSQL and MySQL source connectors run inside Kafka Connect workers, read database replication logs, and publish raw CDC records to Kafka. AgentFlow then treats those raw Debezium records as an internal capture format and normalizes them before Flink validation, Iceberg writes, and serving-layer reads.

## 1. Scope decision

**Decision:** implement a Kafka Connect distributed worker cluster, with one worker for local dev and two workers for staging/prod-like Kubernetes.

- Local dev uses the same distributed-mode worker config as staging, but `replicaCount=1` in `docker-compose.cdc.yml`.
- Staging/prod-like Kubernetes uses `replicaCount=2` for worker failover. Debezium PostgreSQL and MySQL connectors still run with `tasks.max=1`, because each source connector owns a single ordered replication stream; HA comes from task reassignment after worker failure, not from parallel tasks for one source.
- Kafka Connect internal topics are owned by the Connect cluster:
  - `connect-agentflow-configs`: `cleanup.policy=compact`, partitions `1`.
  - `connect-agentflow-offsets`: `cleanup.policy=compact`, partitions `25`.
  - `connect-agentflow-status`: `cleanup.policy=compact`, partitions `5`.
  - Replication factor is `1` in local compose and `3` in staging/prod-like clusters.

**Debezium version:** use Debezium `3.5.0.Final` for both PostgreSQL and MySQL connectors. Debezium 3.5 is the latest stable series as of 2026-04-25, supports Kafka Connect 3.1+, and lists PostgreSQL 14-17 plus MySQL 8.0/8.4/9.0/9.1 as tested database versions. The repo already runs Confluent Platform `7.7.0`; T25b should build an AgentFlow Kafka Connect image from `confluentinc/cp-kafka-connect-base:7.7.0` and install Debezium `3.5.0.Final` plugin archives into `/usr/share/java/debezium`.

Do not use `quay.io/debezium/connect` for production. It is acceptable for a throwaway local smoke, but the plan standardizes on a repo-owned image because Debezium documents its container images as testing/evaluation assets, not production-hardened images.

**Connector classes:**

- PostgreSQL: `io.debezium.connector.postgresql.PostgresConnector`
- MySQL: `io.debezium.connector.mysql.MySqlConnector`

**Serialization / schema registry decision:** do not require Schema Registry in T25b. Use Kafka Connect `org.apache.kafka.connect.json.JsonConverter` for keys and values, with `schemas.enable=false`, so the new CDC path remains compatible with the current `SimpleStringSchema` Flink input and JSON-based local pipeline. Confluent Schema Registry already exists in `docker-compose.prod.yml`, but Avro/Protobuf/JSON Schema converters are deferred until the team decides to enforce schemas on raw CDC topics. Canonical AgentFlow CDC validation remains in the normalizer and `scripts/check_schema_evolution.py`, not in raw Debezium topics.

## 2. Source systems

**Decision:** T25b attaches only demo/staging source databases. Production source attachment is out of scope until the user confirms real database hosts, network access, and credential ownership.

### Local source instances

`docker-compose.cdc.yml` should add two source databases:

- `postgres-source`: `postgres:16`, database `agentflow_demo`, user `cdc_reader`, logical replication enabled with `wal_level=logical`, `max_replication_slots=4`, `max_wal_senders=4`.
- `mysql-source`: `mysql:8.4`, database `agentflow_demo`, CDC enabled with `server-id=223344`, `log_bin=mysql-bin`, `binlog_format=ROW`, `binlog_row_image=FULL`, `binlog_expire_logs_seconds=864000`.

### Kubernetes staging source instances

For kind staging, T25b should deploy ephemeral Postgres/MySQL source instances in the same namespace as Kafka Connect, seeded with the same schemas below. This keeps staging validation reproducible without requiring access to production data.

### Tables and schemas

The demo schema mirrors `src/processing/local_pipeline.py` and the current seeded DuckDB files.

PostgreSQL `agentflow_demo.public`:

| Table | Columns | CDC mapping |
| --- | --- | --- |
| `orders_v2` | `order_id VARCHAR PRIMARY KEY`, `user_id VARCHAR`, `status VARCHAR`, `total_amount DECIMAL(10,2)`, `currency VARCHAR DEFAULT 'USD'`, `created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP` | `entity_type=order`, key `order_id`, events `order.snapshot/created/updated/deleted` |
| `users_enriched` | `user_id VARCHAR PRIMARY KEY`, `total_orders INTEGER DEFAULT 0`, `total_spent DECIMAL(10,2) DEFAULT 0`, `first_order_at TIMESTAMP`, `last_order_at TIMESTAMP`, `preferred_category VARCHAR` | `entity_type=user`, key `user_id`, events `user.snapshot/updated/deleted` |
| `debezium_signal` | `id VARCHAR PRIMARY KEY`, `type VARCHAR NOT NULL`, `data JSONB` | Debezium incremental snapshot and signal table; not routed to downstream entities |

MySQL `agentflow_demo`:

| Table | Columns | CDC mapping |
| --- | --- | --- |
| `products_current` | `product_id VARCHAR(64) PRIMARY KEY`, `name VARCHAR(255)`, `category VARCHAR(128)`, `price DECIMAL(10,2)`, `in_stock BOOLEAN DEFAULT TRUE`, `stock_quantity INT DEFAULT 0` | `entity_type=product`, key `product_id`, events `product.snapshot/updated/deleted` |
| `sessions_aggregated` | `session_id VARCHAR(64) PRIMARY KEY`, `user_id VARCHAR(64)`, `started_at DATETIME`, `ended_at DATETIME NULL`, `duration_seconds FLOAT`, `event_count INT`, `unique_pages INT`, `funnel_stage VARCHAR(64)`, `is_conversion BOOLEAN DEFAULT FALSE` | `entity_type=session`, key `session_id`, events `session.snapshot/updated/deleted` |

## 3. Topic naming

**Convention:** `cdc.<source>.<schema>.<table>`.

Use Debezium default table topic naming by setting stable `topic.prefix` values:

- PostgreSQL `topic.prefix=cdc.postgres`, producing topics such as `cdc.postgres.public.orders_v2`.
- MySQL `topic.prefix=cdc.mysql`, producing topics such as `cdc.mysql.agentflow_demo.products_current`.

Do not keep the current placeholder `RegexRouter` behavior from `src/ingestion/connectors/postgres_cdc.py` that rewrites topics to `$1.cdc`; it conflicts with ADR 0005 and the T25 naming convention.

### Topic inventory

| Topic pattern | Partitions | Retention | Cleanup | Notes |
| --- | ---: | --- | --- | --- |
| `cdc.postgres.public.orders_v2` | 3 | 7 days local/staging, 14 days prod-like | `delete` | Raw Debezium envelope; internal boundary |
| `cdc.postgres.public.users_enriched` | 3 | 7 days local/staging, 14 days prod-like | `delete` | Raw Debezium envelope; internal boundary |
| `__debezium-heartbeat.cdc.postgres` | 1 | 24 hours | `delete` | Heartbeat topic for liveness/lag checks |
| `cdc.mysql` | 1 | 7 days | `delete` | MySQL Debezium signal topic used when Kafka auto-create is disabled |
| `cdc.mysql.agentflow_demo.products_current` | 3 | 7 days local/staging, 14 days prod-like | `delete` | Raw Debezium envelope; internal boundary |
| `cdc.mysql.agentflow_demo.sessions_aggregated` | 3 | 7 days local/staging, 14 days prod-like | `delete` | Raw Debezium envelope; internal boundary |
| `__debezium-heartbeat.cdc.mysql` | 1 | 24 hours | `delete` | Heartbeat topic for liveness/lag checks |
| `schemahistory.cdc.mysql.agentflow_demo` | 1 | Unlimited | `delete` | MySQL connector internal schema history topic; Debezium 3.5 JSON records can be keyless, so compaction is not valid in the local stack |
| `cdc.postgres.transaction`, `cdc.mysql.transaction` | 1 | 7 days | `delete` | Enabled only if transaction metadata is required by normalizer |
| `events.deadletter` | 3 | 14 days local/staging, 30 days prod-like | `delete` | Existing AgentFlow DLQ for malformed/unmappable normalized records |

Kafka record ordering is guaranteed per partition. The normalizer must key CDC records by primary key so each entity's changes stay ordered even when table topics use three partitions.

## 4. Deployment manifests

T25b should create the following files.

| Path | Description |
| --- | --- |
| `docker/kafka-connect/Dockerfile` | Builds the AgentFlow Kafka Connect image from `confluentinc/cp-kafka-connect-base:7.7.0` and installs Debezium PostgreSQL/MySQL `3.5.0.Final` plugin archives into the configured plugin path. |
| `helm/kafka-connect/Chart.yaml` | Separate Helm chart for Kafka Connect rather than embedding Connect in `helm/agentflow`, because `docs/helm-deployment.md` states the AgentFlow chart deploys the API only and external services stay outside it. |
| `helm/kafka-connect/values.yaml` | Defaults for worker replicas, image, Kafka bootstrap servers, internal topic names, converters, JMX, resources, and connector enable flags. Local/kind values set `replicaCount=1`; staging/prod-like values set `replicaCount=2`. |
| `helm/kafka-connect/values.schema.json` | Helm values contract mirroring the strict schema pattern already used by `helm/agentflow/values.schema.json`. |
| `helm/kafka-connect/templates/configmap.yaml` | Worker config: `group.id=agentflow-connect`, internal topics, JSON converters, plugin path, REST advertised host/port, offset flush settings, and JMX exporter config path. |
| `helm/kafka-connect/templates/topic-bootstrap.yaml` | Helm hook Job that pre-creates Kafka Connect internal topics, raw CDC table topics, Debezium heartbeat/signal topics, and the MySQL schema history topic before connector registration. |
| `helm/kafka-connect/templates/deployment.yaml` | Kafka Connect distributed workers with readiness on `GET /connectors`, liveness on the REST port, JMX port, and rolling-update settings. |
| `helm/kafka-connect/templates/service.yaml` | ClusterIP service exposing Kafka Connect REST API on `8083` and metrics/JMX exporter on the selected port. |
| `helm/kafka-connect/templates/secret.yaml` | Optional local/demo credentials only. Production values should reference an existing Kubernetes Secret or ExternalSecret-managed Secret and should not render passwords from chart defaults. |
| `helm/kafka-connect/templates/connector-postgres.yaml` | Helm hook Job plus ConfigMap payload that upserts the PostgreSQL Debezium connector through Kafka Connect REST after workers are ready. It configures `pgoutput`, `slot.name=agentflow_postgres_slot`, `publication.name=agentflow_cdc_publication`, `publication.autocreate.mode=filtered`, `table.include.list=public.orders_v2,public.users_enriched`, and JSON converters. |
| `helm/kafka-connect/templates/connector-mysql.yaml` | Helm hook Job plus ConfigMap payload that upserts the MySQL Debezium connector through Kafka Connect REST. It configures `database.server.id=223345`, `database.include.list=agentflow_demo`, `table.include.list=agentflow_demo.products_current,agentflow_demo.sessions_aggregated`, and `schema.history.internal.kafka.*`. |
| `helm/kafka-connect/templates/serviceaccount.yaml` | Service account for the worker pods and hook Jobs. Keep RBAC minimal; Kafka ACLs are managed outside this chart. |
| `docker-compose.cdc.yml` | Local dev overlay that adds `postgres-source`, `mysql-source`, `kafka-connect`, source init scripts, and a connector registration command. It should depend on the existing `kafka` service from `docker-compose.yml`. |
| `scripts/register_cdc_connectors.sh` | Idempotent local registration script using `PUT /connectors/{name}/config` and status polling. A PowerShell equivalent can be added if Windows local workflow requires it. |
| `tests/integration/test_cdc_capture.py` | Integration test that inserts rows into Postgres/MySQL and waits for matching Debezium CDC records in Kafka. |

PostgreSQL connector config baseline:

```json
{
  "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
  "tasks.max": "1",
  "database.hostname": "${file:/opt/connect/secrets/postgres.properties:hostname}",
  "database.port": "5432",
  "database.user": "${file:/opt/connect/secrets/postgres.properties:user}",
  "database.password": "${file:/opt/connect/secrets/postgres.properties:password}",
  "database.dbname": "agentflow_demo",
  "topic.prefix": "cdc.postgres",
  "plugin.name": "pgoutput",
  "slot.name": "agentflow_postgres_slot",
  "publication.name": "agentflow_cdc_publication",
  "publication.autocreate.mode": "filtered",
  "table.include.list": "public.orders_v2,public.users_enriched",
  "snapshot.mode": "initial",
  "heartbeat.interval.ms": "30000",
  "signal.data.collection": "agentflow_demo.public.debezium_signal",
  "key.converter": "org.apache.kafka.connect.json.JsonConverter",
  "value.converter": "org.apache.kafka.connect.json.JsonConverter",
  "key.converter.schemas.enable": "false",
  "value.converter.schemas.enable": "false",
  "custom.metric.tags": "service=agentflow,source=postgres"
}
```

MySQL connector config baseline:

```json
{
  "connector.class": "io.debezium.connector.mysql.MySqlConnector",
  "tasks.max": "1",
  "database.hostname": "${file:/opt/connect/secrets/mysql.properties:hostname}",
  "database.port": "3306",
  "database.user": "${file:/opt/connect/secrets/mysql.properties:user}",
  "database.password": "${file:/opt/connect/secrets/mysql.properties:password}",
  "database.server.id": "223345",
  "topic.prefix": "cdc.mysql",
  "database.include.list": "agentflow_demo",
  "table.include.list": "agentflow_demo.products_current,agentflow_demo.sessions_aggregated",
  "snapshot.mode": "initial",
  "heartbeat.interval.ms": "30000",
  "schema.history.internal.kafka.bootstrap.servers": "${KAFKA_BOOTSTRAP_SERVERS}",
  "schema.history.internal.kafka.topic": "schemahistory.cdc.mysql.agentflow_demo",
  "key.converter": "org.apache.kafka.connect.json.JsonConverter",
  "value.converter": "org.apache.kafka.connect.json.JsonConverter",
  "key.converter.schemas.enable": "false",
  "value.converter.schemas.enable": "false",
  "custom.metric.tags": "service=agentflow,source=mysql"
}
```

## 5. Testing plan

### Local compose test

1. Build the Kafka Connect image:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.cdc.yml build kafka-connect
   ```

2. Start Kafka, source databases, and Kafka Connect:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.cdc.yml up -d kafka cdc-kafka-init postgres-source mysql-source kafka-connect
   ```

3. Register connectors:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.cdc.yml run --rm cdc-register-connectors
   ```

4. Verify worker and connector state:

   ```bash
   curl -fsS http://localhost:8083/connectors
   curl -fsS http://localhost:8083/connectors/agentflow-postgres-cdc/status
   curl -fsS http://localhost:8083/connectors/agentflow-mysql-cdc/status
   ```

5. Insert source rows and consume the raw CDC topics:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.cdc.yml exec postgres-source psql -U cdc_reader -d agentflow_demo -c "insert into orders_v2(order_id,user_id,status,total_amount,currency) values ('ORD-CDC-1','USR-CDC-1','confirmed',42.50,'USD');"
   docker compose -f docker-compose.yml -f docker-compose.cdc.yml exec mysql-source mysql -ucdc_reader -pagentflow -D agentflow_demo -e "insert into products_current(product_id,name,category,price,in_stock,stock_quantity) values ('PROD-CDC-1','CDC Widget','test',9.99,true,10);"
   docker compose -f docker-compose.yml -f docker-compose.cdc.yml exec kafka kafka-console-consumer --bootstrap-server kafka:9092 --topic cdc.postgres.public.orders_v2 --from-beginning --max-messages 1
   docker compose -f docker-compose.yml -f docker-compose.cdc.yml exec kafka kafka-console-consumer --bootstrap-server kafka:9092 --topic cdc.mysql.agentflow_demo.products_current --from-beginning --max-messages 1
   ```

### Staging/kind test

1. Reuse the T26 kind pattern:

   ```bash
   kind create cluster --config k8s/kind-config.yaml --name agentflow-cdc-test
   helm lint helm/kafka-connect -f k8s/staging/values-cdc.yaml
   helm install kafka-connect helm/kafka-connect -f k8s/staging/values-cdc.yaml --wait
   ```

2. Port-forward Kafka Connect and verify connector states:

   ```bash
   kubectl port-forward svc/kafka-connect 8083:8083
   curl -fsS http://127.0.0.1:8083/connectors/agentflow-postgres-cdc/status
   curl -fsS http://127.0.0.1:8083/connectors/agentflow-mysql-cdc/status
   ```

3. Run the same insert-and-consume checks against in-cluster test sources.

### Integration test

Add `tests/integration/test_cdc_capture.py` with `@pytest.mark.integration` and `@pytest.mark.requires_docker`. The test should:

- start or require the CDC compose stack;
- insert one row into `orders_v2` and one row into `products_current`;
- poll `cdc.postgres.public.orders_v2` and `cdc.mysql.agentflow_demo.products_current`;
- assert each CDC record contains the expected primary key, `op` code, `source.db`, `source.table`, and `after` values;
- restart the connector task through Kafka Connect REST and assert a second insert is captured after restart.

Keep this test out of the default fast unit path. It should run explicitly with:

```bash
python -m pytest tests/integration/test_cdc_capture.py -m "integration and requires_docker" -v
```

## 6. Rollout strategy

### Step 1: Kafka Connect cluster up, no connectors

- Build and publish the AgentFlow Kafka Connect image.
- Deploy `helm/kafka-connect` with connector hooks disabled.
- Verify `GET /connectors` responds, worker logs show Debezium plugins discovered, and internal topics exist.
- Add Prometheus scrape config for Connect/JMX metrics.

Exit criteria: Connect REST is healthy, internal topics are compacted, and no connector is registered.

### Step 2: PostgreSQL connector

- Enable the Postgres connector hook.
- Confirm the source database has `wal_level=logical`, a replication-capable user, and publication privileges.
- Register `agentflow-postgres-cdc`.
- Insert/update/delete a row in `orders_v2`.
- Verify records arrive on `cdc.postgres.public.orders_v2` with the expected primary key and Debezium operation code.
- Verify `MilliSecondsBehindSource`, connector status, and task status are visible.

Exit criteria: Postgres connector is `RUNNING`, captures initial snapshot and streaming changes, and resumes after a task restart.

### Step 3: MySQL connector

- Enable the MySQL connector hook.
- Confirm the source database has `log_bin`, `binlog_format=ROW`, `binlog_row_image=FULL`, and a unique `server-id`.
- Register `agentflow-mysql-cdc`.
- Insert/update/delete a row in `products_current`.
- Verify records arrive on `cdc.mysql.agentflow_demo.products_current`.
- Verify `schemahistory.cdc.mysql.agentflow_demo` exists with `cleanup.policy=delete` and `retention.ms=-1`.

Exit criteria: MySQL connector is `RUNNING`, captures initial snapshot and streaming binlog changes, and resumes after a task restart.

### Step 4: Connect CDC topics to Flink/Iceberg

Use the Flink path, not a standalone direct consumer, because `docs/architecture.md` defines production processing as Kafka -> Flink -> Iceberg.

- Add a CDC normalizer stage before existing schema/semantic validation.
- Read the raw CDC topic patterns `cdc.postgres.*.*` and `cdc.mysql.*.*`.
- Normalize Debezium envelopes into ADR 0005 canonical CDC fields: `event_id`, `event_type`, `operation`, `timestamp`, `source`, `entity_type`, `entity_id`, `before`, `after`, `source_metadata`.
- Route valid normalized events to `events.validated` and Iceberg tables through the existing validation/enrichment path.
- Route unmappable records and schema-control records that cannot be handled to `events.deadletter`.
- Run `scripts/check_schema_evolution.py` against canonical CDC schemas before enabling new table mappings.

Exit criteria: a source INSERT reaches the matching Iceberg table and serving API path after normalization, while raw Debezium topics remain documented as internal.

## 7. Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| PostgreSQL WAL retention from inactive replication slots | Disk growth or connector restart failure if WAL required by the stored offset is gone | Alert on replication slot lag and inactive slots; set source-side WAL limits deliberately; run connector restart smoke in staging. |
| MySQL binlog retention too short | Connector cannot resume from stored offset after downtime | Set `binlog_expire_logs_seconds` above expected recovery window; alert on connector lag and source binlog age. |
| Schema evolution breaks normalization | CDC records become unmappable or fail validation | Keep raw Debezium schema changes internal, emit canonical `ddl_change` events, and gate mapping changes with `scripts/check_schema_evolution.py`. |
| JSON raw CDC topics lack registry-enforced compatibility | Consumers could couple to raw Debezium envelopes | Declare raw `cdc.*` topics internal, keep only canonical CDC contract public, and add Schema Registry/Avro as a separate hardening decision. |
| Connector credentials leak through Helm values | Source database compromise | Use Kubernetes Secret references, Sealed Secrets, or External Secrets; do not store production passwords in chart defaults or connector ConfigMaps. |
| Connector task failure is not automatically restarted by Connect | CDC capture stops until intervention | Alert on REST status/JMX task state; add a runbook restart command; consider an operator/controller only after the basic chart is stable. |
| Snapshot load affects source databases | Initial snapshot can lock or load demo/staging sources | Limit `table.include.list`, schedule snapshots off peak, keep `snapshot.max.threads=1` initially, and use incremental snapshots only after baseline capture is proven. |
| Topic partitioning changes ordering assumptions | Cross-row ordering is not globally preserved | Key records by primary key and design normalizer/idempotency around entity-level ordering. Use one partition only for tables requiring total table order. |

## 8. Decision points for the user

1. Confirm whether T25b should stay demo/staging-only. This plan does not attach production Postgres/MySQL sources; production rollout needs real hostnames, database names, table list, network path, and secret owner.
2. Confirm whether JSON raw CDC is acceptable through T25b. The default is no Schema Registry for raw Debezium topics; choosing Avro now adds Confluent Schema Registry converter work, compatibility policy, and registry operations to T25b.
3. Choose the production secret mechanism before non-demo deployment: existing Kubernetes Secret, Sealed Secrets, or External Secrets. The chart can support all three, but T25b should implement one default path.

## 9. Estimate T25b implementation

| Step | Estimate | Notes |
| --- | ---: | --- |
| Kafka Connect image and Helm chart | 1.0-1.5 days | Includes Dockerfile, chart, values schema, service, deployment, internal topic config, and metrics port. |
| Local compose CDC stack | 0.5-0.75 day | Adds source DBs, seed SQL, Connect worker, and registration script. |
| PostgreSQL connector rollout | 0.5-0.75 day | Includes publication/slot config, connector hook, local and kind verification. |
| MySQL connector rollout | 0.5-0.75 day | Includes binlog config, schema history topic, connector hook, local and kind verification. |
| Integration test | 0.75-1.0 day | `tests/integration/test_cdc_capture.py`, Docker markers, restart/resume assertion. |
| Flink/Iceberg CDC connection | 1.0-1.5 days | Minimal normalizer path from raw CDC topics to canonical CDC events and existing validated sink. |
| Docs/runbook updates | 0.5 day | CDC operations, connector status checks, lag/DLQ troubleshooting. |

Expected T25b total: **4.75-6.75 engineering days** for deployable demo/staging CDC. Production source onboarding is a separate follow-up after the decision points are answered.

## Evidence and references

High confidence:

- ADR 0005 is still aligned with current Q2 architecture: `docs/architecture.md` already describes Debezium/Kafka Connect CDC feeding the Kafka -> Flink -> Iceberg path.
- Debezium architecture documents MySQL binlog capture, PostgreSQL logical replication, Kafka Connect as a separate service, and table-specific Kafka topics: <https://debezium.io/documentation/reference/architecture.html>.
- Debezium 3.5 is the latest stable release series and lists tested PostgreSQL/MySQL/Kafka Connect compatibility: <https://debezium.io/releases/3.5/>.
- Debezium PostgreSQL docs define `topic.prefix`, `pgoutput`, publication/slot behavior, replication permissions, WAL retention risks, and streaming metrics: <https://debezium.io/documentation/reference/stable/connectors/postgresql.html>.
- Debezium MySQL docs define required connector properties, topic naming, binlog requirements, schema history topic settings, and metrics: <https://debezium.io/documentation/reference/3.4/connectors/mysql.html>.
- Kafka Connect worker configs include plugin path, internal topic replication/partition settings, REST port, and status topic behavior: <https://kafka.apache.org/23/configuration/kafka-connect-configs/> and <https://kafka.apache.org/31/kafka-connect/connector-development-guide/>.
- Kafka topic configs define `cleanup.policy`, `retention.ms`, compaction, and partition-retention behavior: <https://kafka.apache.org/42/configuration/topic-configs/>.
- Confluent docs distinguish JSON converters without Schema Registry from Avro/Protobuf/JSON Schema converters with Schema Registry: <https://docs.confluent.io/platform/current/connect/userguide.html> and <https://docs.confluent.io/platform/current/schema-registry/connect.html>.
