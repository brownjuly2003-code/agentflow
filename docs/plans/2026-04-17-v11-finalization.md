# AgentFlow — Finalization v11
**Date**: 2026-04-17
**Цель**: закрыть хвосты v8/v9/v10, обновить артефакты, полный отчёт
**Executor**: Codex
**Reference**: `BCG_audit.md`, v8/v9/v10 plans

## Что осталось

После v8/v9/v10 закрыты Phase 0, Phase 2, Phase 3. Остались технические долги:

1. `docs/benchmark-baseline.json` — snapshot старого прогона (p50=570ms). Нужен актуальный (p50=43ms), иначе `--baseline` regression check не имеет смысла.
2. Chaos smoke в PR CI ещё ни разу реально не прогонялся — синтаксис есть, runtime не подтверждён.
3. Load regression gate — то же: реальный прогон не подтверждён.
4. `terraform plan` локально не запускался — tfvars-examples не провалидированы.
5. Bandit всё ещё красный из-за old out-of-scope findings — нужно зафиксировать baseline bandit allowlist, чтобы **новые** findings ломали CI, а старые не шумели.
6. `BCG_audit.md` не обновлён — отметки ✅ не проставлены у закрытых пунктов.
7. Единый release readiness report — в одном месте показать что сделано.

---

## Граф зависимостей

```
TASK 1  Регенерация benchmark-baseline.json             ← независим
TASK 2  Runtime validation chaos smoke + load gate      ← независим
TASK 3  Terraform plan smoke (local или docker)         ← независим
TASK 4  Bandit baseline (allowlist)                     ← независим
TASK 5  BCG_audit.md — пометить ✅ закрытые пункты      ← после Task 1-4
TASK 6  Release readiness report                        ← последним
```

---

## TASK 1 — Регенерация `docs/benchmark-baseline.json`

**Проблема:** baseline снят до v8 TASK 3 (Redis cache). Файл показывает p50=570ms — не отражает текущего состояния. PR regression check c `--baseline` будет срабатывать ложно.

### Шаги

```bash
docker compose up -d redis
make api &
API_PID=$!
sleep 15
python scripts/run_benchmark.py --host http://127.0.0.1:8000 --output docs/benchmark-baseline.json
kill $API_PID
docker compose down
```

Если флага `--output` в `run_benchmark.py` нет — добавить (2 строки): argparse + `Path(args.output).write_text(json.dumps(report, indent=2))`.

### Verify

```bash
# 1. Файл обновлён, endpoint p50 < 100ms
python -c "
import json
b = json.loads(open('docs/benchmark-baseline.json').read())
for name, data in b['endpoints'].items():
    if '/v1/entity/' in name:
        assert data['p50_ms'] < 100, f'{name} p50={data[\"p50_ms\"]}'
print('OK')
"

# 2. Regression check self-consistent
python scripts/check_performance.py --baseline docs/benchmark-baseline.json --current docs/benchmark-baseline.json --max-regress 20
echo "exit=$?"   # ожидаемо 0
```

---

## TASK 2 — Runtime validation chaos smoke + load PR gate

**Проблема:** v10 добавил chaos smoke и load на PR trigger, но ни разу реально не запускался end-to-end локально. Workflow-syntax ≠ работающий pipeline.

### Шаги

**Chaos smoke:**
```bash
docker compose -f docker-compose.chaos.yml up -d
pytest tests/chaos/test_chaos_smoke.py -v --timeout=180
docker compose -f docker-compose.chaos.yml down
```

Проверить:
- Все тесты PASS
- Wall-time < 5 min
- Если падает — исправить и повторить

**Load PR gate:**
```bash
docker compose up -d redis
make api &
sleep 15
python scripts/run_benchmark.py --host http://127.0.0.1:8000 --users 20 --run-time 30s --output /tmp/pr-bench.json
python scripts/check_performance.py --baseline docs/benchmark-baseline.json --current /tmp/pr-bench.json --max-regress 20
echo "gate exit=$?"
```

### Искусственная регрессия (проверка что gate реально ловит)

Вставить `time.sleep(0.1)` в `get_entity` в `src/serving/semantic_layer/query/entity_queries.py`, прогнать тот же check — **должен упасть с regression > 20%**. Вернуть код обратно.

### Verify
- Chaos smoke local run: все зелёные, < 5 min
- Load gate: зелёный на чистой ветке, красный на искусственной регрессии
- Записать wall-time в commit message

---

## TASK 3 — Terraform plan smoke

**Проблема:** локально терраформ не прогонялся — tfvars.example могут не совпадать с variables.tf.

### Подход без локального terraform

Использовать docker:
```bash
cd infrastructure/terraform
docker run --rm -v "$PWD:/workspace" -w /workspace hashicorp/terraform:1.7 init -backend=false
docker run --rm -v "$PWD:/workspace" -w /workspace hashicorp/terraform:1.7 validate
docker run --rm -v "$PWD:/workspace" -w /workspace hashicorp/terraform:1.7 plan -var-file=environments/staging.tfvars.example -input=false -lock=false
```

**Если plan падает с "Missing required argument":**
- Дополнить `staging.tfvars.example` / `prod.tfvars.example` всеми required variables (без секретов — placeholder типа `"<REPLACE-ME>"`)
- Убедиться что `variables.tf` для всех модулей имеет sensible defaults там где уместно

### Verify
```bash
# Оба environment files должны пройти validate + plan
for env in staging prod; do
  docker run --rm -v "$PWD:/workspace" -w /workspace hashicorp/terraform:1.7 plan \
    -var-file=environments/${env}.tfvars.example -input=false -lock=false
  echo "${env}: exit=$?"
done
```

---

## TASK 4 — Bandit baseline

**Проблема:** `bandit -r src/ --severity-level low` красный из-за старых findings вне scope v8-v10. Новые regressions не видно.

### Создать baseline

```bash
pip install bandit
bandit -r src/ -f json -o .bandit-baseline.json --severity-level medium
```

Добавить в `.github/workflows/security.yml` или `ci.yml`:

```yaml
- run: pip install bandit
- run: |
    bandit -r src/ -f json -o /tmp/bandit-current.json --severity-level medium || true
    python scripts/bandit_diff.py .bandit-baseline.json /tmp/bandit-current.json
```

### `scripts/bandit_diff.py` (NEW)

```python
"""Fail CI if new bandit findings appeared vs baseline."""
import json, sys
from pathlib import Path

baseline_path, current_path = Path(sys.argv[1]), Path(sys.argv[2])
baseline = json.loads(baseline_path.read_text())
current = json.loads(current_path.read_text())

def key(issue):
    return (issue["test_id"], issue["filename"], issue["line_number"])

baseline_keys = {key(i) for i in baseline["results"]}
new_findings = [i for i in current["results"] if key(i) not in baseline_keys]

if new_findings:
    print(f"New bandit findings: {len(new_findings)}")
    for i in new_findings:
        print(f"  {i['test_id']} {i['filename']}:{i['line_number']} — {i['issue_text']}")
    sys.exit(1)
print(f"No new findings (baseline: {len(baseline['results'])} issues)")
```

### Verify
```bash
python scripts/bandit_diff.py .bandit-baseline.json .bandit-baseline.json
# exit=0: same file, zero diff
```

---

## TASK 5 — Обновить `BCG_audit.md`

Пройти по файлу, в Phase 0 / Phase 2 / Phase 3 и §C / §D проставить `✅` у закрытого. Формат:

```markdown
### Phase 0: Блокеры релиза (2 недели)

- [x] **Performance fix**: ✅ p50 43ms (v8 TASK 1-3)
- [x] **SQL injection fix**: ✅ parameterized queries + sqlglot validator (v8 TASK 2,4,5)
- [x] **Scope cut**: ⚠️ не делали — оставили current endpoints
```

Для каждой отметки — короткая ссылка на commit/plan где сделано. Если что-то не сделано — явно `⚠️ not done` + причина.

### Добавить секцию в конец

```markdown
---

## История исправлений

- **2026-04-17 v8** — Phase 0 блокеры: async offload, parameterized queries, cache, sqlglot, god-class split. p50 26000ms → 43ms.
- **2026-04-17 v9** — Phase 2 code health: Flink tests (session_aggregator, stream_processor), event schema validators, contracts auto-gen, constants module.
- **2026-04-17 v10** — Phase 3 production readiness: chaos PR smoke, load regression gate, terraform apply workflow, minimal admin UI.
- **2026-04-17 v11** — Finalization: benchmark baseline regen, runtime validation CI pipelines, bandit baseline, BCG audit update.
```

### Verify
```bash
grep -c "\[x\]\|✅" BCG_audit.md
# Ожидаемо: >15
```

---

## TASK 6 — Release readiness report

**Цель:** один документ показывающий готовность к релизу.

### `docs/release-readiness.md` (NEW)

```markdown
# Release Readiness Report
**Date**: 2026-04-17
**Version**: v1.0.0-rc1

## Executive Summary

AgentFlow готов к v1.0.0. Все Phase 0 блокеры из BCG аудита (2026-04-12) закрыты. Phase 2 (Code Health) и Phase 3 (Production Readiness) завершены. Phase 1 (Product-Market Fit) — не-технический, вне scope.

## Status by BCG Dimension

| Направление | Было (2026-04-12) | Стало (2026-04-17) | Delta |
|-------------|-------------------|---------------------|-------|
| Продукт | 6.5 / 10 | 6.5 / 10 | — (Phase 1 outside scope) |
| Дизайн | 7.5 / 10 | 8.0 / 10 | +0.5 (admin UI) |
| Код | 7.0 / 10 | 8.5 / 10 | +1.5 (perf + split + tests) |
| DevOps | 8.5 / 10 | 9.0 / 10 | +0.5 (terraform apply, PR gates) |
| Документация | 9.0 / 10 | 9.0 / 10 | — |

## Performance

| Метрика | До | После | Цель | Status |
|---------|-----|--------|------|--------|
| p50 (entity) | 26000ms | 43ms | <100ms | ✅ |
| p99 (entity) | 40000ms | 170ms | <500ms | ✅ |
| RPS | 0.27 | 28.82 | — | +107x |
| Event loop blocking | yes | no | — | ✅ |

## Test Coverage

| Категория | Было | Стало |
|-----------|------|--------|
| Всего тестов | 379 | 491+ |
| Flink unit tests | 0 | 20+ |
| Injection/security tests | 0 | 32 |
| Contract drift tests | 0 | 1 (scripted) |

## Code Health

- auth.py 862 LOC → `auth/` 4 файла, каждый <400 LOC
- alert_dispatcher.py 738 LOC → `alerts/` 5 файлов
- query_engine.py 710 LOC → `query/` 7 файлов
- Silent exceptions: 10+ точек → 0 unjustified

## Security

- SQL injection: regex scoping → sqlglot AST, string interpolation → parameterized queries
- NL→SQL: allowlist через sqlglot validator, запрещены DDL/DML
- Bandit baseline зафиксирован, CI ловит регрессии

## Infrastructure

- Terraform apply: ручной → GH Actions workflow с required reviewer
- Chaos testing: scheduled only → + PR smoke (< 5 min)
- Load testing: main only → + PR regression gate (-20% threshold)

## Known Limitations

- Phase 1 (PMF) не закрыт — customer discovery, competitive analysis, pricing вне scope этого релиза
- ClickHouse alternative backend — ADR подготовлен, реализация в v2
- SDK retry/circuit-breaker — в v2

## Release Checklist

- [x] Phase 0 blockers closed
- [x] Phase 2 code health done
- [x] Phase 3 production readiness done
- [x] Full test suite green (local + CI)
- [x] Benchmark baseline updated and gate passing
- [x] Bandit baseline зафиксирован
- [x] BCG_audit.md обновлён
- [ ] Phase 1 (PMF) — после релиза, non-blocking для tech release
```

### Verify
- Открыть `docs/release-readiness.md` — все ссылки рабочие
- Данные из отчёта совпадают с реальными цифрами в `docs/benchmark.md`, `BCG_audit.md`, `pytest -v` output

---

## Финальный отчёт Codex

После выполнения всех 6 задач — **один консолидированный комментарий** по шаблону:

```
## v11 Finalization — результат

### Что сделано
- [ ] TASK 1: benchmark-baseline.json — <путь к diff или commit hash>, p50 entity <value>
- [ ] TASK 2: chaos smoke local run — <wall-time>, load gate validated: <PASS/FAIL на чистой ветке + на искусственной регрессии>
- [ ] TASK 3: terraform plan staging / prod — exit codes, обновлённые tfvars.example
- [ ] TASK 4: bandit baseline — <кол-во issues в baseline>, diff script работает
- [ ] TASK 5: BCG_audit.md — <кол-во ✅ отметок>, diff
- [ ] TASK 6: docs/release-readiness.md — создан, <кол-во строк>

### Полный прогон
pytest tests/unit tests/integration --tb=line -q
Результат: <N passed, M failed>

### Bandit
bandit -r src/ --severity-level medium
Результат: <K findings, все в baseline: Y/N>

### Open items
- Если что-то не получилось (terraform docker не смог, chaos тест flaky) — явно указать
- Никаких "в целом работает" — только конкретика с командами и выводом
```

## Notes

- **Все 6 задач — последовательно**, без parallel.
- **Честность в отчёте** важнее скорости. Если TASK 3 (terraform) не удался из-за отсутствия docker или иных причин — явно зафиксировать, не маскировать.
- **Не трогать** в этом раунде: Phase 1 PMF, ClickHouse, SDK v2. Это всё после релиза v1.0.
