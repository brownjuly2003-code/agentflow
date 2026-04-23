# TA02 result

## Test suite catalog (venv: a010a2d, python: 3.11.13, deps sha256: e9fb9d0764134e3e8c21edcc6c3f7f98c85a20568c6c3b9536f997080c834c5f)

| Suite | Total | Passed | Failed | Errored | Skipped | Time | Notes |
|-------|-------|--------|--------|---------|---------|------|-------|
| `tests/unit/` | 360 | 354 | 6 | 0 | 0 | `67.24s` | Все 6 падений сводятся к direct script invocation: subprocess-запуски `scripts/*.py` не могут импортировать `src`. |
| `tests/property/` | 15 | 15 | 0 | 0 | 0 | `26.48s` | Полностью зелёный прогон. |
| `tests/contract/` | 7 | 6 | 0 | 0 | 1 | `36.45s` | `tests/contract/test_openapi_compliance.py` skipped: `schemathesis` отсутствует в audit env после документированного install. |
| `tests/sdk/` | 17 | 17 | 0 | 0 | 0 | `2.17s` | Полностью зелёный прогон. |
| `tests/e2e/` | 17 | 17 | 0 | 0 | 0 | `79.37s` | Docker Compose stack поднялся локально, полный e2e suite прошёл. |
| `tests/integration/` | 185 | 184 | 1 | 0 | 0 | `257.06s` | Единственный fail снова в subprocess-запуске `scripts/init_iceberg.py`, который не видит `src`. |
| `tests/chaos/` | 8 | 7 | 1 | 0 | 0 | `86.33s` | Kafka timeout path bubbles up как необработанный `RuntimeError`, вместо ожидаемого `replay_pending`. |
| `tests/load/` | 2 | 2 | 0 | 0 | 0 | `0.29s` | `pytest` собрал 2 теста из `run_load_test.py`, оба прошли. |

Итого: `611` тестов/проверок, `602 passed`, `8 failed`, `0 errored`, `1 skipped`.

## Failed/Errored test breakdown

| Suite | File:Line | Test | Failure type | Root cause (1 sentence) | Action |
|-------|-----------|------|--------------|--------------------------|--------|
| `unit` | `tests/unit/test_contracts_in_sync.py:19` | `test_contracts_match_pydantic_models` | `AssertionError (subprocess exit 1)` | `scripts/generate_contracts.py:21` импортирует `src.*`, но не добавляет repo root в `sys.path`, поэтому direct file execution падает с `ModuleNotFoundError: src`. | `pre-existing (T17)` |
| `unit` | `tests/unit/test_schema_evolution.py:367` | `test_schema_check_script_exits_zero_for_safe_change` | `AssertionError (subprocess exit 1)` | `scripts/check_schema_evolution.py:12` импортирует `src.*` без bootstrap repo root, поэтому script invocation из temp git repo завершается `ModuleNotFoundError: src`. | `pre-existing (T17)` |
| `unit` | `tests/unit/test_schema_evolution.py:464` | `test_schema_check_script_accepts_breaking_change_in_new_version_file` | `AssertionError (subprocess exit 1)` | `scripts/check_schema_evolution.py:12` импортирует `src.*` без bootstrap repo root, поэтому script invocation из temp git repo завершается `ModuleNotFoundError: src`. | `pre-existing (T17)` |
| `unit` | `tests/unit/test_schema_evolution.py:501` | `test_schema_check_script_treats_missing_base_ref_as_first_commit` | `AssertionError (subprocess exit 1)` | `scripts/check_schema_evolution.py:12` импортирует `src.*` без bootstrap repo root, поэтому script invocation из temp git repo завершается `ModuleNotFoundError: src`. | `pre-existing (T17)` |
| `unit` | `tests/unit/test_schema_evolution.py:542` | `test_schema_check_script_handles_first_commit_without_head_tilde_one` | `AssertionError (subprocess exit 1)` | `scripts/check_schema_evolution.py:12` импортирует `src.*` без bootstrap repo root, поэтому script invocation из temp git repo завершается `ModuleNotFoundError: src`. | `pre-existing (T17)` |
| `unit` | `tests/unit/test_security.py:524` | `test_rotate_keys_script_prints_plaintext_once_and_writes_hash` | `CalledProcessError` | `scripts/rotate_keys.py:6` импортирует `src.serving.api.auth` как file script без подготовки import path, поэтому CLI падает до выполнения логики ротации ключа. | `pre-existing (T17)` |
| `integration` | `tests/integration/test_iceberg_sink.py:147` | `test_init_iceberg_script_creates_five_tables` | `AssertionError (subprocess exit 1)` | `scripts/init_iceberg.py:5` импортирует `src.processing.iceberg_sink` без bootstrap repo root, поэтому subprocess не может создать таблицы и падает на `ModuleNotFoundError: src`. | `pre-existing (T17)` |
| `chaos` | `tests/chaos/conftest.py:401` | `test_replay_stays_pending_when_kafka_proxy_times_out` | `RuntimeError` | При удалённом toxiproxy proxy Kafka producer timeout (`_MSG_TIMED_OUT`) не переводится в ожидаемый `replay_pending`, а пробрасывается наружу как необработанное исключение и ломает HTTP request path. | `pre-existing (T18)` |

## Notes

- Аудит выполнен в отдельном `.venv-audit`, созданном через `uv venv --python 3.11`, потому что в системе из коробки были только `3.10`, `3.12` и `3.13`.
- После quick fix из TA01 локальный `tests/integration/` больше не падает на collection/import уровне по `pyiceberg`: suite реально исполняет `185` тестов и оставляет один предметный fail.
- Для затронутых файлов проверен diff `54e169e..0dde32a`; в T00 там были только форматирующие изменения, поэтому найденные падения классифицированы как `pre-existing`, а не `regression from T00`.
- Contract suite остаётся неполным даже после документированного install набора из TA02, потому что `schemathesis` не входит в эти extras; follow-up вынесен в `T19`.

## New tickets created

- `docs/codex-tasks/2026-04-24/T17-cli-scripts-import-bootstrap.md`
- `docs/codex-tasks/2026-04-24/T18-chaos-kafka-timeout-replay-pending.md`
- `docs/codex-tasks/2026-04-24/T19-contract-suite-schemathesis-install.md`
