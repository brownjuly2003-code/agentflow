# Audit batch (2026-04-23) — Full project audit разбит на 10 частей

Зонтичный таск `../T_AUDIT-full-project-audit.md` декомпозирован на 10 самодостаточных тикетов. Каждый — независимый PR (или ветка), каждый имеет свой `result.md` deliverable. Финальный TA10 агрегирует.

## Общий контекст (для всех тасков)

- Репо: `D:\DE_project\` — AgentFlow, Python 3.11 / FastAPI / Kafka KRaft / Flink 1.19 / Iceberg+DuckDB / Dagster / Helm / OpenTelemetry
- HEAD на момент написания: `b8ba5f7` на `origin/main`, tree clean
- Локально: `ruff check src/ tests/`, `ruff format --check`, `mypy src/` все три зелёные
- Спринт CI repair (T00-T05) закрыт коммитами `20a5620..739ceb4` + T_AUDIT в `b8ba5f7`. См. `../README.md`.
- CI на push 739ceb4: ✅ Contract / Security / DORA, ❌ CI (test-unit/test-integration на pyiceberg) / Load Test / Staging Deploy / E2E Tests
- Известная регрессия: `test-integration` job в `.github/workflows/ci.yml` ставит `[dev]` без `cloud` extra → quick fix в TA01

## Таски

| #    | Файл                                              | Приоритет | Оценка | Параллельно с |
| ---- | ------------------------------------------------- | --------- | ------ | ------------- |
| TA01 | [ci-matrix-and-quickfix.md](TA01-ci-matrix-and-quickfix.md) | P0        | 1ч     | —             |
| TA02 | [test-suite-catalog.md](TA02-test-suite-catalog.md)         | P1        | 1-2ч   | TA03..TA09    |
| TA03 | [t00-hardening-review.md](TA03-t00-hardening-review.md)     | P1        | 1-2ч   | TA02, TA04..TA09 |
| TA04 | [extras-matrix.md](TA04-extras-matrix.md)                   | P1        | 1ч     | TA02, TA03, TA05..TA09 |
| TA05 | [stale-code-scan.md](TA05-stale-code-scan.md)               | P2        | 1-2ч   | TA02..TA04, TA06..TA09 |
| TA06 | [docs-alignment.md](TA06-docs-alignment.md)                 | P2        | 1ч     | TA02..TA05, TA07..TA09 |
| TA07 | [security-posture.md](TA07-security-posture.md)             | P1        | 1-2ч   | TA02..TA06, TA08, TA09 |
| TA08 | [architectural-debt.md](TA08-architectural-debt.md)         | P2        | 1ч     | TA02..TA07, TA09 |
| TA09 | [memory-state-sync.md](TA09-memory-state-sync.md)           | P2        | 30м    | TA02..TA08    |
| TA10 | [consolidation-and-recommendation.md](TA10-consolidation-and-recommendation.md) | P0 | 1ч | depends on TA01..TA09 |

## Порядок исполнения

- **TA01 — первым** (quick fix даёт CI test-integration шанс пройти, влияет на TA02 catalog).
- **TA02..TA09 — параллельно** (независимые scopes, разные файлы deliverable).
- **TA10 — последним**, агрегирует TA01..TA09 в `../T_AUDIT-result.md` с go/no-go для следующего спринта.

## Соглашения

- Каждый таск deliverable пишет в `docs/codex-tasks/2026-04-23/audit/<TAxx>-result.md`.
- Quick fix в TA01 — отдельный коммит до анализа matrix.
- Любой actionable finding не fix-ит автор таска (кроме TA01 quick fix), а создаёт ticket в `docs/codex-tasks/2026-04-24/`.
- Если deliverable не получилось доделать — частичный result.md с явной отметкой `partial — see <reason>`, а не отсутствие файла.
