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

1. Принять финальную naming strategy для runtime repo и Python SDK:
   - `agentflow` остаётся distribution name/import path/CLI именем SDK,
   - root runtime repo получает отдельный distribution name (`agentflow-runtime`),
   - downstream metadata не переименовывает SDK в `agentflow-sdk` без отдельного product decision.
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

## Decision

- Зарезервировать distribution name `agentflow` за Python SDK.
- Переименовать root `pyproject.toml` package identity из `agentflow` в `agentflow-runtime`.
- Оставить import path `agentflow` и console script `agentflow` у SDK без изменений.
- Оставить `integrations/pyproject.toml` зависимостью от `agentflow>=...`, потому что integrations потребляют именно SDK surface.
- Сохранить tag split: repo/source releases продолжают `vX.Y.Z`, SDK registry publish остаётся на `sdk-vX.Y.Z`.

## Why This Is The Safer Split

- `integrations/`, examples и user docs уже завязаны на `from agentflow import AgentFlowClient`; это имя должно продолжать принадлежать SDK.
- Root editable install сейчас не предоставляет importable `agentflow` package, поэтому `agentflow` как runtime distribution name не несёт полезного public contract.
- Clean-venv probe показывает реальный конфликт: последний editable install забирает distribution identity `agentflow`; если после `sdk/` поставить root repo, `pip show agentflow` указывает на root repo, а `import agentflow` падает.
- Переименование SDK в `agentflow-sdk` увеличивает blast radius для downstream consumers и docs, но не даёт выигрыша по import-path/CLI compatibility.

## Migration Plan

### Phase 1 — Manifest Identity Split

- Обновить root `pyproject.toml`: `name = "agentflow-runtime"`.
- Оставить `sdk/pyproject.toml` как `name = "agentflow"` и не менять `sdk/agentflow/` import package.
- Не вводить второй live alias, который публикует root repo под `agentflow`: это сохраняет коллизию вместо её устранения.

### Phase 2 — Setup / Tests / Docs

- Обновить setup scripts и contributor docs так, чтобы dual editable install был официальным и deterministic после rename root dist.
- Удалить `sys.path.insert(.../sdk)` и аналогичные shims из tests/examples после того, как install contract станет стабильным.
- Оставить user-facing usage без изменений: `from agentflow import AgentFlowClient`, `agentflow --help`, `pip install agentflow` для published SDK.
- Любые repo-contributor references к root package identity перевести на `agentflow-runtime` только там, где речь именно про editable/runtime package metadata.

### Phase 3 — Release / Publish Coordination

- PyPI publish для SDK продолжает использовать distribution `agentflow`.
- Root runtime package, если вообще публикуется отдельно, публикуется только как `agentflow-runtime`.
- `scripts/release.py` и publish workflows продолжают считать `sdk-vX.Y.Z` canonical SDK tag pattern.
- Repo/source releases `vX.Y.Z` остаются отдельным каналом и не должны переиспользовать SDK distribution identity.

### Phase 4 — Integrations Rollout

- `integrations/pyproject.toml` сохраняет зависимость на `agentflow>=...`; rename там не нужен.
- После split убрать install-order assumptions из local setup и CI paths, где сейчас есть отдельный `pip install -e sdk/`.
- Закрыть follow-up `T08` через publish proof уже после manifest split, а не до него.

## Backwards-Compat Story

### Alias Window

- Не держать runtime alias `agentflow` параллельно с SDK even temporarily: такой alias сохраняет order-dependent collision.
- Compatibility window делать documentation-first: один release cycle явно помечать, что root editable install теперь регистрируется как `agentflow-runtime`, а `agentflow` зарезервирован за SDK.

### Deprecation Notice

- Добавить release note / changelog entry про rename root distribution identity.
- Обновить contributor/setup docs с коротким migration note для локальных окружений, где раньше использовали `pip show agentflow` после `pip install -e .`.
- Любые внутренние скрипты или проверки, читающие `importlib.metadata.version("agentflow")`, должны трактовать это как SDK version lookup, а не runtime repo version lookup.

### Clean-Environment Smoke Validation

- Поднять чистый venv и проверить оба порядка установки:
  - `python -m pip install -e . -e sdk/ -e ./integrations`
  - `python -m pip install -e sdk/ -e . -e ./integrations`
- В обоих случаях подтвердить:
  - `pip show agentflow` → SDK metadata,
  - `pip show agentflow-runtime` → root repo metadata,
  - `python -c "from agentflow import AgentFlowClient"` succeeds,
  - `agentflow --help` resolves to SDK CLI,
  - integrations import path работает без `sys.path` shims.

## Release Checklist Delta

- Добавить clean-venv dual-install smoke в release checklist и publish rehearsal.
- Проверять оба distribution identity отдельно: `agentflow` (SDK) и `agentflow-runtime` (root repo).
- Не считать release готовым, пока tests/examples всё ещё требуют `sys.path.insert(.../sdk)`.
- Включить в `T08` preflight шаги сборки и metadata-check для обоих пакетов до live `sdk-v*` tag push.

## Non-Goals

- Не переименовывать import package `agentflow`.
- Не переносить CLI `agentflow` с SDK на root repo.
- Не делать isolated rename одного manifest без docs/setup/release migration window.
