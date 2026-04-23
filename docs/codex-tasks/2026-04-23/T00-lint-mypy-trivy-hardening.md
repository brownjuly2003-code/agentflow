# T00 — Lint / mypy / trivy hardening (CI lint job → green)

**Priority:** P0 · **Estimate:** 1-2ч

## Goal

Сделать `lint` job в `.github/workflows/ci.yml` зелёным end-to-end (`ruff check`, `ruff format --check`, `mypy`), и зафиксить Trivy gate в `.github/workflows/security.yml` чтобы он не падал на не-fixable CVE. Это **prep таск** — должен пройти ДО старта T01-T05, потому что без него каждая последующая PR ловит pre-existing red lint/mypy.

## Context

- HEAD `5631353` на момент написания ТЗ. Локальные проверки текущего main:
  - `python -m ruff check src/ tests/` → **60 errors**
  - `python -m ruff format --check src/ tests/` → **75 files would be reformatted**
  - `python -m mypy src/ --ignore-missing-imports` → **71 errors in 13 files**
  - CI lint job красный с 2026-04-20+ (15+ runs подряд).
- Стратегия: ruff format автоматически (75 файлов whitespace/quotes), per-file-ignores в `pyproject.toml` для tests/ + `clickhouse_backend.py`, точечные исправления в src/, mypy per-module override для `semantic_layer.query.*` (mixin attr-defined).
- Trivy: добавить `ignore-unfixed: true` чтобы actionable signal остался, но не блокировали CVE без upstream patch.

## Deliverables

Все ниже — в **одном PR**, разбитом на 4 коммита для читаемости.

### Коммит 1 — `style: apply ruff format to src/ tests/`

```bash
python -m ruff format src/ tests/
```

Результат: 75 файлов reformatted (whitespace, кавычки, line breaks). Чисто механический. После — `python -m ruff format --check src/ tests/` возвращает clean.

### Коммит 2 — `chore(ruff): add per-file-ignores for tests and clickhouse backend`

В `pyproject.toml` после секции `[tool.ruff.lint]` добавить:

```toml
[tool.ruff.lint.per-file-ignores]
"tests/**/*.py" = [
    "S603",
    "S607",
    "S310",
    "S104",
    "N802",
    "E402",
    "B017",
    "PT011",
    "A002",
    "E501",
]
"src/serving/backends/clickhouse_backend.py" = [
    "S310",
    "E501",
]
```

Обоснование (для commit body):
- tests S603/S607 — subprocess в test scaffolding, контролируемые args
- tests N802 — мок-классы типов `STRING()/LONG()/BOOLEAN()` имитируют API внешних либ
- tests E402 — `sys.path.insert` перед import-ами (`integrations/`, `sdk/` shimming)
- tests S310/S104 — controlled URL и `0.0.0.0` bind в test fixtures
- tests B017/PT011 — `pytest.raises(Exception)` в resilience tests (намеренно широкие)
- tests A002 — `format` arg как kwarg для API mock-ов
- tests E501 — длинные fixture data lines
- clickhouse S310 — `urlopen` это **the** API для HTTP бэкенда (URL контролируется конфигом)
- clickhouse E501 — длинные `INSERT VALUES` со seed data

### Коммит 3 — `fix(src): targeted ruff fixes (B904, F401, C416)`

**`src/serving/api/auth/__init__.py`** — переписать целиком:

```python
from __future__ import annotations

import structlog

from src.serving.api.security import verify_api_key

from .key_rotation import KeyRotator, rotate_all_keys
from .manager import (
    DEFAULT_API_KEYS_FILE,
    DEFAULT_RATE_LIMIT_RPM,
    DEFAULT_USAGE_DB_PATH,
    ApiKeysConfig,
    AuthManager,
    KeyCreateRequest,
    TenantKey,
    get_auth_manager,
    get_current_tenant_id,
)
from .middleware import AuthMiddleware, build_auth_middleware, require_admin_key, require_auth

logger = structlog.get_logger()

__all__ = [
    "DEFAULT_API_KEYS_FILE",
    "DEFAULT_RATE_LIMIT_RPM",
    "DEFAULT_USAGE_DB_PATH",
    "ApiKeysConfig",
    "AuthManager",
    "AuthMiddleware",
    "KeyCreateRequest",
    "KeyRotator",
    "TenantKey",
    "build_auth_middleware",
    "get_auth_manager",
    "get_current_tenant_id",
    "require_admin_key",
    "require_auth",
    "rotate_all_keys",
    "verify_api_key",
]
```

**Что изменено:** удалены неиспользуемые `import secrets`, `import duckdb`. Сохранён `logger = structlog.get_logger()` (его используют `auth_package.logger.warning(...)` в `manager.py`, `middleware.py`, `key_rotation.py` — нельзя убирать), но перемещён ПОСЛЕ всех импортов чтобы не было E402.

**`src/serving/api/routers/admin.py`** — три места:

```python
    except KeyError:
        raise HTTPException(status_code=404, detail=f"API key '{key_id}' not found.") from None
```

Найти все `except KeyError:` блоки на строках 45-46, 60-61, 69-70 (или соответствующие после format), добавить `from None` в конце `raise HTTPException(...)`. Это fix B904.

**`src/serving/api/auth/key_rotation.py`** — заменить one-line:

```python
                return dict(rows)
```

вместо

```python
                return {key_id: requests_last_hour for key_id, requests_last_hour in rows}
```

(C416 — unnecessary dict comprehension, `rows` это `list[tuple[str, int]]`, `dict()` достаточно).

После этого коммита: `python -m ruff check src/ tests/` clean.

### Коммит 4 — `fix(src): mypy errors in cache, rate_limiter, logger, clickhouse, admin_ui, sql_builder + per-module override for semantic_layer`

**`pyproject.toml`** — после `[[tool.mypy.overrides]]` для flink_jobs добавить:

```toml
[[tool.mypy.overrides]]
module = "src.serving.semantic_layer.query.*"
disable_error_code = ["attr-defined"]
```

Обоснование: mixin pattern (`SQLBuilderMixin`, `NLQueryMixin`, `MetricQueryMixin`, `EntityQueryMixin`) обращается к атрибутам host class-а (`self._tenant_router`, `self.catalog`, `self._backend`, ...) — стандартный mypy не понимает mixin без Protocol-based typing, а это major refactor.

**`src/logger.py`** — заменить top:

```python
from __future__ import annotations

import logging
import os
from collections.abc import MutableMapping
from typing import Any

import structlog
from opentelemetry import trace


def add_otel_context(
    _logger: Any, _method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    span = trace.get_current_span()
    if not span.is_recording():
        return event_dict
    span_context = span.get_span_context()
    event_dict["trace_id"] = format(span_context.trace_id, "032x")
    event_dict["span_id"] = format(span_context.span_id, "016x")
    return event_dict
```

(было `def add_otel_context(_logger, _method_name: str, event_dict: dict) -> dict:` — тип `dict` не совместим с тем что `structlog.configure(processors=[...])` ожидает; `MutableMapping[str, Any]` — корректно).

**`src/serving/cache.py`** — заменить блок:

```python
try:
    import redis.asyncio as redis  # type: ignore[import-untyped,unused-ignore]
except ImportError:  # pragma: no cover
    redis = None  # type: ignore[assignment]
```

**`src/serving/api/rate_limiter.py`** — то же самое:

```python
try:
    import redis.asyncio as redis  # type: ignore[import-untyped,unused-ignore]
except ImportError:  # pragma: no cover
    redis = None  # type: ignore[assignment]
```

**`src/serving/backends/clickhouse_backend.py`** — два места.

В `_request` (строка ~49-50):

```python
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                decoded: str = response.read().decode("utf-8")
                return decoded
```

В `execute` (строка ~99-103):

```python
    def execute(self, sql: str, params: list | None = None) -> list[dict]:
        del params
        payload = self._request(sql, expect_json=True)
        data = json.loads(payload)
        rows: list[dict] = data.get("data", [])
        return rows
```

**`src/serving/api/routers/admin_ui.py`** — два места.

`_gather_health` (строка ~60-62):

```python
async def _gather_health(state) -> dict[str, object]:
    payload = await run_in_threadpool(state.health_collector.collect)
    result: dict[str, object] = payload.to_dict()
    return result
```

`_qps_last_minute` (строка ~81-89):

```python
    try:
        row = conn.execute(
            """
            SELECT COUNT(*)
            FROM api_sessions
            WHERE ts >= CURRENT_TIMESTAMP - INTERVAL '1 minute'
            """
        ).fetchone()
        requests_last_minute = row[0] if row else 0
```

**`src/serving/semantic_layer/query/sql_builder.py`** — `_get_tenant_schema` (строка ~19-26):

```python
    def _get_tenant_schema(self, tenant_id: str | None) -> str | None:
        resolved_tenant_id = self._resolve_tenant_id(tenant_id)
        schema: str | None = self._tenant_router.get_duckdb_schema(resolved_tenant_id)
        if schema is None:
            return None
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema) is None:
            raise ValueError(f"Invalid DuckDB schema '{schema}' for tenant '{resolved_tenant_id}'.")
        return schema
```

После этого коммита: `python -m mypy src/ --ignore-missing-imports` → `Success: no issues found in 90 source files`.

### Коммит 5 — `ci(security): trivy ignore-unfixed CVEs`

**`.github/workflows/security.yml`** — в job `trivy` шаге `Run Trivy scan` добавить `ignore-unfixed: true`:

```yaml
      - name: Run Trivy scan
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: agentflow-api:security-scan
          format: sarif
          output: trivy-results.sarif
          severity: HIGH,CRITICAL
          ignore-unfixed: true
          exit-code: "1"
```

Обоснование: CVE без доступного patch upstream блокируют CI без actionable пути починки. С `ignore-unfixed: true` gate срабатывает только на fixable findings → CI становится actionable. Пост-merge — T04 проверит остались ли actionable CVE и решит upgrade vs `.trivyignore`.

## Acceptance

- `python -m ruff check src/ tests/` → `All checks passed!`
- `python -m ruff format --check src/ tests/` → `183 files already formatted`
- `python -m mypy src/ --ignore-missing-imports` → `Success: no issues found in 90 source files`
- CI workflow `CI` job `lint` зелёный после push.
- CI workflow `Security Scan` job `trivy` либо зелёный, либо красный только на actionable (с fix-version) CVE — последнее → блокирует merge T01-T05, тогда сначала T04.
- Все 552 локальных теста проходят (минус `tests/unit/test_mcp_server.py` который требует `mcp` package — это T01).
- Diff по функциональным файлам (не format-only): `git diff --stat HEAD~5 HEAD -- ':!*.py' ':(glob)src/**/*.py' ':(glob)src/serving/api/auth/__init__.py' ':(glob)src/serving/api/routers/admin*.py' ...` показывает компактный набор изменений (без всплеска LOC от format).

## Notes

- НЕ трогать никакие файлы, кроме перечисленных. Format pass (Коммит 1) меняет ~75 файлов whitespace/quotes — это нормально, отдельный коммит чтобы review остальных был чистым.
- НЕ изменять `select`/`ignore` в `[tool.ruff.lint]` — только `per-file-ignores` блок.
- НЕ ставить `disable_error_code` на весь mypy — только targeted override для `semantic_layer.query.*`. Mixin attr-defined в других местах должен фейлить.
- Если ruff format в шаге 1 затронет файлы которых нет в текущем main (т.е. появились новые после `5631353`) — это норм, просто отформатировать и они пойдут в коммит.
- Если после format-pass появятся новые ruff errors (UP035 в `src/logger.py` после добавления `MutableMapping` import) — это уже обработано в Коммите 4 (`from collections.abc import MutableMapping`), но если что-то ещё всплыло — fix в том же коммите 3.
- Проверить локально перед push: `python -m ruff check src/ tests/ && python -m ruff format --check src/ tests/ && python -m mypy src/ --ignore-missing-imports`. Все три должны быть зелёные.
- `mcp` package не установлен в dev-env по умолчанию → `pytest tests/unit/` упадёт на коллекции. Это **отдельная** проблема (T01). Для верификации T00 можно использовать `pytest tests/unit/ --ignore=tests/unit/test_mcp_server.py` или `pip install mcp>=1.0`.
- Один PR = одна merge. Можно squash в один итоговый коммит на merge или сохранить 5 — на усмотрение.
