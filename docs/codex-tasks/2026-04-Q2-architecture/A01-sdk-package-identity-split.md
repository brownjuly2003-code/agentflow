# A01 — SDK package identity split

**Priority:** P1 · **Estimated effort:** 2-3 weeks (**flag for project planning**)

## Goal

Развести package identity runtime-репо и Python SDK так, чтобы editable installs, publish flow и downstream integrations работали детерминированно.

## Context

- `pyproject.toml` и `sdk/pyproject.toml` сейчас публикуют один и тот же дистрибутив: `name = "agentflow"` `version = "1.0.1"`.
- Репо уже живёт с workaround-ами: тесты и примеры поднимают `sdk/` через `sys.path.insert(...)`, а setup/docs отдельно ставят `pip install -e sdk/`.
- `integrations/pyproject.toml` зависит от `agentflow>=1.0.1`, так что rename затронет publish contract и downstream consumers.
- Publish proof для SDK ещё не закрыт: см. `docs/codex-tasks/2026-04-24/T08-sdk-publish-workflows-release-proof.md`.

## Deliverables

1. Принять финальную naming strategy для Python SDK:
   - отдельный distribution name (`agentflow-sdk` или эквивалент),
   - совместимость по import path,
   - судьба CLI entrypoint `agentflow`.
2. Описать migration plan:
   - PyPI publish,
   - docs/setup scripts,
   - `integrations/` dependency metadata,
   - release/tag strategy.
3. Подготовить backwards-compat story:
   - alias window,
   - deprecation notice,
   - smoke validation на clean environment.
4. Обновить release checklist так, чтобы dual install `-e .` + `-e sdk/` больше не был order-dependent.

## Acceptance

- Runtime package и Python SDK больше не конкурируют за один и тот же installed distribution identity.
- Clean environment допускает совместную установку repo runtime, SDK и integrations без `sys.path` shims.
- Publish docs и workflow expectations синхронизированы с новой naming strategy.

## Risk if not fixed

Следующий consumer или CI path, который установит и runtime repo, и SDK, останется зависеть от порядка install-ов: imports и CLI могут резолвиться в неожиданный пакет, а release/publish координация продолжит быть хрупкой.

## Notes

- Blocked on release planning и сигнал от integration partners.
- Не делать rename как isolated quick fix без migration window.
