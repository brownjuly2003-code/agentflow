# T23 — Fresh flamegraph on a3ecd38 + perf backlog refresh

**Priority:** P1 · **Estimate:** 2-3 часа · **Track:** Perf next iteration

## Goal

После PII masker fix (`220f94c`, p99 −61% c 936ms до 361ms) top hot frames в entity path сдвинулись. Снять новый flamegraph на HEAD `a3ecd38`, обновить backlog гипотез в `docs/perf/entity-profile-2026-04-24.md` под новую реальность. Nightly SLO p99 < 200 ms ещё ~1.8× недостижим — нужен evidence-based next hypothesis.

## Context

- HEAD: `a3ecd38` (working tree должен быть clean; если нет — не коммить рабочие изменения до профилирования).
- Benchmark contract: `docs/perf/entity-benchmark-contract.md` (version 1.0). **Строго** следовать параметрам и reproducibility checklist (секция 7).
- Предыдущие артефакты:
  - Baseline: `docs/perf/entity-latency-baseline-2026-04-24.json` (p50=179, p99=936), flamegraph `flamegraph-baseline-2026-04-24.svg` (3007 samples).
  - After PII fix: `docs/perf/entity-latency-after-pii-masker-cache.json` (p50=56.65, p99=360.97), flamegraph **не снимался** — это надо сделать.
- Инструментарий: `py-spy record --format speedscope` (или default SVG) на attached PID uvicorn'а во время `profile_entity.py` run.

## Deliverables

1. **Stack up:**
   - Redis up (`docker ps` shows `de_project-redis-1` healthy).
   - DuckDB seeded (`agentflow_demo.duckdb` exists, fixtures present).
   - API: `uvicorn src.serving.api.main:app --host 127.0.0.1 --port 8000`.
   - Запустить py-spy attach: `py-spy record -o docs/perf/flamegraph-after-pii-masker-cache.svg --pid <uvicorn_pid> --duration 30`.
2. В параллельном окне: запустить `scripts/profile_entity.py` с canonical params (iterations=2000, concurrency=16, warmup=20). Убедиться, что py-spy активен во время measured window.
3. Сохранить JSON: `docs/perf/entity-latency-a3ecd38-flamegraph.json` (с machine metadata по контракту секция 5). Сверить с `entity-latency-after-pii-masker-cache.json` — числа должны быть близки ±10%. Если отличаются >20%, разобраться почему (что-то изменилось в stack) до flamegraph analysis.
4. **Обновить `docs/perf/entity-profile-2026-04-24.md`:**
   - Пометить секцию про PII masker как CLOSED (ссылка на `220f94c`).
   - Добавить новую секцию "Hot frames after PII masker fix" — top-5 frames из нового flamegraph.
   - Обновить backlog: переставить приоритеты (DuckDB pool contention, orjson, usage-DB single-writer — что теперь top). Каждая гипотеза: predicted win %, rationale из flamegraph, cost estimate.
5. **Выбрать next hypothesis** — одну. Записать в раздел "Next candidate" с обоснованием (почему эта, почему не другие). Это вход для T24.
6. Коммит `docs(perf): refresh hot-frame backlog after PII fix, next hypothesis = <X>`.

## Acceptance

- `docs/perf/flamegraph-after-pii-masker-cache.svg` создан, читается в browser (Speedscope / Firefox), >= 2000 samples.
- `entity-profile-2026-04-24.md` обновлён: PII masker closed, новый backlog с evidence из flamegraph.
- Next hypothesis выбран, в sprint плане (раздел "Next candidate") явно назван — чтобы T24 не исследовал с нуля.
- Latency JSON валидный, machine metadata включён.

## Notes

- Если py-spy не видит uvicorn PID из-за Windows permissions — запускать под `py-spy record ... -- python -m uvicorn ...` (spawn variant).
- **Не** выбирать next hypothesis без flamegraph evidence — правило из benchmark contract секция 8.2.
- **Не** делать optimizations в этом таске. T23 = observe + decide. T24 = implement.
- Если flamegraph после PII fix **всё ещё** имеет PII-related frames — это означает, что fix не долетел до production code path, и нужно diagnose (см. agent_query.py:34, должно быть `Path(...) != Path(...)`). В этом случае — revert T23 работу и создать T23b hotfix.
