# T21 — v1.1.0-rc1 publish workflow smoke test

**Priority:** P1 · **Estimate:** 3-5 часов · **Track:** Customer release unblock

## Goal

Публичные `publish-pypi.yml` и `publish-npm.yml` workflows ещё ни разу не были зелёные на main. После A01 rename (root → `agentflow-runtime`, SDK → `agentflow`) существует риск, что publish pipeline сломан на уровне tag → build → registry. Прогнать release-candidate tag `v1.1.0-rc1` **в testPyPI / npm dry-run mode** и убедиться, что оба пакета публикуются корректно с новыми именами.

## Context

- `pyproject.toml` root: `name = "agentflow-runtime"`, `version = "1.0.1"`. Для publish нужно bump до `1.1.0rc1` (PEP 440 pre-release) или `1.1.0-rc1` если npm.
- `sdk/pyproject.toml`: `name = "agentflow"`. Тоже bump.
- Workflows: `.github/workflows/publish-pypi.yml`, `.github/workflows/publish-npm.yml` (проверить существование и trigger — вероятно `on: push: tags`).
- Настройки testPyPI: обычно env secret `TEST_PYPI_API_TOKEN`; если нет — сначала добавь поддержку dry-run (`twine check dist/*` без upload).
- npm dry-run: `npm publish --dry-run` — валидирует package без реальной публикации.

## Deliverables

1. Bump `pyproject.toml`, `sdk/pyproject.toml` (и `integrations/pyproject.toml` если нужен) до `1.1.0rc1`. Коммит `chore: bump to 1.1.0rc1 for publish smoke`.
2. Проверить, что publish workflows поддерживают **rc tags** и **dry-run mode**. Если нет — добавить:
   - `publish-pypi.yml`: шаг "dry-run build and twine check" перед upload; при tag match `v*-rc*` — upload в testPyPI вместо PyPI.
   - `publish-npm.yml`: `npm publish --dry-run` в отдельном шаге; при rc tag — upload c `--tag next` в npm (или skip upload если rc — спорный выбор, обсудить в commit message).
3. Запустить: `git tag v1.1.0-rc1 && git push origin v1.1.0-rc1`.
4. **Дождаться оба workflow зелёными.** Логи upload'а (или dry-run успех) — captured.
5. На testPyPI / npm проверить что пакеты визуально на месте, versions правильные.
6. Если были правки workflows — отдельный коммит `ci(publish): support rc tags and dry-run` перед tag.

## Acceptance

- Оба publish workflow зелёные на `v1.1.0-rc1`.
- `agentflow-runtime==1.1.0rc1` виден на testPyPI (или dry-run логи показывают артефакт под правильным именем).
- `agentflow==1.1.0-rc1` SDK виден на testPyPI (или dry-run).
- npm dry-run `@<scope>/agentflow-client` (или как у них называется npm пакет) — артефакт правильный.
- **Не** триггерить production PyPI / npm publish на rc.

## Notes

- Если публикация требует Trusted Publishing (OIDC) — проверь `.github/workflows/publish-pypi.yml` использует `pypa/gh-action-pypi-publish@...` с OIDC, без api-token (memory: T09 делал OIDC readiness для terraform, aналогичная тема).
- Если в процессе выяснится что SDK SDK `sdk/pyproject.toml` не готов к publish (нет `readme`, `authors`, `license`) — задокументировать в T22 migration guide (отдельная задача), **не** чинить в этом таске. Фокус T21 — именно workflows/pipeline, не contents.
- После зелёного rc: **НЕ** триггерить v1.1.0 production release. Это отдельное решение юзера — сначала T22 migration guide, потом продакшен tag.
