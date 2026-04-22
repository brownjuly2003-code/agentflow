# T07 — Performance regression trend history

**Priority:** P2 · **Estimate:** 3-4ч

## Goal

Сохранять историю perf benchmarks в `.github/perf-history.json` чтобы видеть тренд p50/p95/p99/throughput через время. Строить график из истории.

## Context

- Репо: `D:\DE_project\` (AgentFlow)
- `.github/workflows/perf-regression.yml` уже гейтит 20% регрессию против baseline
- Baseline — одиночная точка, трудно диагностировать постепенную деградацию
- Нужна append-only история + график

## Deliverables

1. **Workflow** `.github/workflows/perf-regression.yml` — после passing assertion:
   - Извлечь метрики (p50, p95, p99, throughput) из pytest-benchmark JSON или load-test output
   - Append запись в `.github/perf-history.json`:
     ```json
     {
       "timestamp": "2026-04-22T10:30:00Z",
       "commit_sha": "abc1234",
       "branch": "main",
       "p50_ms": 38.2,
       "p95_ms": 180.5,
       "p99_ms": 295.1,
       "throughput_rps": 450.3
     }
     ```
   - Ограничение: последние 500 записей (`jq` или Python трим)
   - Commit на `main` отдельным bot-commit (или на dedicated branch `perf-history` если принято):
     ```yaml
     - name: Commit perf history
       run: |
         git config user.name "perf-history-bot"
         git config user.email "actions@github.com"
         git add .github/perf-history.json
         git diff --staged --quiet || git commit -m "chore(perf): record benchmark history [skip ci]"
         git push
     ```
   - **Важно:** exclude `.github/perf-history.json` из path triggers других workflows (избежать рекурсии)

2. **Script** `scripts/plot_perf_history.py`:
   - Читает `.github/perf-history.json`
   - Генерит `docs/perf/history.html` через Plotly (интерактивный) + `docs/perf/history.png` (static) через matplotlib или plotly static export
   - Три линии: p50, p95, p99 по времени
   - Отдельный график throughput
   - Аннотации на точках где есть git tag (version release)

3. **Makefile** — target:
   ```makefile
   perf-plot:
   	python scripts/plot_perf_history.py --output docs/perf/
   ```

4. **README.md** — секцию `Performance` дополнить ссылкой на `docs/perf/history.html` (если GitHub Pages включён — на published URL)

5. Коммит `ci(perf): record benchmark history and expose trend plot`

## Acceptance

- После merge и 2-3 CI runs — `.github/perf-history.json` содержит 2-3 записи
- `make perf-plot` генерит валидный HTML и PNG
- График показывает p99 как time series, без ошибок
- `perf-regression.yml` НЕ триггерится сам от своего же commit (skip ci работает или path filter)
- `.github/perf-history.json` присутствует в `main` после успешного run

## Notes

- Commit message от bot **обязательно** с `[skip ci]` или путь в `perf-history.json` исключён из триггеров других workflows — иначе бесконечная рекурсия
- НЕ использовать `git push --force` никогда
- Если проект использует signed commits — настроить GPG для bot (иначе либо отключить signing для bot, либо обосновать почему нет)
- Альтернатива: вместо commit в main — external storage (S3/Gist/Bencher.dev). Выбрать commit-в-main как default, переход на external — отдельный таск если объём истории вырастет
