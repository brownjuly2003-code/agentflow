# T02 — Version sync (pyproject + SDK)

**Priority:** P0 · **Estimate:** 20 мин

## Goal

Синхронизировать версии между `pyproject.toml`, Python SDK и TypeScript SDK до `1.0.1` (соответствует CHANGELOG и опубликованному GitHub release).

## Context

- Репо: `D:\DE_project\` (AgentFlow)
- `pyproject.toml` содержит `version = "0.1.0"`
- `CHANGELOG.md` и опубликованный GitHub release — `v1.0.1`
- `sdk/agentflow/__init__.py` содержит `__version__ = "1.0.0"`
- `sdk-ts/package.json` — проверить текущее значение

Рассинхрон версий ломает `pip show agentflow`, сбивает SDK consumers и выглядит непрофессионально в published release.

## Deliverables

1. `pyproject.toml`:
   ```toml
   version = "1.0.1"
   ```
2. `sdk/agentflow/__init__.py`:
   ```python
   __version__ = "1.0.1"
   ```
3. `sdk-ts/package.json`:
   ```json
   "version": "1.0.1"
   ```
4. Если есть `src/agentflow/__init__.py` с версией — обновить туда же
5. Новый тест `tests/unit/test_version.py`:
   - Читает версию через `importlib.metadata.version("agentflow")`
   - Сравнивает с `agentflow.__version__`
   - Обе должны сходиться
6. Один коммит `chore: sync package versions to 1.0.1 across pyproject and SDKs`

## Acceptance

- `python -c "from agentflow import __version__; print(__version__)"` → `1.0.1`
- `pip install -e .` успешен, `pip show agentflow` → `Version: 1.0.1`
- `cat sdk-ts/package.json | jq .version` → `"1.0.1"`
- Новый тест `tests/unit/test_version.py` зелёный
- `make test` зелёный

## Notes

- НЕ поднимать до `1.1.0` — это patch-sync, не новый release
- НЕ трогать CHANGELOG (там уже корректно)
- Если в `sdk-ts/` есть `package-lock.json` — обновить через `npm install` после правки package.json
