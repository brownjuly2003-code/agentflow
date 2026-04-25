# T20 — Fix iceberg REST catalog 500 in test-integration

**Priority:** P0 · **Estimate:** 2-4 часа · **Track:** Customer release unblock

## Goal

`tests/integration/test_iceberg_sink.py::test_repo_default_config_writes_to_rest_catalog` стабильно падает в CI job `test-integration` (`.github/workflows/ci.yml`). Диагностировать и починить, чтобы CI на main стал зелёным (кроме Load Test — он по отдельной задаче). Это блокер для customer release GO verdict.

## Context

Симптом в логах CI:

```
requests.exceptions.HTTPError: 500 Server Error: Server Error for url:
  http://localhost:8181/v1/namespaces/agentflow_rest_<random>/tables
pyiceberg.exceptions.ServerError: RuntimeIOException:
  Failed to create file: /warehouse/agentflow_rest_<random>/orders/metadata/00000-<uuid>.metadata.json
```

- REST catalog сервис (polaris/iceberg-rest-fixture или аналог) запускается в CI и слушает localhost:8181.
- `_create_table` в pyiceberg возвращает 500 — catalog server не может записать в `/warehouse/...` путь.
- Ошибка **не flaky** — воспроизводится на 2+ прогонах подряд (проверено 2026-04-24 runs 24874386545, 24874661911 — разные namespaces, одна и та же суть).
- Этот тест раньше не всплывал потому что CI падал на collection stage (ModuleNotFoundError после A01 rename). После hotfix 97a1902 CI дошёл до test-integration и тест начал стабильно падать.
- 184 из 185 integration-тестов при этом проходят — единичный тест, изолированный к REST catalog config.

Ключевые файлы для исследования:

- `tests/integration/test_iceberg_sink.py` (тест и его fixtures)
- `docker-compose.yml` и/или `docker-compose.e2e.yml` / `docker-compose.integration.yml` если есть — ищи сервис REST catalog
- `.github/workflows/ci.yml` test-integration job — проверь `services:` блок
- Проверь `/warehouse` — это volume mount или path внутри catalog container?

## Deliverables

1. **Root cause document** (1 абзац в commit message или `docs/perf/` если долгий). Варианты гипотез:
   - volume `/warehouse` не примонтирован в container REST catalog / permissions issue
   - catalog image версия сменилась (upstream breakage) — pin другую
   - test fixture не создаёт namespace path до create_table
   - GHA runner filesystem не writable для container user (UID mismatch)
2. **Fix:** либо docker-compose изменение, либо ci.yml services блок, либо fixture setup, либо сочетание.
3. Локальная reproduction: запустить test-integration под тем же setup, что CI (`docker compose up` нужный compose + `pytest tests/integration/test_iceberg_sink.py::test_repo_default_config_writes_to_rest_catalog -v`). Подтвердить зелёный 3 раза подряд.
4. Один коммит `fix(integration): <что конкретно> to unblock iceberg REST catalog in CI` + push.

## Acceptance

- CI job `test-integration` зелёный на новом HEAD.
- Локально тест зелёный 3 раза подряд — не flaky.
- Нет новых skipped тестов (не маскируй проблему через skip-if-ci).

## Notes

- **Не** добавлять `@pytest.mark.skip` или `continue-on-error`. Если тест нельзя запустить в CI без infra, это отдельное решение (перенос в nightly) и требует декларации в ADR, не молчаливый skip.
- Проверь `docs/codex-tasks/2026-04-23/T01..T19` — в T10 (`b9618e1`) чинили coverage floor + iceberg sink. Возможно, тест тогда не запускался вовсе. Git blame поможет.
- REST catalog — скорее всего `tabulario/iceberg-rest` или `projectnessie/nessie` — pin image tag на рабочий known-good commit, не :latest.
- Если причина — shared /warehouse volume state между тестами (namespace collision, cleanup gap), добавь autouse fixture-cleanup. Но сначала убедись что первая гипотеза не проще.
