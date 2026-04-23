# TA03 — T00 hardening functional review

**Priority:** P1 · **Estimate:** 1-2ч

## Goal

Просмотреть **функциональные** изменения коммита `0dde32a` (T00 lint/mypy/trivy hardening) — без whitespace-only ruff format pass — и проверить что ни одно из 9 targeted fixes не сломало runtime поведение.

## Context

- Коммит `0dde32a chore: T00 lint/mypy/trivy hardening` — 81 файл, ~1130/1059 lines.
- Из них ~75 файлов — pure ruff format (whitespace, кавычки, line collapsing).
- Функциональные changes — 9 файлов:
  - `pyproject.toml` (per-file-ignores + mypy override)
  - `.github/workflows/security.yml` (trivy ignore-unfixed)
  - `src/logger.py` (typed processor signature)
  - `src/serving/api/auth/__init__.py` (logger move + drop unused imports)
  - `src/serving/api/routers/admin.py` (B904 raise from None)
  - `src/serving/api/auth/key_rotation.py` (C416 dict over comp)
  - `src/serving/api/routers/admin_ui.py` (typed return + None-guard fetchone)
  - `src/serving/api/rate_limiter.py` + `src/serving/cache.py` (type:ignore optional redis)
  - `src/serving/backends/clickhouse_backend.py` (typed return)
  - `src/serving/semantic_layer/query/sql_builder.py` (typed schema)

## Deliverables

Для каждого функционального изменения — checkpoint в `audit/TA03-result.md`:

```markdown
## TA03 — T00 hardening functional review

### 1. src/serving/api/auth/__init__.py — logger move

**Изменение:** `logger = structlog.get_logger()` перенесён ПОСЛЕ всех import-ов (раньше был между ними); удалены unused `import secrets`, `import duckdb`.

**Risk:** `auth_package.logger.warning(...)` callers в `manager.py`, `middleware.py`, `key_rotation.py` — runtime late-binding (через `from src.serving.api import auth as auth_package`). Если import order изменился, ranges `auth_package.logger` может не существовать когда callers первый раз вызывают.

**Verification:**
- [ ] `grep -rn "auth_package.logger" src/` — найти все callers
- [ ] `python -c "from src.serving.api.auth.manager import AuthManager; m = AuthManager(...); m.<call that triggers logger>"` — runtime check
- [ ] Run `tests/unit/test_auth.py` — должны быть зелёные

**Verdict:** ok / regression / unclear (objection)

[... повторить для каждого из 9]
```

Конкретные проверки по файлам:

1. **auth/__init__.py logger move** — runtime late-binding check + auth tests
2. **admin.py B904 from None** — проверить что 404 для отсутствующих ключей не теряет structured log context
3. **key_rotation.py C416 dict(rows)** — проверить тип `rows` (если duckdb возвращает не tuple-compatible Row, dict() сломается); прогнать `tests/unit/test_auth.py`, `tests/integration/test_rotation.py`
4. **admin_ui.py None-guard fetchone** — edge case empty table; вызвать `_qps_last_minute` на пустой `api_sessions` table
5. **logger.py MutableMapping signature** — structlog config принимает; `tests/unit/test_telemetry.py` зелёные
6. **rate_limiter.py / cache.py type:ignore optional redis** — `pip uninstall redis` + import + RateLimiter/QueryCache fallback на in-memory
7. **clickhouse_backend.py casted return** — `tests/unit/test_clickhouse_backend.py` (если есть) или import smoke test
8. **sql_builder.py typed schema** — `tests/unit/test_sql_builder.py` если есть, или smoke import
9. **pyproject mypy override semantic_layer.query.*** — bonus: `mypy src/serving/semantic_layer/query/ --disable-error-code attr-defined --hide-error-codes` чтобы убедиться что override не маскирует другие error codes

Финальная таблица:

```markdown
| # | Файл | Изменение | Verdict | Если regression — ticket |
```

## Acceptance

- `audit/TA03-result.md` содержит 9 checkpoint-ов, каждый с verdict.
- Если найдена regression — ticket в `2026-04-24/` с минимальным repro + предложением fix.
- НЕ чинить regression в этом таске (только catalog + ticket).
- Если все 9 verdict-ов `ok` — явно зафиксировать «T00 hardening clean, no regressions found».

## Notes

- НЕ переделывать ruff format — это whitespace, не рассматривать.
- НЕ trigger-ить полный `tests/` run — это TA02. Здесь только targeted runtime checks для 9 файлов.
- Если runtime check требует Docker (test_rotation integration) — `requires Docker, deferred to TA02 / partial verdict`.
- Auth logger late-binding — самый рискованный change. Особое внимание ему. Если runtime fails — это P0, fix немедленно отдельным коммитом (не quick fix лимит TA01).
