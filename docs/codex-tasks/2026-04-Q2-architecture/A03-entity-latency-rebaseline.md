# A03 — Entity latency re-baseline before further optimization

**Priority:** P2 · **Estimated effort:** 1-2 weeks (**flag for project planning**)

## Goal

Перед следующей волной perf work заново привязать entity latency backlog к измеренному hot path `/v1/entity/{type}/{id}` и к repeatable benchmark setup, а не к устаревшим гипотезам из старых perf notes.

## Context

- `docs/codex-tasks/2026-04-22/T05-p99-latency.md` предполагает, что sqlglot cache может быть главным win.
- На текущем HEAD entity path живёт в `src/serving/semantic_layer/query/entity_queries.py` и строит SQL вручную; hot path здесь ближе к `_backend.execute(...)`, row materialization и `_last_updated` normalization, а не к sqlglot parse cache.
- `docs/benchmark.md`, `docs/regression-report.md` и `docs/release-readiness.md` фиксируют baseline от 2026-04-17 на уровне `290-320 ms` p99 для entity endpoints, но checked-in benchmark артефакты на том же хосте расходятся заметно сильнее: `docs/benchmark_pool16.md` показывает `200-320 ms`, `docs/benchmark_pool16_60s.md` — `15-140 ms`, `docs/benchmark_pool24_60s.md` — `30-200 ms`.
- `docs/perf/README.md` прямо отмечает, что bare host-side run даёт misleading numbers без reachable Redis/Kafka/demo stack: cache warning logging, `/v1/health` fan-out и usage DB contention искажают latency profile.
- CI/perf repair уже выделен отдельно в `docs/codex-tasks/2026-04-24/T06-performance-workflows-baseline-repair.md`; это не закрывает architectural question о том, какой optimization plan вообще осмыслен.
- Audit от 2026-04-23 уже зафиксировал этот drift как architectural debt в `docs/codex-tasks/2026-04-23/audit/TA08-architectural-debt.md` и `TA08-result.md`.

## Deliverables

1. Зафиксировать reference benchmark contract для entity perf:
   - обязательный stack/services и startup path,
   - один canonical quick profile (`scripts/profile_entity.py`) и один canonical full benchmark (`scripts/run_benchmark.py`),
   - repeatable capture для p50/p95/p99, throughput и machine metadata,
   - naming/placement для baseline артефактов в `docs/perf/` и benchmark reports.
2. Повторно профилировать entity hot path на текущем HEAD в reference environment:
   - снять baseline JSON + flamegraph,
   - выделить top hot frames и привязать их к конкретным слоям (`backend execution`, middleware/logging, serialization/post-processing, dependency noise),
   - явно зафиксировать, какие старые гипотезы не подтверждаются.
3. Переписать optimization backlog так, чтобы он бил по подтверждённым bottleneck-ам:
   - заменить порядок шагов из `T05-p99-latency.md` на evidence-based,
   - ранжировать только гипотезы с ожидаемым win и способом проверки,
   - не пропускать в sprint изменения без измеримого эффекта.
4. Отдельно принять benchmark split decision:
   - нужен ли quick CI perf gate как smoke/release guard,
   - нужен ли long-running benchmark для цели `<200 ms`,
   - какие thresholds относятся к release gating, а какие только к optimization tracking.

## Acceptance

- Есть один documented baseline для current HEAD с точным environment, командами запуска, датой и before-artifacts; конфликтующие benchmark markdown-файлы явно считаются historical input.
- Следующий perf PR для entity path опирается на актуальный профиль и measured hot frames, а не на старые гипотезы вроде `sqlglot-cache-first`.
- Есть repeatable environment для сравнения before/after и отдельно понятно, что является CI smoke gate, а что long-running optimization benchmark.
- No-op work вроде sqlglot-cache-first change не попадает в sprint без evidence и без измеримого win на reference stack.

## Risk if not fixed

Следующий sprint может потратить 1-2 недели на оптимизации, которые почти не двигают entity p99, при этом release gate `<500 ms` и target `<200 ms` останутся смешанными, а команда будет спорить о CI thresholds и отдельных гипотезах без общего измерительного ground truth.

## Notes

- Blocked on доступ к representative benchmark stack.
- Существующий `T05-p99-latency.md` считать historical input, а не готовым execution plan.
- До появления нового baseline `docs/perf/README.md` считать source of truth по measurement caveats и profiling workflow.
- Эта задача про re-baseline и backlog correction, а не про внедрение очередной оптимизации в код.
