# T22 — Write v1.1 migration guide for A01 package split

**Priority:** P1 · **Estimate:** 2-3 часа · **Track:** Customer release unblock

## Goal

A01 (`87e5f8e`, 2026-04-23) переименовал root package `agentflow` → `agentflow-runtime`. SDK остался с чистым именем `agentflow`. Существующим пользователям (кто ставил `pip install agentflow` и получал runtime) теперь нужно мигрировать. Написать `docs/migration/v1.1.md` — чёткий, короткий, с примерами.

## Context

До v1.0.x:
- `pip install agentflow` → ставит root package, который и runtime и SDK (одно имя, одно распространение).
- `from agentflow import AgentFlowClient` → работает.

С v1.1.0 (после A01):
- Root project = `agentflow-runtime` (PyPI). Содержит backend API, pipelines, processing, serving.
- SDK = `agentflow` (PyPI). Содержит только client + retry + circuit breaker.
- `pip install agentflow` теперь ставит **только SDK** (не runtime!). Пользователи, которые запускали API локально через `pip install agentflow && uvicorn ...`, сломаются.
- `from agentflow import AgentFlowClient` продолжает работать (SDK экспортирует клиента).

См. дополнительные изменения в `docs/integrations.md`, `docs/product.md`, `sdk/README.md` (обновлены в A01 doc-supplement, landed 2026-04-24 в 97a1902).

## Deliverables

`docs/migration/v1.1.md` со следующими секциями:

1. **TL;DR** (2-3 строки, что делать каждому).
2. **What changed** — таблица: old → new, на каждом слое (PyPI name, import path, purpose).
3. **Who is affected** — 3 группы:
   - Только SDK users (ставили `pip install agentflow` чтобы писать агента) — **не affected**, `pip install agentflow` даёт клиент как и раньше.
   - Runtime operators (ставили `pip install agentflow` для запуска API) — **affected**, нужно `pip install agentflow-runtime`.
   - Monorepo contributors — **affected**, `pip install -e .` ставит runtime, `pip install -e ./sdk` — SDK отдельно.
4. **Migration steps** — по каждой группе:
   ```bash
   # before
   pip install agentflow
   # after (runtime user)
   pip install agentflow-runtime
   # imports не меняются — всё что было `from agentflow.X`
   # либо SDK (AgentFlowClient), либо runtime internals (src.*)
   ```
5. **Backwards-compatible imports** — что не меняется: `from agentflow import AgentFlowClient, AsyncAgentFlowClient`.
6. **Breaking imports** — если есть (проверь — возможно `from agentflow.processing import X` больше не работает без `agentflow-runtime`). Если нет — явно указать "No breaking imports — all public paths preserved".
7. **Pinning and lockfiles** — `requirements.txt`/`poetry.lock` users должны обновить `agentflow` → `agentflow-runtime` если нужен runtime; SDK users без изменений.
8. **Troubleshooting** — 2-3 common issues: `ModuleNotFoundError: agentflow.processing` (не установлен runtime), коллизия при `pip install agentflow agentflow-runtime` в одной env (должно работать, но проверь в контексте).

Плюс:

9. Обновить `CHANGELOG.md` раздел `[Unreleased]` → `[1.1.0]` с ссылкой на migration guide.
10. Обновить `README.md` quick-start: упомянуть migration guide для upgraders.

## Acceptance

- `docs/migration/v1.1.md` существует, читается ≤ 5 минут.
- Все 3 группы пользователей получают чёткий шаг.
- Проверено локально: `pip install agentflow-runtime` из testPyPI после T21 — работает на чистой venv (`python -c "from src.serving.api.main import app"` или `uvicorn src.serving.api.main:app`).
- Проверено локально: `pip install agentflow` из testPyPI даёт только SDK — `from agentflow import AgentFlowClient` работает, `from agentflow.processing import X` падает с `ModuleNotFoundError` (ожидаемо).

## Notes

- **Не** вводить deprecation shims в runtime. `pip install agentflow` → SDK (не warning о rename). Migration guide + CHANGELOG — достаточно communication.
- Если найдёшь публичный import path, который реально ломается (не просто internals), задокументируй в секции **Breaking imports** + FIX в коде (например, re-export через SDK). Но проверь реально ли он был публичный — если он был в `src.*` prefix, это internal, не ломаем.
- Не нужно переводить на русский. English — стандарт для migration guides в этом проекте.
