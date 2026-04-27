# CI/Release Gates Audit

Дата: 2026-04-27  
Проект: `D:\DE_project` / `brownjuly2003-code/agentflow`  
HEAD на момент аудита: `4a13d36f9baa652cc0082ccbd04137d768f9929b` (`main`, `origin/main`)  
Tracked files: 597  
Scope: `.github/workflows`, publish/deploy jobs, contract generation, package publishing.

## Короткий вердикт

Релиз сейчас блокируется не общей CI-системой, а только теми publish job, которые запускаются при push release tag. Репозиторный уровень защиты отсутствует: `main` не protected, rulesets пустые, required checks не настроены. Поэтому большинство CI/deploy/security/perf/contract gates существуют как workflow checks, но не являются обязательным pre-release барьером: их можно обойти прямым push/tag push при наличии прав.

Production registry publish фактически ещё не доказан: `@agentflow/client`, `agentflow-client`, `agentflow-runtime` в публичных registry не найдены; последний production tag `v1.1.0` запускал publish workflows и оба упали. Текущий `v1.1.0` tag указывает на `1ee89a3`, то есть на 40 commits позади текущего HEAD.

## Что реально блокирует релиз

| Gate | Где | Что реально блокирует | Статус |
|---|---|---|---|
| Python package publish | `.github/workflows/publish-pypi.yml:5-101` | Запускается на `sdk-v*`, `v*-rc*`, `vX.Y.Z`; проверяет tag/version sync, собирает root + SDK distributions, делает `twine check`, на production tags публикует `agentflow-runtime` и `agentflow-client` через PyPI OIDC. | Блокирует только сам publish job после tag push. Не требует CI/E2E/security. |
| npm package publish | `.github/workflows/publish-npm.yml:5-91` | Запускается на те же tags; проверяет tag/version sync, делает `npm install`, `npm run build`, dry-run, потом `npm publish`. | Блокирует только npm publish job. `npm test` и `npm run typecheck` не запускаются. |
| Release metadata sync | `publish-pypi.yml:29-63`, `publish-npm.yml:24-60` | Tag должен совпадать с `pyproject.toml`, `sdk/pyproject.toml`, `sdk-ts/package.json`. | Реальный hard gate внутри publish workflows. |
| Main CI deployment record | `.github/workflows/ci.yml:207-231` | `record-deployment` требует `schema-check`, unit/integration, helm live validation, perf-check, terraform-validate. | Блокирует только DORA deployment marker, не tag release. |
| Staging deploy workflow | `.github/workflows/staging-deploy.yml:4-65` | На push в `main` поднимает KinD staging, helm lint, staging E2E. | Блокирует только этот workflow status. Не привязан к publish. |
| Terraform validate | `.github/workflows/ci.yml:189-205` | Проверяет `terraform fmt`, `init -backend=false`, `validate`. | Блокирует только CI job / DORA marker. Не production apply. |

Внешние настройки GitHub, проверенные через `gh api`:

- `branches/main/protection`: `Branch not protected`.
- `repos/.../rulesets`: `[]`.
- Environments: `production`, `staging`, `pypi`.
- `production` и `staging` имеют required reviewer, но `can_admins_bypass=true`.
- `pypi` environment существует, но protection rules пустые.

## Что можно обойти

| Обход | Почему возможен |
|---|---|
| Прямой push/tag push без зелёного CI | Нет branch protection, нет rulesets, нет required status checks. |
| Publish без `CI`, `Security Scan`, `E2E Tests`, `Load Test`, `Contract Tests`, `Staging Deploy` | `publish-pypi.yml` и `publish-npm.yml` не используют `needs` и запускаются отдельно на tag push. |
| RC release без реального upload | `v*-rc*` делает dry-run; npm явно пишет "no registry upload", PyPI TestPyPI upload пропускается, если `TEST_PYPI_API_TOKEN` пустой. |
| Contract/OpenAPI drift | `contract.yml` не запускает `scripts/export_openapi.py`; `docs/agent-tools/*.json` не проверяются; тест проверяет только уже задокументированный subset. |
| GitHub environment reviewers для staging/prod | `staging-deploy.yml` не объявляет `environment`; `terraform-apply.yml` объявляет environment только в disabled apply job. |
| Terraform production apply gate | Оба job в `.github/workflows/terraform-apply.yml` имеют `if: false`. Workflow вручную доступен, но ничего не применит. |
| Coverage upload failure | `codecov-action` в CI настроен с `fail_ci_if_error: false`; без branch protection даже Codecov status не обязателен. |
| Security findings при прямом tag push | Security workflow не является dependency publish workflows. Внутри Bandit raw exit заглушён `|| true`, hard gate реализует только `bandit_diff.py`. |

## Что сломано или сомнительно

### 1. Production publish сейчас не доказан

Проверки registry:

- `npm view @agentflow/client`: `E404 Not Found`.
- `python -m pip index versions agentflow-client`: no matching distribution.
- `python -m pip index versions agentflow-runtime`: no matching distribution.
- `gh release list`: есть GitHub releases только `v1.0.0` и `v1.0.1`; `v1.1.0` GitHub Release отсутствует.

Последние publish runs:

- `Publish Python Packages` на `v1.1.0` упал: старый workflow пытался `twine upload` с пустым `TWINE_PASSWORD`, получил `403 Forbidden`.
- `Publish TypeScript SDK` на `v1.1.0` упал на metadata gate: `sdk-ts/package.json version 1.1.0-rc1 does not match tag 1.1.0`.
- `v1.1.0-rc1` runs были зелёные, но это был smoke: npm dry-run only, PyPI TestPyPI upload был skipped без `TEST_PYPI_API_TOKEN`.

### 2. Локальный PyPI OIDC fix ещё не в `origin/main`

В рабочем дереве есть незакоммиченный фикс:

- `.github/workflows/publish-pypi.yml:16` добавляет `environment: pypi`.

Но `origin/main:.github/workflows/publish-pypi.yml` не содержит `environment: pypi`. Если PyPI Trusted Publisher настроен с environment `pypi`, текущий удалённый workflow всё ещё не предъявляет нужный environment claim. Новый tag должен указывать на commit, где этот фикс уже есть.

### 3. Текущий `v1.1.0` tag устарел

`v1.1.0` указывает на `1ee89a36e91d3894baa5e4e257154cd5614a3149`, а HEAD `main` - `4a13d36f9baa652cc0082ccbd04137d768f9929b`. Между ними 40 commits. Рерun старого tag не проверит и не опубликует текущую release line.

### 4. `scripts/release.py` не соответствует текущему publish gate

`scripts/release.py` обновляет только:

- `sdk/pyproject.toml`
- `sdk-ts/package.json`
- `sdk/agentflow/__init__.py`
- `sdk/CHANGELOG.md`

Но `publish-pypi.yml` для production tag проверяет ещё root `pyproject.toml`. Если root runtime version не обновлён вручную, Python publish падает до сборки. Скрипт также создаёт только `sdk-vX.Y.Z`, то есть это скорее standalone SDK release path, а не полный runtime+SDK release path.

### 5. OpenAPI generation gate фактически сломан

Проверка без записи файлов показала:

- `docs/openapi.json`: 6 paths.
- Live `app.openapi()`: 41 paths.
- `docs/openapi.json` `info.version`: `1.0.0`.
- `src/serving/api/main.py:237` тоже hardcodes FastAPI version `1.0.0`, при package version `1.1.0`.

`tests/contract/test_openapi_compliance.py` сравнивает только documented subset: берёт documented paths и проверяет, что они совпадают с live. Новые live endpoints не требуют обновления `docs/openapi.json`, поэтому stale OpenAPI проходит contract workflow. `scripts/export_openapi.py` существует, но вызывается только `make tools`; CI его не запускает и не делает drift check для `docs/openapi.json`, `docs/agent-tools/claude-tools.json`, `docs/agent-tools/openai-tools.json`.

### 6. Contract generation частично работает, но покрытие узкое

`python scripts/generate_contracts.py --check` проходит. Это хороший gate для `config/contracts/*.yaml`.

Слабые места:

- `contract.yml` не включает `scripts/export_openapi.py` и `docs/agent-tools/**`.
- `contracts/entities/**` существует и документирован как data-driven entity contract path, но не входит в `contract.yml` paths.
- `scripts/generate_contracts.py` генерирует только hardcoded `CONTRACT_SPECS`; добавление нового entity YAML не обязательно будет поймано этим gate.

### 7. Deploy gates больше похожи на smoke, чем на release controls

- `staging-deploy.yml` поднимает локальный KinD staging на GitHub runner; это полезный smoke, но не реальный external staging/prod deploy.
- `production`/`staging` GitHub environments с reviewers существуют, но `staging-deploy.yml` их не использует.
- `terraform-apply.yml` полностью disabled через `if: false`; production infra apply gate отсутствует.
- `deploy/fly/` есть, но workflow для Fly deploy/publish не найден.

### 8. Package publishing имеет partial-release риски

- Python workflow публикует `agentflow-runtime` и `agentflow-client` последовательно. Если первый upload succeeds, а второй fails, получится частичный release.
- npm и PyPI workflows независимы. Один registry может опубликоваться, второй упасть.
- `publish-npm.yml` использует `npm install`, а в `sdk-ts/` нет lockfile; publish build не воспроизводим строго.
- npm publish не запускает `npm test`; TypeScript `typecheck` script есть, но не используется в publish job.
- Runtime wheel содержит top-level package `src`, потому что root `pyproject.toml` задаёт `packages = ["src"]`. Это нетипично для package name `agentflow-runtime` и повышает риск import/collision confusion.
- `twine check dist/* sdk/dist/*` проходит, но root runtime artifacts дают warnings: missing `long_description` и `long_description_content_type`.

## Итоговая карта gates

| Категория | Реально hard-blocks? | Комментарий |
|---|---:|---|
| Branch protection / required checks | Нет | GitHub сообщает `Branch not protected`; rulesets пустые. |
| CI lint/unit/integration/perf/terraform validate | Нет для release | Блокирует только CI status и DORA marker. |
| Security Scan | Нет для release | Может падать на push/PR, но tag publish от него не зависит. |
| Contract Tests | Нет для release | Отдельный workflow; OpenAPI coverage неполное. |
| E2E / Staging Deploy / Load Test | Нет для release | Отдельные push workflows; не `needs` publish. |
| Publish Python Packages | Да, но только после tag push | Сейчас production proof red; OIDC environment fix локальный, не в `origin/main`. |
| Publish TypeScript SDK | Да, но только после tag push | Блокирует npm upload, но без tests/typecheck. |
| Terraform Apply | Нет | Workflow disabled. |
| GitHub environments | Частично | `pypi` без approval; staging/prod reviewers не подключены к активному deploy workflow. |

## Минимальный список исправлений перед следующим release tag

1. Закоммитить `environment: pypi` в `.github/workflows/publish-pypi.yml` до создания/переноса release tag.
2. Не rerun старый `v1.1.0`; создать новый release commit/tag на текущем HEAD после зелёных локальных/CI gates.
3. Явно связать publish workflows с доказанной зелёной release line: либо branch protection + required checks, либо release workflow, который перед upload запускает/проверяет CI, contract, E2E/security минимум.
4. Починить OpenAPI drift gate: CI должен генерировать OpenAPI/tools во временный каталог или запускать exporter с check-mode и падать при diff.
5. Привести `scripts/release.py` к реальному release path: full runtime+SDK version bump либо явно переименовать/задокументировать как SDK-only.
6. Добавить `contracts/entities/**` и `scripts/export_openapi.py`/`docs/agent-tools/**` в relevant contract paths.
7. Решить, является ли KinD staging deploy релизным gate. Если да - добавить `environment: staging` и required reviewers; если нет - не считать его release blocker.
8. Для npm publish заменить `npm install` на воспроизводимый процесс с lockfile или явно принять нерепродуцируемость; добавить `npm test`/`npm run typecheck` либо документировать, почему publish build достаточно.

## Выполненные проверки

- `git status --short`: до записи аудита уже были чужие изменения в `.github/workflows/publish-pypi.yml`, `docs/release-readiness.md` и audit files; этот аудит их не меняет.
- `gh api repos/.../branches/main/protection`: branch not protected.
- `gh api repos/.../rulesets`: `[]`.
- `gh api repos/.../environments`: `production`, `staging`, `pypi`; `pypi` без protection rules.
- `gh run list --workflow "Publish Python Packages"` / `"Publish TypeScript SDK"`: production `v1.1.0` failed, RC smoke green.
- `npm view @agentflow/client`: not found.
- `python -m pip index versions agentflow-client` / `agentflow-runtime`: not found.
- `python scripts/generate_contracts.py --check`: pass.
- In-memory `app.openapi()` vs `docs/openapi.json`: mismatch, 41 live paths vs 6 documented paths.
- `python -m twine check dist/* sdk/dist/*`: pass with root runtime metadata warnings.
