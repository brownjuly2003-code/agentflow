# T09 — CDC connectors and normalization (Debezium/Kafka Connect)

**Priority:** P3 · **Estimate:** 3-5 дней

## Goal

Расширить `src/ingestion/` единым CDC path для Postgres и MySQL на базе Debezium/Kafka Connect и нормализовать оба источника в единый AgentFlow CDC contract перед downstream processing.

## Context

- Репо: `D:\DE_project\` (AgentFlow)
- Архитектурное решение зафиксировано в `docs/decisions/0005-cdc-ingestion-strategy.md`
- Текущий `src/ingestion/` уже содержит Debezium-based placeholder для Postgres в `src/ingestion/connectors/postgres_cdc.py`
- Архитектура: Kafka (KRaft) → Flink → Iceberg
- Нужно одно payload contract и один ops model для Postgres/MySQL; raw Debezium envelope не должен уходить в downstream как публичный формат
- Не делать Python-native WAL/binlog consumers и не вводить отдельный custom offset store поверх Kafka Connect

## Deliverables

1. **`src/ingestion/connectors/postgres_cdc.py`** — привести существующий Debezium config builder к ADR-0005:
   - явный topic naming для raw CDC stream
   - publication/slot/schema-history config для Postgres
   - secrets только через env/secret references
   - readiness для регистрации через Kafka Connect REST API

2. **`src/ingestion/connectors/mysql_cdc.py`** — добавить symmetric Debezium MySQL config builder:
   - watched databases/tables
   - schema history topic
   - same topic naming и observability labels что у Postgres

3. **Shared CDC normalizer** в `src/ingestion/cdc/`:
   - принимает raw Debezium envelope от Postgres/MySQL
   - применяет единый mapping `table -> entity_type/event_type/key_column`
   - emit в canonical CDC contract:
     - `event_id`
     - `event_type`
     - `operation`
     - `timestamp`
     - `source`
     - `entity_type`
     - `entity_id`
     - `before`
     - `after`
     - `source_metadata`
   - schema-change records идут как `event_type = "ddl_change"` и `operation = "ddl"`

4. **`config/cdc/postgres.connect.json`**, **`config/cdc/mysql.connect.json`**, **`config/cdc/mapping.example.yaml`**:
   - connector examples для Kafka Connect
   - один mapping format для Postgres и MySQL
   - topic names и history topics документированы рядом

5. **Offset/state model**:
   - использовать Kafka Connect internal topics (`config`, `offset`, `status`)
   - не добавлять custom Kafka topic `cdc-offsets`
   - replay/restart semantics документировать через Connect, а не через source-specific Python state

6. **`docker-compose.yml`** — optional services под profile `cdc`:
   ```yaml
   services:
     kafka-connect:
       image: debezium/connect:...
       profiles: [cdc]
     postgres-source:
       image: postgres:16
       profiles: [cdc]
       environment: [...]
       command: ["postgres", "-c", "wal_level=logical"]
     mysql-source:
       image: mysql:8
       profiles: [cdc]
       environment: [...]
       command: ["--log-bin=mysql-bin", "--binlog-format=ROW", "--server-id=1"]
   ```
   + pre-populated demo данные через init scripts
   + Kafka Connect сконфигурирован Debezium plugins и internal topics

7. **Тесты**:
   - `tests/integration/ingestion/test_cdc_postgres.py`:
     - Postgres source + Kafka Connect/Debezium + normalizer
     - INSERT/UPDATE/DELETE в source
     - Assert что normalized topic получил canonical CDC payload
     - Restart connector/task mid-stream, verify resume через Connect offsets
   - `tests/integration/ingestion/test_cdc_mysql.py` — аналогично для MySQL source
   - unit tests для mapping/normalization edge cases и `ddl_change`

8. **Документация** `docs/ingestion/cdc.md`:
   - Postgres publication / logical replication prerequisites
   - MySQL binlog prerequisites
   - connector registration flow в Kafka Connect
   - canonical CDC contract и mapping rules
   - monitoring lag/error-rate/status
   - schema evolution: как `ddl_change` и schema history проходят через систему
   - troubleshooting (connector failed state, slot lag, history topic drift, binlog retention)

9. **`Makefile`** target:
   ```makefile
   cdc-demo:
      docker compose --profile cdc up -d
      scripts/register_cdc_connectors.sh
   ```
   + регистрирует оба коннектора и запускает demo flow до normalized topic

10. Коммит: `feat(ingestion): add Debezium-based CDC ingestion for Postgres and MySQL`

## Acceptance

- `pytest tests/integration/ingestion/test_cdc_*.py` — зелёные (может требовать Docker)
- `docker compose --profile cdc up` поднимает Postgres/MySQL + Kafka Connect, demo flow регистрирует оба коннектора, normalized CDC events доходят до Kafka
- Postgres/MySQL используют один canonical CDC contract и один mapping format
- `cdc_replication_lag_seconds` и connector/task health exportятся в Prometheus/Grafana path
- Restart connector mid-stream — resume с правильного offset через Kafka Connect internal topics; at-least-once семантика приемлема
- `docs/ingestion/cdc.md` читается и воспроизводим
- В реализации нет Python-native WAL/binlog consumer path

## Notes

- Offset/state ownership у Kafka Connect; custom offset store поверх него не нужен
- Schema evolution — Debezium schema history + normalized `ddl_change`; downstream (Flink) может игнорировать control events в v1.1, но contract должен их сохранять
- Raw Debezium topics — internal boundary. Downstream и docs не должны объявлять их как stable public payload
- Replication lag meaning:
  - Postgres: difference between current WAL progress и connector-applied position
  - MySQL: difference between source binlog progress и connector-applied position
- **Безопасность**: DSN/passwords — только через env или secret management, не в JSON/YAML конфигах. Конфиги могут ссылаться на env vars (`${POSTGRES_PASSWORD}`)
- DDL events опциональны для downstream handling в v1.1, но payload schema и docs должны оставлять место для них
