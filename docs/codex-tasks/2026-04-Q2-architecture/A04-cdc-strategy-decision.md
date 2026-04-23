# A04 — CDC ingestion strategy decision

**Priority:** P2 · **Estimated effort:** 1-2 weeks (**flag for project planning**)

## Goal

Принять одно стратегическое решение по CDC ingestion: Debezium/Kafka Connect или Python-native connectors, с единым payload и ops model.

## Context

- `src/ingestion/connectors/postgres_cdc.py` уже описывает Debezium-based connector config.
- При этом task `docs/codex-tasks/2026-04-22/T09-cdc-connectors.md` явно требует `НЕ использовать Debezium` и хочет Python-native implementation.
- Зонтичный audit уже пометил это как открытый architectural debt.
- Без решения проект рискует развести design намерение и shipped code/documentation в разные стороны.

## Deliverables

1. Зафиксировать ADR:
   - выбранный CDC approach,
   - почему rejected alternatives не подходят,
   - как decision влияет на Postgres и MySQL paths.
2. Определить единый event contract и operational model:
   - deployment dependencies,
   - observability,
   - failure handling,
   - schema change story.
3. Синхронизировать docs/tasks так, чтобы future work не шло в обе стороны одновременно.
4. Подготовить follow-up backlog под выбранную стратегию.

## Acceptance

- Для CDC roadmap существует одно решение, а не два конкурирующих направления.
- Postgres/MySQL follow-up tasks используют один event contract и один ops model.
- Repo docs больше не одновременно обещают Debezium path и Python-native path.

## Risk if not fixed

Следующие CDC PR-ы могут пойти в разные стороны, producing incompatible payloads, duplicated maintenance и неясные infra requirements для команды, которая будет это деплоить и поддерживать.

## Notes

- Blocked on v1.1 ingestion roadmap и input от ops/owners.
- Не делать смешанный итог "Postgres через Debezium, MySQL вручную" без отдельного decision record.
