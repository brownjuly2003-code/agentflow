# Codex tasks: DE_project CI repair (2026-04-23)

Self-contained ТЗ для Codex. Каждый файл — один PR.

## Общий контекст (для всех тасков)

- Репо: `D:\DE_project\` — AgentFlow, real-time data platform для AI-агентов (Python 3.11+/FastAPI, Kafka KRaft, Flink 1.19, Iceberg+DuckDB, Dagster, Helm/kind, OpenTelemetry/Prometheus)
- Состояние: v1.0.1 на `main`, HEAD `5631353` (на момент написания ТЗ), 552 теста зелёных локально, 15 CI workflows
- **CI fully red since 2026-04-20** — последняя зелёная сборка не найдена в последних 100 runs. Цель этого спринта — каждый workflow зелёный
- Все локальные правки рабочего дерева очищены — Codex стартует с чистого `5631353`. Lint/mypy/trivy hardening вынесен в **T00** (prep таск, должен мержиться первым).
- Коммиты — Conventional Commits, один таск = один PR (или несколько тематически близких коммитов в одном PR)
- Lint/type-check/format локально:
  ```
  python -m ruff check src/ tests/
  python -m ruff format --check src/ tests/
  python -m mypy src/ --ignore-missing-imports
  ```
  Все три должны быть зелёными до push

## Таски

| #   | Файл                              | Приоритет | Оценка   |
| --- | --------------------------------- | --------- | -------- |
| T00 | [lint-mypy-trivy-hardening.md](T00-lint-mypy-trivy-hardening.md) | P0 prep   | 1-2ч     |
| T01 | [test-unit-mcp-deps.md](T01-test-unit-mcp-deps.md) | P0        | 20 мин   |
| T02 | [staging-deploy-diagnostics.md](T02-staging-deploy-diagnostics.md) | P0        | 3-5ч     |
| T03 | [e2e-tests-trim.md](T03-e2e-tests-trim.md)         | P1        | 2-3ч     |
| T04 | [trivy-verify-and-fallback.md](T04-trivy-verify-and-fallback.md) | P1        | 1-2ч     |
| T05 | [ci-green-audit.md](T05-ci-green-audit.md)         | P2        | 2-4ч     |

## Порядок исполнения

- **T00 — первым**, мержить до T01-T05. Все остальные таски стартуют от пост-T00 baseline (lint/mypy зелёные).
- T01 — после T00, маленький blocking fix, ~20 мин
- T02 — параллельно с T01 (отдельный PR, не пересекаются по файлам)
- T03 — после T01/T02 (тоже трогает CI workflows)
- T04 — параллельно с T03 (нужен чтобы Trivy ratify post-T00 hardening)
- T05 — финальный аудит, после T01-T04 merge

После T00-T05 merge — память обновить: `~/.claude/projects/D--/memory/project_de_project.md` → CI зелёный.
