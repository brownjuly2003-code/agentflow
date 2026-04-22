# T09 — CDC connectors (Postgres WAL + MySQL binlog)

**Priority:** P3 · **Estimate:** 2-3 дня

## Goal

Расширить `src/ingestion/` двумя ready-to-use CDC коннекторами: Postgres logical replication и MySQL binlog. Emit events в Kafka с тем же event schema что синтетика.

## Context

- Репо: `D:\DE_project\` (AgentFlow)
- Текущий `src/ingestion/` содержит synthetic generator и placeholder CDC
- Архитектура: Kafka (KRaft) → Flink → Iceberg
- Event schema определена (читать `src/ingestion/` или `contracts/` чтобы понять формат) — новые коннекторы должны emit в том же формате чтобы не ломать downstream
- Offset persistence нужен, чтобы при рестарте не пересчитывать с начала binlog

## Deliverables

1. **`src/ingestion/cdc/postgres.py`** — `PostgresCDCConnector`:
   - Использует `psycopg2` + logical replication slot (plugin `pgoutput` или `wal2json`)
   - Конфиг: connection string, slot name, publication name, starting LSN (optional)
   - Mapping table → event_type через YAML (см. п.3)
   - Emit events в Kafka topic
   - Graceful shutdown на SIGTERM с flush offset
   - Lag metric `cdc_replication_lag_seconds{source="postgres"}` в Prometheus

2. **`src/ingestion/cdc/mysql.py`** — `MySQLBinlogConnector`:
   - Использует `python-mysql-replication` (`pip install mysql-replication`)
   - Конфиг: host/port/user/password, server_id, starting binlog filename + position, watched tables
   - Same mapping table → event_type через YAML
   - Same Prometheus metric `cdc_replication_lag_seconds{source="mysql"}`

3. **`config/cdc/postgres.example.yaml`**, **`config/cdc/mysql.example.yaml`** — примеры конфигов:
   ```yaml
   # postgres.example.yaml
   source:
     type: postgres
     dsn: postgresql://user:pass@localhost:5432/app
     slot_name: agentflow_cdc
     publication: agentflow_pub
   kafka:
     bootstrap_servers: localhost:9092
     topic: cdc.postgres.events
   mapping:
     orders:
       event_type: order_changed
       key_column: order_id
     users:
       event_type: user_changed
       key_column: user_id
   ```

4. **Offset persistence**:
   - Сохранять LSN (Postgres) / binlog position (MySQL) в dedicated Kafka topic `cdc-offsets` или в Redis
   - Default — Kafka topic (консистентно с остальной инфрой проекта)
   - При старте коннектор читает последний offset из topic, возобновляет с него

5. **CLI** `src/ingestion/cdc/__main__.py`:
   ```bash
   python -m ingestion.cdc --source postgres --config config/cdc/postgres.yaml
   python -m ingestion.cdc --source mysql --config config/cdc/mysql.yaml
   ```

6. **`docker-compose.yml`** — optional services под profile `cdc`:
   ```yaml
   services:
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

7. **Тесты**:
   - `tests/integration/ingestion/test_cdc_postgres.py`:
     - Testcontainers Postgres с logical replication включённым
     - Создание publication + slot через test setup
     - INSERT/UPDATE/DELETE в source
     - Assert что Kafka topic получил события с правильной семантикой (op, before, after)
     - Restart connector mid-stream, verify resume from saved offset
   - `tests/integration/ingestion/test_cdc_mysql.py` — аналогично для MySQL binlog

8. **Документация** `docs/ingestion/cdc.md`:
   - Как создать publication в Postgres (`CREATE PUBLICATION`, `wal_level=logical`)
   - Как настроить binlog в MySQL (`log-bin`, `binlog-format=ROW`, `server-id`)
   - Схема offset persistence
   - Мониторинг lag (PromQL query, Grafana panel)
   - Schema evolution: что происходит при ALTER TABLE на source
   - Troubleshooting (slot disk full, binlog rotation, etc.)

9. **`Makefile`** target:
   ```makefile
   cdc-demo:
   	docker compose --profile cdc up -d
   	scripts/cdc_demo.sh
   ```

10. Коммит: `feat(ingestion): add Postgres WAL and MySQL binlog CDC connectors`

## Acceptance

- `pytest tests/integration/ingestion/test_cdc_*.py` — зелёные (может требовать Docker)
- `docker compose --profile cdc up` поднимает Postgres/MySQL + connector, demo скрипт генерит данные, они появляются в AgentFlow API через Kafka → Flink → Iceberg/DuckDB
- `cdc_replication_lag_seconds` exportится в Prometheus на scraping endpoint `/metrics`
- Restart connector mid-stream — resume с правильного offset, без дубликатов и без пропусков (at-least-once семантика приемлема)
- `docs/ingestion/cdc.md` читается и воспроизводим

## Notes

- Обработка offset persistence — Kafka topic `cdc-offsets` (не Redis) для consistency с остальным проектом. Compacted topic, key = `(source, slot_or_binlog)`, value = offset JSON
- Schema evolution — если таблица на source меняется (ALTER TABLE), connector должен emit schema-change event (тип `ddl_change`), НЕ падать. Downstream (Flink) может его игнорировать в v1
- **НЕ использовать Debezium** — хочется Python-native для consistency с остальным проектом и упрощения ops
- Replication lag meaning:
  - Postgres: `now() - (SELECT max(timestamp) FROM replicated_events)` или difference between current WAL location и confirmed_flush_lsn slot'а
  - MySQL: difference between master binlog position и consumer position
- **Безопасность**: DSN/passwords — только через env или secret management, не в YAML конфигах. Конфиги могут ссылаться на env vars (`${POSTGRES_PASSWORD}`)
- DDL events опциональны в v1, но payload schema должен оставлять место для них (union type)
