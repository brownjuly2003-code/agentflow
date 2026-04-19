# AgentFlow — Windows DuckDB file lock в rotation тестах
**Date**: 2026-04-17
**Executor**: Codex
**Severity**: Low — тест зелёный изолированно (7/7), падает только в full suite на Windows

## Симптом

```
FAILED tests/integration/test_rotation.py::test_expired_grace_period_revokes_old_key_automatically
_duckdb.IOException: IO Error: Cannot open file "...test_expired_grace_period_revo0\usage.duckdb":
The process cannot access the file because it is being used by another process.
  at src/serving/api/auth/key_rotation.py:185
```

- В изоляции (`pytest tests/integration/test_rotation.py`): 7/7 passed
- В полном прогоне (`pytest tests/unit tests/integration`): 435 passed / 1 failed
- Ошибка на Windows — POSIX не блокирует файлы так жёстко

## Root cause

`key_rotation.py:185` — `KeyRotator.old_key_usage_by_key_id`:
```python
conn = duckdb.connect(str(self._manager.db_path))
```

Открывает **новый** коннект к тому же DuckDB, пока предыдущий тест не полностью освободил файл. Это может происходить когда:

1. `threading.Timer` от предыдущего теста продолжает работать, держит коннект открытым в `expire_previous_key → revoke_old_key → load → ensure_usage_table`.
2. `AuthManager.shutdown()` не ждёт завершения активных таймеров — `Timer.cancel()` не прерывает уже запущенную функцию.
3. Короткое grace period (1s) в фикстуре `expiring_client` гарантирует гонку: таймер срабатывает прямо во время teardown.

## Задача

### Шаг 1 — reproduce
```bash
pytest tests/integration -x --tb=short
# Воспроизводится на второй прогон обычно стабильнее чем на первый
```

### Шаг 2 — fix в `KeyRotator`

Варианты (выбрать наиболее простой, рабочий):

**A) Ждать завершения таймеров при shutdown:**
```python
def shutdown(self) -> None:
    with self._manager._config_lock:
        timers = list(self._manager._rotation_cleanup_timers.values())
        for timer in timers:
            timer.cancel()
        self._manager._rotation_cleanup_timers.clear()
    # Подождать — пока Timer.finished не станет True для всех
    for timer in timers:
        timer.join(timeout=2.0)
```

**B) Флаг `_shutting_down` в `AuthManager`:**
```python
def expire_previous_key(self, key_id: str) -> None:
    if self._manager._shutting_down:
        return
    try:
        self.revoke_old_key(key_id)
    ...
```
И выставлять `_shutting_down = True` в начале `AuthManager.shutdown()`.

**C) Переиспользовать connection из pool вместо `duckdb.connect(...)` в `old_key_usage_by_key_id`:**
Если в manager уже есть `_usage_conn` — использовать его. Это заодно чище семантически.

Рекомендую **B + A** вместе: флаг предотвращает новые операции, join гарантирует что текущие завершились.

### Шаг 3 — verify

```bash
# Повторить 3 раза подряд — должно быть стабильно
for i in 1 2 3; do
  pytest tests/unit tests/integration -q --tb=line 2>&1 | tail -3
done
# Ожидаемо: 436 passed, 0 failed (во всех 3 прогонах)
```

## Done When

- [ ] `pytest tests/unit tests/integration` — 436 passed, 0 failed
- [ ] 3 последовательных прогона без regressions
- [ ] `AuthManager.shutdown()` корректно ждёт завершения всех rotation timers

## Notes

- Это **не блокер релиза** — gate перформанса пройден, security issues закрыты, функциональность работает.
- Можно оставить на потом если приоритет — другое.
