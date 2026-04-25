# T24 — Implement next perf hypothesis (selected in T23)

**Priority:** P2 · **Estimate:** 1-2 дня · **Track:** Perf next iteration · **Depends on:** T23

## Goal

Реализовать next perf hypothesis, выбранную в T23 на основе нового flamegraph и обновлённого backlog. Цель — двинуть p99 ближе к nightly SLO 200 ms (сейчас 361 ms на local). Если hypothesis даёт ≥ 5 % p99 reduction — land. Если < 5 % — **не коммитить**, вернуть backlog с причиной ("measured but below 5% threshold") и пометить следующую гипотезу.

## Context

**Важно:** этот таск начинается **после** T23. До T23 hypothesis не выбрана, не начинай работать с предположений.

- Hypothesis и её rationale — в `docs/perf/entity-profile-2026-04-24.md` раздел "Next candidate" (обновлён T23).
- Benchmark contract: `docs/perf/entity-benchmark-contract.md` — используй для до/после замеров строго.
- Threshold rule: "5 % или дальше" (contract секция 8.1). ≤ 5 % p99 wins не коммитятся.

Типовые candidates (зависит от T23 выбора):

- **DuckDB pool contention**: увеличить pool size, или изменить connection reuse pattern, или async DuckDB wrapper.
- **orjson serialization**: profile вывел orjson как top — переключить на msgspec или ujson; но по baseline flamegraph он был <5%, вряд ли top после PII fix.
- **Usage-DB single-writer**: `agentflow_api.duckdb` пишется на каждый request (auth middleware). Batched async writer или Redis-backed queue.
- **Кэширование entity payload в Redis**: TTL 1s для hot IDs (уже есть `ENTITY_TTL_SECONDS` — проверить, работает ли).
- **Pydantic model construction cost**: переключить на dataclasses / msgspec.Struct для hot path.

## Deliverables

1. **Before measurement** (baseline для этой гипотезы):
   - Запустить `profile_entity.py` на чистом HEAD до изменения кода, сохранить `docs/perf/entity-latency-before-<hypothesis>.json` (2000 iterations, contract params).
2. **Implementation** — минимальный код под hypothesis. Один focused commit(-range):
   - Не refactoring за пределы hot frame.
   - Не менять API contract.
   - Не trogarть unrelated tests.
3. **After measurement**:
   - Тот же profile setup (same machine, same parameters, within 5 minutes of before).
   - Сохранить `docs/perf/entity-latency-after-<hypothesis>.json`.
4. **Reproducibility check**: запустить 3 раза (before+after), взять best of 3. Подтвердить, что win стабилен, не шум.
5. **Decide:**
   - Если win ≥ 5 % p99: один коммит `perf(<area>): <change> — p99 −X%` + `docs/perf/entity-profile-after-<hypothesis>.md` write-up (короткий, 1 страница).
   - Если win < 5 %: **revert** code changes. Один коммит только в docs: `docs(perf): <hypothesis> measured at <X%>, below threshold — archived`. Обновить backlog в `entity-profile-2026-04-24.md`.
6. Push.

## Acceptance

**Если win принят:**
- `before` и `after` JSON в `docs/perf/`.
- Write-up `.md` с summary table (p50/p95/p99/throughput delta).
- Сам код изменения — минимальный, проходит `ruff check && ruff format --check && mypy`.
- Все существующие тесты проходят локально (`pytest tests/unit/ tests/property/ -q`).

**Если win отвергнут:**
- Никаких изменений в `src/` в финальном пуше.
- `before`/`after` JSON всё равно в `docs/perf/` (evidence что мы измеряли).
- Backlog обновлён с пометкой next candidate.

## Notes

- Hardware noise: best-of-3 минимум. Если spread > 10 % p99 между runs — отложи измерение, проверь что machine idle (закрой browser, disable realtime AV если можно, no concurrent builds). См. contract секция 7.
- **Не** делать "пока тут — и вот это заодно". Один hypothesis = один commit = одно decision. Если в процессе нашлась **другая** проблема — задокументируй в backlog, не чини сейчас.
- Если выбранная hypothesis оказывается non-trivial (>2 дня) — остановись, задокументируй в write-up как "larger than initially scoped, split into T24a/T24b", и обсуди с юзером до продолжения.
