# TA03 — T00 hardening functional review

## Scope and method

- Аудит привязан к коммиту `0dde32a`.
- Текущее `HEAD` во время проверки: `a010a2d`.
- `git diff 0dde32a..HEAD -- <target files>` показал, что после T00 из runtime-целевых файлов менялся только `pyproject.toml` и только в части cloud extra (`pyiceberg[pyiceberg-core]`); остальные 8 runtime-файлов совпадают с T00.
- `.github/workflows/security.yml` (`trivy ignore-unfixed`) и `tool.ruff.lint.per-file-ignores` в `pyproject.toml` не включал в 9 verdict-ов ниже: это CI/static-analysis surface, не runtime path.
- Локальный `pytest` в этом окружении сломан внешним глобальным plugin autoload (`schemathesis 4.15.1` падает на `ModuleNotFoundError: _pytest.subtests` при старте раннера). Для целевых прогонов использовал `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` и явный `-p pytest_asyncio.plugin`; это workaround окружения, не изменение репо.

### 1. `src/serving/api/auth/__init__.py` — logger move

**Изменение:** `logger = structlog.get_logger()` перенесён вниз файла, после import-ов и re-export-ов.

**Risk:** late-binding для `auth_package.logger` в `manager.py`, `middleware.py`, `key_rotation.py`.

**Verification:**
- `rg -n "auth_package\\.logger" src/serving/api/auth` подтвердил runtime callers в `manager.py`, `middleware.py`, `key_rotation.py`.
- Runtime smoke: при `AGENTFLOW_ROTATION_GRACE_PERIOD_SECONDS=bad` создание `AuthManager(...)` корректно вызвало `auth_package.logger.warning("invalid_rotation_grace_period_seconds", ...)`; `auth_has_logger=True`.
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin tests/unit/test_auth.py -q` -> `10 passed in 12.54s`.

**Verdict:** `ok` — поздний перенос `logger` не ломает runtime lookup.

### 2. `src/serving/api/routers/admin.py` — B904 `from None`

**Изменение:** ветки `except KeyError` теперь поднимают `HTTPException(... ) from None`.

**Risk:** сломать 404 semantics или потерять structured log context.

**Verification:**
- Source inspection: `admin.py` не содержит прямых `logger`/`structlog` calls (`no logger refs in admin.py`), значит сам route structured context не пишет; контекст живёт в middleware, а не в `raise`.
- Missing-key smoke через `TestClient(app)` с `X-Correlation-ID: ta03-missing-key`:
  - `POST /v1/admin/keys/missing-key/rotate` -> `404`, `{"detail":"API key 'missing-key' not found."}`
  - `GET /v1/admin/keys/missing-key/rotation-status` -> `404`, тот же detail
  - `POST /v1/admin/keys/missing-key/revoke-old` -> `404`, тот же detail
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin tests/integration/test_rotation.py -q` -> `8 passed in 88.47s`.

**Verdict:** `ok` — поведение 404 сохранено, признаков потери лог-контекста нет, потому что route сам его не эмитит.

### 3. `src/serving/api/auth/key_rotation.py` — `dict(rows)`

**Изменение:** `return {key_id: requests_last_hour for ... in rows}` заменён на `return dict(rows)`.

**Risk:** если DuckDB возвращает row type, несовместимый с tuple-pairs, `dict(rows)` упадёт.

**Verification:**
- DuckDB smoke: `duckdb.connect(':memory:').execute(...).fetchall()` вернул row type `tuple`; `dict(rows)` дал `{'key-1': 7}`.
- `tests/integration/test_rotation.py` зелёный, включая runtime paths со status polling и usage counting.
- `tests/unit/test_auth.py` тоже зелёный.

**Verdict:** `ok` — в текущем runtime `fetchall()` tuple-compatible, поведение не изменилось.

### 4. `src/serving/api/routers/admin_ui.py` — `fetchone()` None-guard

**Изменение:** `_qps_last_minute()` теперь сначала сохраняет `row = fetchone()`, потом использует `row[0] if row else 0`.

**Risk:** empty-table / empty-result edge case.

**Verification:**
- Direct smoke на пустой свежей DuckDB базе: `_qps_last_minute(db_path)` -> `0.0`.
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin tests/integration/test_admin_ui.py -q` -> `3 passed in 72.21s`.

**Verdict:** `ok` — empty `api_sessions` больше не образует риск `NoneType[0]`, dashboard path жив.

### 5. `src/logger.py` — `MutableMapping` signature

**Изменение:** `add_otel_context()` получил typed signature `MutableMapping[str, Any] -> MutableMapping[str, Any]`.

**Risk:** несовместимость с processor contract `structlog.configure(processors=[...])`.

**Verification:**
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin tests/unit/test_logging.py tests/unit/test_telemetry.py -q` -> `12 passed in 6.37s`.
- Эти тесты покрывают direct вызов `add_otel_context`, `configure_logging()`, JSON render, contextvars и telemetry wiring.

**Verdict:** `ok` — typed signature не меняет runtime contract для structlog processor.

### 6. `src/serving/api/rate_limiter.py` + `src/serving/cache.py` — optional redis `type:ignore`

**Изменение:** добавлены `# type: ignore[...]` на optional import/assignment `redis.asyncio`.

**Risk:** сломать import path и fallback, когда пакет `redis` отсутствует.

**Verification:**
- Одноразовый virtualenv без установленного `redis`:
  - `redis_present=False`
  - `RateLimiter()._redis is None` -> fallback на in-memory window активен
  - `QueryCache()._redis is None` -> fallback на no-cache/no-op path активен
  - `await RateLimiter().check('tenant:key', 2)` -> `(True, 1, ...)`
  - `await QueryCache().get('metric:revenue:1h:now')` -> `None` + warning `query_cache_unavailable`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin tests/unit/test_rate_limiter.py tests/unit/test_cache.py -q` -> `18 passed in 9.65s`.

**Verdict:** `ok` — type ignores не меняют runtime fallback. Уточнение: `RateLimiter` действительно падает в in-memory mode, `QueryCache` деградирует в no-cache path, а не в in-memory cache.

### 7. `src/serving/backends/clickhouse_backend.py` — typed return locals

**Изменение:** локальные typed переменные `decoded: str` и `rows: list[dict]`.

**Risk:** скрытый functional drift в `_request()` / `execute()`.

**Verification:**
- Smoke без сети: monkeypatched `_request` вернул JSON payload; `execute('SELECT 1')` -> `[{'value': 1}, {'value': 2}]`, `scalar('SELECT 1')` -> `1`.
- В репо нет dedicated `tests/unit/test_clickhouse_backend.py`; проверка ограничена import/execute smoke, что достаточно для чисто typed-local change.

**Verdict:** `ok` — change выглядит functionally inert, smoke path работает.

### 8. `src/serving/semantic_layer/query/sql_builder.py` — typed schema

**Изменение:** `schema` типизирован как `str | None`; остальное в этом куске — formatting/line wrapping.

**Risk:** сломать schema resolution или table qualification в `_scope_sql()`.

**Verification:**
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin tests/unit/test_query_engine.py -q` -> `4 passed in 4.36s`.
- Эти тесты покрывают `_scope_sql()` для CTE alias, subquery qualification и comments.

**Verdict:** `ok` — runtime paths вокруг schema qualification не пострадали.

### 9. `pyproject.toml` — mypy override `src.serving.semantic_layer.query.*`

**Изменение:** добавлен override `disable_error_code = ["attr-defined"]` для `src.serving.semantic_layer.query.*`.

**Risk:** случайно замаскировать другие type errors в query layer.

**Verification:**
- `python -m mypy src/serving/semantic_layer/query/ --disable-error-code attr-defined --hide-error-codes --no-incremental` -> `Success: no issues found in 7 source files`.
- Отдельный warning: `unused section(s) in pyproject.toml: module = ['src.processing.flink_jobs.*']`. Это касается старого flink override, не нового query override.

**Verdict:** `ok` — новый override не скрывает дополнительные ошибки beyond `attr-defined` в текущем query subtree.

## Summary table

| # | Файл | Изменение | Verdict | Если regression — ticket |
| --- | --- | --- | --- | --- |
| 1 | `src/serving/api/auth/__init__.py` | logger move | `ok` | `-` |
| 2 | `src/serving/api/routers/admin.py` | `raise ... from None` | `ok` | `-` |
| 3 | `src/serving/api/auth/key_rotation.py` | `dict(rows)` | `ok` | `-` |
| 4 | `src/serving/api/routers/admin_ui.py` | `fetchone()` None-guard | `ok` | `-` |
| 5 | `src/logger.py` | typed processor signature | `ok` | `-` |
| 6 | `src/serving/api/rate_limiter.py`, `src/serving/cache.py` | optional redis `type:ignore` | `ok` | `-` |
| 7 | `src/serving/backends/clickhouse_backend.py` | typed return locals | `ok` | `-` |
| 8 | `src/serving/semantic_layer/query/sql_builder.py` | typed schema | `ok` | `-` |
| 9 | `pyproject.toml` | mypy override for query layer | `ok` | `-` |

## Conclusion

T00 hardening clean, no regressions found по 9 runtime checkpoints TA03.

Новые tickets в `docs/codex-tasks/2026-04-24/` не создавались.
