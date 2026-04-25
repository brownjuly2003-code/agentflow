# T20b — Fix iceberg REST catalog PermissionError on CI runner

**Priority:** P0 · **Estimate:** 2-4 часа · **Track:** Customer release unblock · **Supersedes:** T20 partial (`0a16298`)

## Goal

T20 (commit `0a16298`) попытался решить проблему `500 Server Error` от REST catalog через монтирование `/warehouse` как tmpfs. На GitHub Actions ubuntu-latest runner это даёт другую ошибку:

```
PermissionError: [Errno 13] Cannot create directory '/warehouse'.
Detail: [errno 13] Permission denied
```

То есть Codex поменял природу ошибки, но не закрыл. CI test-integration job всё ещё красный на main HEAD `5b57cf4`. Нужен фикс, который РЕАЛЬНО работает на GHA runner и **не маскирует проблему через skip**.

## Context

- Текущий test: `tests/integration/test_iceberg_sink.py::test_repo_default_config_writes_to_rest_catalog`
- Текущий fixture/setup: смотри `tests/integration/conftest.py` и `tests/integration/test_iceberg_sink.py` — что Codex добавил в `0a16298`. Скорее всего, попытался добавить tmpfs mount в `services:` блок ci.yml или в pyiceberg-rest container config.
- На GHA runner: services запускаются как Docker containers; **runner user не имеет root privileges** на host-уровне, поэтому tmpfs mounts с custom path требуют либо privileged: true, либо альтернативный путь.
- Локально (Windows) Docker Desktop работает с другим permission model — поэтому tmpfs может работать локально, но падать на CI.

Известные working patterns для iceberg-rest на GHA:

1. **Использовать /tmp/warehouse** вместо `/warehouse` — runner user имеет write access к `/tmp`. Передать через `CATALOG_WAREHOUSE` env.
2. **Использовать named Docker volume** вместо bind mount — Docker сам резолвит permissions.
3. **Run REST catalog container как `--user 0:0`** (root inside container) если image это поддерживает — пишет в любой path, runner не возражает на container internals.

## Deliverables

1. **Reproduce locally**: запустить test-integration setup как в CI (через `act` или вручную через `docker compose -f docker-compose.integration.yml up` если есть) — подтвердить, что текущий fix `0a16298` действительно ломается тем же `PermissionError` на Linux. Если локально работает — это объяснит, почему Codex считал что закрыто.
2. **Apply working fix** — выбрать из 3 patterns выше (или другой evidence-based) и применить:
   - Если patch №1 (`/tmp/warehouse`): обновить env в ci.yml services + соответствующий path в test fixture.
   - Если patch №2 (named volume): docker-compose-style volume в services блок (если GHA services support named volumes).
   - Если patch №3 (root user): добавить `options: --user 0:0` в services блок ci.yml.
3. **Run test 3 times back-to-back** на CI (через push с trivial change или manual workflow_dispatch на CI) — все 3 раза зелёный без flaky retries.
4. Один коммит `fix(integration): <approach> resolves iceberg-rest /warehouse permissions on CI runner`. В commit message — почему именно этот approach, что было tried (если другое).

## Acceptance

- CI job `test-integration` зелёный на main 3 пуша подряд (можно triggers через trivial commits или re-runs).
- Локально тот же тест зелёный (не сломали local dev).
- Test НЕ помечен `@pytest.mark.skip` или `@pytest.mark.skipif` — проблема решена, не замаскирована.
- В commit message — single-paragraph root cause.

## Notes

- **Не использовать `continue-on-error: true`** на test-integration job — broken-window anti-pattern.
- **Не делать xfail** на этот test — это test infra, не product feature.
- Если выяснится что fundamentally нельзя поднять REST catalog на GHA shared runner (например, требует privileged) — escalate: предложить вариант "перенести этот test в nightly с self-hosted runner или kind cluster", в commit message обосновать. Но сначала перепробовать все 3 patterns.
- Учти `0a16298` уже на main — НЕ делай revert, делай incremental fix поверх. Если revert нужен, обоснуй.
- Local Windows reproduction необязателен — если падает только на Linux GHA runner, фокус на Linux. Используй WSL2 или CI-only iteration.
- Помни: A06 dependency-profile contract enforced. test-integration profile = `test-sdk`. Если меняешь install line — обнови соответствующий профиль в `pyproject.toml` `[tool.agentflow.dependency-profiles.profiles.test-sdk]`. См. `feedback_a06_enforcement.md` урок.
