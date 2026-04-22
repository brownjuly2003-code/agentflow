# AgentFlow — Bandit Baseline Refresh v13.5
**Date**: 2026-04-17
**Цель**: снять security gate блокер для release closure
**Executor**: Codex
**Blocker**: исторический v13.5 blocker из раннего снимка; в текущем checkout больше не воспроизводится

## Контекст

Проверка на 2026-04-17 показала, что baseline сам по себе не устарел:

- `.bandit-baseline.json` содержит 1 исторический `B310` в `src/serving/backends/clickhouse_backend.py:49`
- `python -m bandit -r src/ sdk/ -f json -o .tmp/bandit-current.json --severity-level medium` + `python scripts/bandit_diff.py ...` даёт `No new findings (baseline: 1 issues)`
- `bandit --ini .bandit -r src/ sdk/ -f json -o .tmp/bandit-current.json --severity-level medium` + `python scripts/bandit_diff.py ...` тоже даёт `exit=0`
- свежий последовательный прогон целевого regression test `python -m pytest tests/unit/test_bandit_diff.py -q` проходит
- историческое описание “36 new findings vs 1 в baseline” больше не подтверждается в текущем состоянии репозитория

**Правильный подход:** не делать массовый refresh baseline без нового воспроизводимого сигнала. Для текущего checkout задача сводится к closeout-верификации: подтвердить `diff=0`, оставить baseline как есть и зафиксировать, что старый blocker устарел.

---

## TASK 1 — Reproduce current gate

### Шаги

1. **Сгенерить актуальный scan:**
   ```bash
   python -m bandit -r src/ sdk/ -f json -o .tmp/bandit-current.json --severity-level medium
   python scripts/bandit_diff.py .bandit-baseline.json .tmp/bandit-current.json
   ```

   Альтернатива для прямого CLI:
   ```bash
   bandit --ini .bandit -r src/ sdk/ -f json -o .tmp/bandit-current.json --severity-level medium
   python scripts/bandit_diff.py .bandit-baseline.json .tmp/bandit-current.json
   ```

2. **Ожидаемый результат:**

- `bandit_diff.py` возвращает `exit=0`
- новых findings нет
- baseline остаётся с 1 историческим `B310`

3. **Если это не так:**

- сохранить свежий вывод в `.tmp/`
- triage-ить только реально воспроизводимые findings текущего checkout
- не переписывать baseline до завершения triage

### Deliverable — `.tmp/bandit-triage.md`

```markdown
# Bandit Triage — 2026-04-17

## Summary
- Total new findings with valid invocation: 0
- Historical baseline findings: 1 (`B310` at `src/serving/backends/clickhouse_backend.py:49`)
- Historical blocker from earlier plan snapshot: not reproducible in current checkout

## Root Cause
- plan state drifted behind the repo state
- current Bandit gate and checked-in baseline are already aligned

## Action
- Keep `.bandit-baseline.json` unchanged
- Treat v13.5 as verification/closeout unless a fresh scan shows new findings
```

---

## TASK 2 — Preserve the current green state

- Не переписывать `.bandit-baseline.json`
- Не делать bulk-triage по старым числам из плана без свежего воспроизведения
- Если нужна ручная проверка, использовать одну из уже подтверждённых команд из Task 1
- Любые новые правки в коде делать только при реально воспроизводимом finding

### Verify

```bash
python -m bandit -r src/ sdk/ -f json -o .tmp/bandit-post-fix.json --severity-level medium
python scripts/bandit_diff.py .bandit-baseline.json .tmp/bandit-post-fix.json
# Цель: exit=0
```

---

## TASK 3 — Final verification

После нормализации команд:

```bash
python -m bandit -r src/ sdk/ -f json -o .tmp/bandit-current.json --severity-level medium
python scripts/bandit_diff.py .bandit-baseline.json .tmp/bandit-current.json
# exit=0 означает, что baseline совпадает с реальным gate

python -m pytest tests/unit/test_bandit_diff.py -q
# регрессия на checked-in baseline остаётся зелёной
```

---

## Done When

- [ ] `bandit_diff.py` exit=0
- [ ] `.bandit-baseline.json` по-прежнему содержит 1 исторический issue
- [ ] `.tmp/bandit-triage.md` сохранён в `.artifacts/security/bandit-triage-2026-04-17.md`
- [ ] `python -m pytest tests/unit/test_bandit_diff.py -q` остаётся зелёным
- [ ] план больше не требует массового baseline refresh без нового воспроизводимого сигнала

## Notes

- Это уже не active remediation plan, а closeout note для сверки фактического состояния.
- `security.yml`, `scripts/security_check.py` и unit regression на baseline уже согласованы с текущим состоянием репозитория.
- Если в будущем появится реальный новый finding, тогда делать triage/fix по свежему scan, а не по этому историческому снимку.

---

## Next

После v13.5 готов **v14 (SDK Resilience)**: `docs/plans/2026-04-17-v14-sdk-resilience.md` — retry/backoff/circuit-breaker для Python + TS SDK, p99 entity followup. Это post-release Phase 4 задача, не блокирует v1.0.0.
