# AgentFlow — Code Health v9 (Phase 2)
**Date**: 2026-04-17
**Цель**: закрыть Phase 2 из BCG аудита (Code Health). Phase 0 уже закрыт в v8.
**Executor**: Codex
**Reference**: `BCG_audit.md` §8 "Phase 2", §С "Непокрытые модули"

## Откуда задачи

Из BCG §C (непокрытые тестами модули) и §3.3 (критические проблемы кода):

- `flink_jobs/session_aggregator.py` (196 LOC) — **0 unit-тестов**, production-critical
- `flink_jobs/stream_processor.py` (236 LOC) — **0 unit-тестов**, production-critical
- `ingestion/schemas/events.py` (122 LOC) — 0 unit-тестов (validators не покрыты)
- 10+ мест silent exception swallowing (`except Exception: pass`) в `processing/`, `quality/`, `serving/`
- Двойная система схем: `ingestion/schemas/events.py` (Pydantic) vs `config/contracts/*.yaml` (ручная)
- Magic numbers без named constants ($300/$150/$50 в enrichment.py, 30-min session gap, 768px и т.д.)

## Граф зависимостей

```
TASK 1  Unit-тесты для Flink session_aggregator            ← независим
TASK 2  Unit-тесты для Flink stream_processor              ← независим
TASK 3  Unit-тесты для ingestion/schemas/events validators ← независим
TASK 4  Fix silent exception swallowing (10+ сайтов)       ← независим
TASK 5  Magic numbers → constants.py per module            ← независим
TASK 6  Pydantic → YAML contracts auto-generation          ← после Task 3
```

Все кроме Task 6 — параллелизуемы, но по правилу user'а **выполнять последовательно**.

---

## TASK 1 — Unit-тесты для `session_aggregator.py`

**Файл**: `src/processing/flink_jobs/session_aggregator.py` (196 LOC, 0 тестов)
**Критичность**: 🔴 Production-critical — session windowing и deduplication

**Что покрыть** (минимум 10 тестов):

```
tests/unit/test_session_aggregator.py   # NEW
```

### Test cases

1. `test_single_session_closes_after_gap` — события с gap >30min создают 2 сессии
2. `test_session_aggregates_clicks_and_views` — правильный счёт внутри окна
3. `test_session_handles_out_of_order_events` — event-time correctness
4. `test_session_dedups_same_event_id` — идемпотентность
5. `test_session_discards_null_user_id` — невалидные события → DLQ
6. `test_session_window_custom_gap` — gap параметризуется (5m, 15m, 1h)
7. `test_session_closes_on_watermark_advance` — watermark mechanics
8. `test_session_converted_flag` — True если есть checkout event
9. `test_session_revenue_sum_excludes_cancelled` — бизнес-правило
10. `test_session_late_event_after_window` — поведение late data

### Шаги

1. Прочитать `session_aggregator.py` — понять public API (`process_element`, `on_timer`, etc.)
2. Создать fixture с FakeKeyedProcessFunction stub (если Flink harness недоступен) ИЛИ использовать pyflink DataStream test harness
3. Написать 10 тестов выше
4. Запустить `pytest tests/unit/test_session_aggregator.py -v` — все PASSED

### Verify
```bash
pytest tests/unit/test_session_aggregator.py -v
# Ожидаемо: 10+ passed
pytest --cov=src.processing.flink_jobs.session_aggregator tests/unit/test_session_aggregator.py
# Ожидаемо: coverage >= 85%
```

---

## TASK 2 — Unit-тесты для `stream_processor.py`

**Файл**: `src/processing/flink_jobs/stream_processor.py` (236 LOC, 0 тестов)
**Критичность**: 🔴 Production-critical — pipeline stages, DLQ routing

```
tests/unit/test_stream_processor.py   # NEW
```

### Test cases (минимум 10)

1. `test_pipeline_validates_schema` — Pydantic validation, invalid → DLQ
2. `test_pipeline_enriches_event` — enrichment stage добавляет поля
3. `test_pipeline_deduplicates_by_event_id` — дубликаты отсеиваются
4. `test_pipeline_routes_invalid_to_dlq` — DLQ с metadata об ошибке
5. `test_pipeline_preserves_valid_on_partial_failure` — если enrichment падает — raw сохраняется
6. `test_pipeline_handles_corrupt_json` — graceful handling + DLQ
7. `test_pipeline_timestamp_parsing` — timezone-aware datetime
8. `test_pipeline_idempotent_processing` — повторный запуск = тот же результат
9. `test_pipeline_metrics_emitted` — Prometheus counters update
10. `test_pipeline_backpressure_signal` — throttling when downstream slow

### Verify
```bash
pytest tests/unit/test_stream_processor.py -v
pytest --cov=src.processing.flink_jobs.stream_processor tests/unit/test_stream_processor.py
# Coverage >= 85%
```

---

## TASK 3 — Unit-тесты для `ingestion/schemas/events.py`

**Файл**: `src/ingestion/schemas/events.py` (122 LOC)
**Критичность**: 🟡 Validation logic — сейчас cross-field validators не тестируются

```
tests/unit/test_event_schemas.py   # NEW
```

### Test cases (минимум 8)

Покрыть каждый validator + cross-field check:

1. `test_order_valid_minimal` — обязательные поля, остальное defaults
2. `test_order_total_matches_items` — cross-field validator (сумма line_items == total_amount)
3. `test_order_total_mismatch_raises` — невалидная сумма
4. `test_order_rejects_negative_amount`
5. `test_order_currency_iso4217` — валюта — 3-буквенный ISO
6. `test_session_rejects_ended_before_started`
7. `test_product_price_positive_or_zero`
8. `test_event_timestamp_timezone_aware` — naive datetime → ошибка

### Verify
```bash
pytest tests/unit/test_event_schemas.py -v
# Все cross-field validators проверены
```

---

## TASK 4 — Fix silent exception swallowing

**Источник**: BCG C3. 10+ мест в кодовой базе.

**Список сайтов для правки** (проверены grep-ом):
- `src/processing/event_replayer.py:128`
- `src/processing/local_pipeline.py:188`
- `src/processing/outbox.py:70, 142, 177`
- `src/quality/monitors/metrics_collector.py:93, 220, 272`
- `src/quality/monitors/freshness_monitor.py` — если есть
- `src/serving/api/analytics.py:88`
- `src/serving/cache.py:38, 61, 78` — оставить как есть (fallback legit)

### Правило замены

**БЫЛО:**
```python
except Exception:
    logger.exception("failed")
    return None
```

**СТАЛО:**
```python
except (KnownError1, KnownError2) as exc:
    logger.warning("operation failed, falling back", exc_info=exc, context=...)
    return fallback_value
# Неизвестные исключения пусть всплывают
```

### Правила:
- **Определить** какие конкретные исключения ожидаются (смотреть что бросает вызываемый код)
- Логировать с **структурированным context** (tenant_id, entity_id, etc.)
- Для cache/network paths — fallback допустим, но только на (RedisError, ConnectionError, TimeoutError)
- Для business logic — НЕ глотать, дать всплыть

### Verify
```bash
# Никаких новых регрессий
pytest tests/unit tests/integration --tb=line -q
# bandit довольнее (меньше B110 try-except-pass)
bandit -r src/ --severity-level low 2>&1 | grep -c "B110\|B112"
# Ожидаемо: меньше чем до изменений
```

---

## TASK 5 — Magic numbers → constants

**Источник**: BCG C8

**Типичные места** (найти grep-ом, не переносить всё подряд):

- `src/processing/enrichment.py` — пороги $50/$150/$300 (tier thresholds)
- `src/processing/flink_jobs/session_aggregator.py` — 30-минутный gap (`SESSION_GAP_MINUTES = 30`)
- `src/serving/api/auth/*` — TTL'ы (`GRACE_PERIOD_DEFAULT_SECONDS = 86400`)
- `src/serving/api/rate_limiter.py` — window/limit defaults

### Подход

Создать `src/constants.py` **ТОЛЬКО для cross-cutting constants** (то что используется в >1 модуле). Для module-specific — constants в том же файле, наверху, UPPER_CASE.

**НЕ создавать** централизованный `constants.py` с сотней значений — это антипаттерн. Only genuine shared values.

### Шаги

1. Grep по числовым литералам в hot paths: `grep -rnE "[^_a-zA-Z0-9][0-9]{2,}[^_a-zA-Z0-9]" src/ | head -50`
2. Отфильтровать очевидные (HTTP codes 200/404/500, индексы 0/1, -1)
3. Для каждого magic number >= 2 usages → constant
4. Для single-usage с бизнес-смыслом → constant с комментарием-ссылкой на источник правила
5. Прогнать тесты — ничего не сломалось

### Verify
```bash
pytest tests/ -q --tb=line
# Ничего не упало
git diff --stat
# Видим: небольшой diff, читаемо
```

---

## TASK 6 — Pydantic → YAML contracts auto-generation

**Источник**: BCG D4 — двойная система схем

**Проблема:**
- `src/ingestion/schemas/events.py` (Pydantic) — источник истины для Python
- `config/contracts/*.yaml` (order.v1, order.v2, metric.revenue.v1) — ручная копия для SDK/API docs
- Расхождения между ними приводят к runtime ошибкам

**Цель**: single source of truth = Pydantic. YAML генерируется скриптом.

### Что построить

```
scripts/
  generate_contracts.py       # NEW: Pydantic → YAML
tests/unit/
  test_contracts_in_sync.py   # NEW: падает если YAML устарел
.github/workflows/
  contract.yml                # MODIFY: добавить шаг `python scripts/generate_contracts.py --check`
```

### `scripts/generate_contracts.py`

```python
"""Generate config/contracts/*.yaml from Pydantic event schemas.

Usage:
  python scripts/generate_contracts.py              # regenerate files
  python scripts/generate_contracts.py --check       # exit 1 if files drift (for CI)
"""
import argparse, sys, yaml
from pathlib import Path
from src.ingestion.schemas import events

CONTRACTS_DIR = Path("config/contracts")
ENTITY_MODELS = {
    "order": ("v1", events.OrderEvent),
    "user": ("v1", events.UserEvent),
    # ...
}

def pydantic_to_contract_yaml(model_cls) -> dict:
    schema = model_cls.model_json_schema()
    return {
        "entity": model_cls.__name__,
        "version": "v1",
        "fields": [
            {"name": fname, "type": ftype, "required": ...}
            for fname, ftype in schema["properties"].items()
        ],
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    drift = []
    for entity, (version, model) in ENTITY_MODELS.items():
        path = CONTRACTS_DIR / f"{entity}.{version}.yaml"
        expected = pydantic_to_contract_yaml(model)
        if args.check:
            actual = yaml.safe_load(path.read_text())
            if actual != expected:
                drift.append(str(path))
        else:
            path.write_text(yaml.safe_dump(expected, sort_keys=False))

    if args.check and drift:
        print(f"Contracts drifted: {drift}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
```

### `tests/unit/test_contracts_in_sync.py`

```python
import subprocess, sys

def test_contracts_match_pydantic():
    result = subprocess.run(
        [sys.executable, "scripts/generate_contracts.py", "--check"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"Contracts drifted:\n{result.stderr}"
```

### Verify
```bash
python scripts/generate_contracts.py
git diff config/contracts/   # смотрим что получилось
python scripts/generate_contracts.py --check && echo "OK"
pytest tests/unit/test_contracts_in_sync.py -v
```

---

## Done When

- [ ] `pytest tests/unit tests/integration` — 460+ passed, 0 failed (было 435)
- [ ] Flink coverage: `session_aggregator.py` ≥85%, `stream_processor.py` ≥85%
- [ ] `ingestion/schemas/events.py` coverage ≥90%
- [ ] Bandit: count B110 (try-except-pass) уменьшилось на >=5
- [ ] `config/contracts/*.yaml` идентичны `python scripts/generate_contracts.py` output
- [ ] `pytest tests/unit/test_contracts_in_sync.py` green
- [ ] Обновлён `BCG_audit.md` — отметить ✅ у Phase 2 чекбоксов

## Notes

- **Порядок важен только для Task 6** (после Task 3).
- **НЕ трогать** в этом раунде: Phase 1 (PMF, competitive analysis — не-технические), Phase 3 (Terraform CI, admin UI — отдельно).
- Task 4 может затронуть много файлов — коммитить по логическим группам (processing / serving / quality).
