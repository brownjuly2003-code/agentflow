# v1.1.0 Release — User Action Checklist

> **Status (2026-05-23):** package versions OK (`pyproject.toml` 1.1.0,
> `sdk/pyproject.toml` 1.1.0, `sdk/agentflow/__init__.py:__version__`
> "1.1.0", `sdk-ts/package.json` 1.1.0, `integrations/pyproject.toml`
> 1.0.1 — fixed). Tag `v1.1.0` exists on commit `2c72387` but main is
> 96 commits ahead. Release IS blocked on 3 user-only web-UI actions.

Claude/CX не могут эти шаги выполнить — все три требуют MFA в браузере,
API key недоступен. Это ~5-7 минут твоего времени.

## Шаг 1 — PyPI Trusted Publishers (2 формы)

URL: https://pypi.org/manage/account/publishing/

В самом низу страницы — "Add a new pending publisher". **Owner = GitHub
username, не email.**

### Запись #1 — `agentflow-runtime`

| Поле                  | Значение                       |
|-----------------------|--------------------------------|
| PyPI Project Name     | `agentflow-runtime`            |
| Owner                 | `brownjuly2003-code`           |
| Repository name       | `agentflow`                    |
| Workflow name         | `publish-pypi.yml`             |
| Environment name      | *(оставить пустым)*            |

### Запись #2 — `agentflow-client`

| Поле                  | Значение                       |
|-----------------------|--------------------------------|
| PyPI Project Name     | `agentflow-client`             |
| Owner                 | `brownjuly2003-code`           |
| Repository name       | `agentflow`                    |
| Workflow name         | `publish-pypi.yml`             |
| Environment name      | *(оставить пустым)*            |

Если PyPI выдаст «Invalid GitHub user or organization name» — значит
вписан email, не username. `brownjuly2003-code` без `@gmail.com`.

## Шаг 2 — NPM token

URL: https://www.npmjs.com/settings/~/tokens

1. "Generate New Token" → **Granular Access Token** (рекомендуется) или
   классический Automation
2. Scope: publish для пакета **`@yuliaedomskikh/agentflow-client`**
   (актуально на 2026-05-23; верифицировано в `sdk-ts/package.json:2`).
   В npm UI выбрать scope `@yuliaedomskikh` и пакет
   `agentflow-client`.
3. Скопировать значение немедленно (показывается один раз)

## Шаг 3 — GitHub secret

URL: https://github.com/brownjuly2003-code/agentflow/settings/secrets/actions

1. "New repository secret"
2. Name: `NPM_TOKEN`
3. Secret: значение из Шага 2

После добавления `gh secret list -R brownjuly2003-code/agentflow` должен
вернуть `NPM_TOKEN`.

## После 3 шагов — сказать «готово»

Claude сразу сделает:

1. **Re-tag** `v1.1.0` на актуальный HEAD:
   ```bash
   git push origin :refs/tags/v1.1.0
   git tag -d v1.1.0
   git tag -a v1.1.0 -m "AgentFlow v1.1.0 — DV2.0 multi-branch demo merged"
   git push origin v1.1.0
   ```
   Это триггернёт `publish-pypi.yml` + `publish-npm.yml`.

2. Дождаться оба publish workflows зелёные (~3-5 минут).

3. Live-verify через WebFetch:
   - https://pypi.org/project/agentflow-runtime/1.1.0/ → 200
   - https://pypi.org/project/agentflow-client/1.1.0/ → 200
   - npm endpoint в зависимости от scope

4. Обновить memory: `v1.1.0 PUBLISHED 2026-05-23`.

## Тонкости

- `publish-pypi.yml` использует OIDC через `pypa/gh-action-pypi-publish@release/v1`.
  Без Trusted Publishers (Шаг 1) — upload падает с
  `trusted publisher not configured`.
- `publish-npm.yml` напрямую читает `secrets.NPM_TOKEN`.
  Без секрета — `npm publish` падает 403/EAUTH.
- Если PyPI вернёт «name taken» на `agentflow-client` — это значит за
  прошедшие 27 дней кто-то занял имя. Альтернативы из memory:
  `agentflow-py`, `agentflow-sdk`, `agentflow-python`, `agentflowclient`,
  `agentflow-core`, `agentflow-api`. Sweep:
  ```bash
  for n in agentflow-py agentflow-sdk agentflow-python agentflowclient \
           agentflow-core agentflow-api; do
    curl -sf https://pypi.org/pypi/$n/json -o /dev/null \
      && echo "$n: TAKEN" || echo "$n: FREE"
  done
  ```
  Если придётся менять — придётся также пересобрать тесты и
  `integrations/pyproject.toml` dep (см. `feedback_de_a06_enforcement`
  и `T30` history в memory).
