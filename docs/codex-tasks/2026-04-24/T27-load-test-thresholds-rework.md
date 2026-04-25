# T27 — Load Test thresholds rework under A03 split-decision

**Priority:** P2 · **Estimate:** 3-5 часов · **Track:** Operationalize Q2 decisions · **Depends on:** T23, T24 (stable nightly numbers)

## Goal

`tests/load/thresholds.py` содержит thresholds, которые невозможно достичь (entity p95 = 50 ms, baseline на local = 234 ms, на CI runner будет хуже). Load Test workflow 25+ прогонов подряд красный. A03 split-decision (`docs/perf/benchmark-split-decision.md`) предлагает другой framework: CI smoke gate p99 < 500 ms + nightly benchmark p99 < 200 ms SLO. Привести `thresholds.py` и `.github/workflows/load-test.yml` в соответствие с этим framework'ом.

## Context

**Важно:** этот таск выполняется **после** T23 + T24 landed. Нужны CI-runner numbers (не local) чтобы калибровать пороги. До этого — defer.

- Current `tests/load/thresholds.py`: entity p95=50ms, metrics p95=100ms, batch p95=200ms, query p95=500ms, health p95=20ms. Взяты "с потолка" (см. `docs/perf/entity-profile-2026-04-24.md` раздел root-cause для Load Test, если обновлён).
- `docs/benchmark-baseline.json` (2026-04-17) — реальные замеры: entity p95=200-230ms. До PII fix.
- После PII fix (`220f94c`) + next hypothesis (T24) — цифры будут другими, нужна свежая baseline на **CI runner** (ubuntu-latest, не local Windows).
- A03 split-decision (`docs/perf/benchmark-split-decision.md`) — читать полностью, там framework.

## Deliverables

1. **Capture CI-runner baseline**:
   - Один manual workflow run `load-test.yml` с diagnostic mode (закомментировать `check_thresholds` на 10 минут, записать results.json как artifact).
   - Скачать `.artifacts/load/results.json` — это CI-runner baseline.
   - Или: добавить отдельный workflow `baseline-capture.yml` который запускает тот же load test, но без gate, и сохраняет artifact. Триггер `workflow_dispatch` only.
2. **Rewrite `tests/load/thresholds.py`:**
   - Thresholds = CI baseline p95 × 1.5 (safety margin) или CI baseline p99 (это более строгий gate).
   - `/v1/health` — убрать из thresholds вообще. Health endpoint p95 на 10-run sample недостоверен (cold-start outliers).
   - Align with A03 split: CI smoke gate = p99 per endpoint, threshold ~500ms (entity) / 800ms (batch/query) в зависимости от baseline.
3. **Update `docs/benchmark-baseline.json`** до CI-runner numbers:
   - Старый baseline (local, 2026-04-17) — в `docs/benchmark-baseline-archive/` для истории.
   - Новый — с machine metadata `"runner": "ubuntu-latest", "cpu_count": 4, ...`.
4. **Update `scripts/check_performance.py`** если logic изменилась — но, скорее всего, его не трогать (он уже сравнивает baseline vs current c ±20%).
5. **Update `docs/perf/benchmark-split-decision.md`** — раздел "Current thresholds" с новыми numbers + дата calibration.
6. Три коммита:
   - `ci(load-test): capture CI-runner baseline`
   - `perf(load-test): align thresholds with A03 split-decision`
   - `docs(perf): update baseline and split-decision thresholds`
7. Push. Load Test на main должен перейти в зелёный.

## Acceptance

- Load Test workflow — зелёный 3 прогонов подряд на main (включая один после merge в main, не dispatch).
- `docs/benchmark-baseline.json` обновлён, содержит machine metadata CI runner.
- `tests/load/thresholds.py` — no `/v1/health` threshold, остальные thresholds reasonable (CI baseline × 1.5 or p99).
- `docs/perf/benchmark-split-decision.md` — "Current thresholds" raздел актуален.

## Notes

- **Не** менять thresholds под local numbers. CI runners (GitHub Actions ubuntu-latest) слабее dev machine — игнорирование этого даст false-green на main но flaky-red на PRs.
- Если после калибровки thresholds всё ещё нереалистичны (p95 >1s везде) — это сигнал, что perf нужна следующая итерация (T24 next cycle), а не просто поднять пороги ещё выше. Discuss с юзером до коммита.
- **Не** выключать Load Test workflow полностью. Broken-window anti-pattern, видимый всегда зелёный > невидимый.
- `docs/benchmark-baseline-archive/` — новая папка для исторических baselines. Если старый baseline — единственный — всё равно архивируй (нужен для rollback investigation).
- Рассмотри: после success'а этого таска — обновить `project_de_project.md` memory (раздел Forward plan / CI repair trail).
