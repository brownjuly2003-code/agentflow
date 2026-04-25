# T25 — A04 Debezium + Kafka Connect ops setup — research and plan

**Priority:** P2 · **Estimate:** 1-2 дня (research only) · **Track:** Operationalize Q2 decisions

## Goal

A04 ADR (`docs/decisions/0005-cdc-ingestion-strategy.md`, commit `6fe84ce`) зафиксировал решение: Debezium + Kafka Connect для CDC из Postgres и MySQL. Имплементация deferred. **Этот таск = research + deploy plan**, не implementation. Deliverable — подробный план со всеми решениями, который следующий CX (T25b) сможет выполнить без дополнительного research.

## Context

- ADR в `docs/decisions/0005-cdc-ingestion-strategy.md` — прочитать полностью, проверить что принятые там решения всё ещё актуальны (ничего не изменилось в Q2 architecture с 2026-04-23).
- Kafka уже работает в docker-compose (KRaft mode, `confluentinc/cp-kafka:7.7.0`).
- Iceberg + DuckDB — текущий sink (см. `src/processing/iceberg_sink.py`).
- Flink 1.19 — batch → stream (см. `docs/architecture.md` если есть).
- Helm chart: `helm/agentflow/` — куда Debezium/Kafka Connect manifests должны встать.

## Deliverables

`docs/plans/2026-04-debezium-kafka-connect-deployment-plan.md` со следующими секциями:

1. **Scope decision** — что именно поднимаем:
   - Kafka Connect distributed cluster (HA) или single-node для dev?
   - Debezium connectors: Postgres (какая версия — 2.5+?), MySQL (aналогично).
   - Schema registry: Confluent / Apicurio / none (если используем Avro).
2. **Source systems** — заполнить:
   - Какие Postgres/MySQL instances читаем (prod demo / staging)?
   - Real tables и их schema — достать из текущего `src/processing/local_pipeline.py` или seeded DuckDB, если это demo.
3. **Topic naming** — convention: `cdc.<source>.<schema>.<table>`. Retention policy, partitions count.
4. **Deployment manifests** — список файлов, которые появятся:
   - `helm/kafka-connect/` Helm chart (subchart or separate)
   - `helm/kafka-connect/templates/connector-postgres.yaml` — Debezium Postgres connector config
   - `helm/kafka-connect/templates/connector-mysql.yaml`
   - `docker-compose.cdc.yml` для local dev (если нужен)
5. **Testing plan**:
   - Local: docker-compose up debezium + test postgres + проверить capture записи в Kafka.
   - Staging: kind cluster (из T26 опыта) + helm install.
   - Integration test: новый `tests/integration/test_cdc_capture.py` который ждёт CDC event после INSERT в source DB.
6. **Rollout strategy** — пошаговый:
   - Step 1: kafka-connect cluster up (no connectors yet).
   - Step 2: Postgres connector → capture → verify в Kafka topic.
   - Step 3: MySQL connector.
   - Step 4: connect CDC topics к Flink/Iceberg sink (или прямой consumer в `src/processing/`).
7. **Risks** — известные gotchas:
   - WAL/binlog retention on source DB (если consumer лагает).
   - Schema evolution (подключить к `scripts/check_schema_evolution.py`).
   - Dead letter queue strategy.
   - Credentials / secrets management (sealed-secrets / external-secrets).
8. **Decision points для юзера** — 2-3 вопроса, на которые нужен ответ до T25b implementation (если есть). Сформулируй конкретно.
9. **Estimate T25b implementation**: в часах/днях на каждый Step.

## Acceptance

- `docs/plans/2026-04-debezium-kafka-connect-deployment-plan.md` существует.
- Все 9 секций заполнены concrete details, не "TBD".
- Список файлов в Deliverables 4 — с точными путями и 1-2 sentence describe каждого.
- Decision points (секция 8) — если есть, ясно сформулированы.
- Один коммит `docs(plans): A04 Debezium + Kafka Connect deployment plan`.

## Notes

- **Не** начинать implementation в этом таске. Цель — plan который другой CX может взять и выполнить.
- Если в процессе research выяснится, что ADR 0005 устарел (например, решили что Kafka Connect не нужен, можно встроить CDC в существующий pipeline) — задокументируй в plan как "ADR 0005 revisit needed" и **не** меняй ADR самостоятельно. Это escalation к юзеру.
- Используй upstream docs (debezium.io, Confluent, kafka.apache.org) как источник истины для connector configs, не устаревшие blog posts.
- Если команда не знакома с Kafka Connect — добавь короткое (1 абзац) "background primer" в начало плана.
