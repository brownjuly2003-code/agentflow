# Codex tasks: DE_project v1.1 sprint (2026-04-22)

Self-contained ТЗ для Codex. Каждый файл — один PR.

## Общий контекст (для всех тасков)

- Репо: `D:\DE_project\` — AgentFlow, real-time data platform для AI-агентов
- Stack: Python 3.11+/FastAPI, Kafka (KRaft), Flink 1.19, Iceberg+DuckDB, Dagster, Terraform+Helm+Docker Compose, Prometheus+Grafana+OpenTelemetry
- Состояние: v1.0.1 опубликовано на GitHub, ветка `main` clean, HEAD `2e4b2e8`, 543 теста зелёные, 15 CI workflows
- Коммиты в стиле Conventional Commits (`fix:`, `feat:`, `chore:`, `ci:`, `perf:`), один таск = один PR
- Тесты: `make test` (unit+integration), full suite: `pytest tests/`
- Lint/type-check: `make lint`, `make typecheck`

## Таски

| # | Файл | Приоритет | Оценка |
|---|------|-----------|--------|
| T01 | [repo-hygiene.md](T01-repo-hygiene.md) | P0 | 30 мин |
| T02 | [version-sync.md](T02-version-sync.md) | P0 | 20 мин |
| T03 | [aws-oidc.md](T03-aws-oidc.md) | P1 | 4-6ч |
| T04 | [chaos-schedule.md](T04-chaos-schedule.md) | P1 | 2-3ч |
| T05 | [p99-latency.md](T05-p99-latency.md) | P2 | 1-2д |
| T06 | [codecov.md](T06-codecov.md) | P2 | 1ч |
| T07 | [perf-history.md](T07-perf-history.md) | P2 | 3-4ч |
| T08 | [mcp-integration.md](T08-mcp-integration.md) | P3 | 1д |
| T09 | [cdc-connectors.md](T09-cdc-connectors.md) | P3 | 2-3д |
| T10 | [entity-contracts.md](T10-entity-contracts.md) | P3 | 1-2д |

## Порядок исполнения

- **Параллельно:** T01, T02 (P0 гигиена — за вечер)
- **Последовательно:** T03 → T04 (P1 инфра, CI зависимости)
- **Параллельно:** T05, T06, T07 (P2 perf+obs — независимы)
- **По customer signal:** T08, T09, T10 (P3 фичи — не раньше 5 customer interviews)

После merge T01/T02 — проверить зелёный CI до старта T03+.
