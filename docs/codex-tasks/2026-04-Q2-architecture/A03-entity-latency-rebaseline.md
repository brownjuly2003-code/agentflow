# A03 — Entity latency re-baseline before further optimization

**Priority:** P2 · **Estimated effort:** 1-2 weeks (**flag for project planning**)

## Goal

Перед следующей волной perf work перепривязать план оптимизаций к реальному hot path `/v1/entity/{type}/{id}`, а не к устаревшим гипотезам.

## Context

- `docs/codex-tasks/2026-04-22/T05-p99-latency.md` предполагает, что sqlglot cache может быть главным win.
- На текущем HEAD entity path живёт в `src/serving/semantic_layer/query/entity_queries.py` и строит SQL вручную; sqlglot используется в `_scope_sql()` для других query flows, а не как основной bottleneck entity lookup.
- CI/perf repair уже выделен отдельно в `docs/codex-tasks/2026-04-24/T06-performance-workflows-baseline-repair.md`; это не закрывает architectural question о том, какой optimization plan вообще осмыслен.
- Честный p99 замер для следующих шагов требует representative stack, а не только host-side smoke.

## Deliverables

1. Зафиксировать reference benchmark environment:
   - Docker stack / representative services,
   - workload profile,
   - repeatable p50/p95/p99 capture.
2. Повторно профилировать entity hot path на текущем codebase.
3. Переписать optimization backlog так, чтобы он бил по подтверждённым bottleneck-ам.
4. Отдельно решить, нужен ли split между quick CI perf gate и long-running benchmark.

## Acceptance

- Следующий perf PR для entity path опирается на актуальный профиль, а не на старые гипотезы.
- Есть repeatable environment для сравнения before/after.
- No-op work вроде sqlglot-cache-first change не попадает в sprint без evidence.

## Risk if not fixed

Следующий sprint может потратить 1-2 недели на оптимизации, которые почти не двигают entity p99, при этом целевой `<200 ms` backlog останется нерешённым и команда получит ложный sense of progress.

## Notes

- Blocked on доступ к representative benchmark stack.
- Существующий `T05-p99-latency.md` считать historical input, а не готовым execution plan.
