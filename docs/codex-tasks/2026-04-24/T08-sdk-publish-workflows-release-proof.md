# T08 — SDK publish workflows: release proof for NPM and PyPI

**Priority:** P2 · **Estimate:** 2-3ч

## Goal

Доказать, что `Publish TypeScript SDK` и `Publish Python SDK` реально сработают на следующем SDK release event.

## Context

- Workflows:
  - `.github/workflows/publish-npm.yml`
  - `.github/workflows/publish-pypi.yml`
- Оба workflow trigger-ятся только на tag pattern `sdk-v*`.
- В репо сейчас есть только tags:
  - `v1.0.0`
  - `v1.0.1`
- Поэтому historical run-ов у обоих publish workflow сейчас нет.
- T05 intentionally не запускал publish workflows вручную, чтобы не публиковать артефакты без реального release.

## Deliverables

1. Проверить intended release process:
   - должен ли repo использовать `sdk-v*` tags,
   - или workflows должны слушать другой tag pattern.
2. Синхронизировать trigger strategy и release docs.
3. Добавить безопасный proof path:
   - dry-run/rehearsal steps,
   - release checklist,
   - или documented staging rehearsal без фактической публикации.
4. На следующем safe event получить зелёные run-ы для:
   - `Publish TypeScript SDK`
   - `Publish Python SDK`

## Acceptance

- Tag strategy documented and consistent with workflow triggers.
- Для обоих publish workflow есть понятный путь к green proof без accidental production publish.
- Следующий релиз проходит обе publish pipeline без surprise failures.

## Notes

- Не запускать `npm publish` / `twine upload` ради аудита.
- Если нужен отдельный dry-run workflow, делать это отдельным PR с явным naming.
