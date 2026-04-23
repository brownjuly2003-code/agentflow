# T17 - CLI scripts: make repo scripts runnable without implicit PYTHONPATH

**Priority:** P1 - **Estimate:** 1-2ч

## Goal

Сделать repo CLI scripts запускаемыми как direct file entrypoints в чистом editable env и в temp/git fixtures, без неявной зависимости от caller cwd или внешнего `PYTHONPATH`.

## Context

- TA02 audit на `a010a2d` (Python `3.11.13`, deps sha256 `e9fb9d0764134e3e8c21edcc6c3f7f98c85a20568c6c3b9536f997080c834c5f`) оставил 7 падений с общей причиной.
- Падают:
  - `tests/unit/test_contracts_in_sync.py::test_contracts_match_pydantic_models`
  - `tests/unit/test_schema_evolution.py::{test_schema_check_script_exits_zero_for_safe_change,test_schema_check_script_accepts_breaking_change_in_new_version_file,test_schema_check_script_treats_missing_base_ref_as_first_commit,test_schema_check_script_handles_first_commit_without_head_tilde_one}`
  - `tests/unit/test_security.py::test_rotate_keys_script_prints_plaintext_once_and_writes_hash`
  - `tests/integration/test_iceberg_sink.py::test_init_iceberg_script_creates_five_tables`
- Все subprocess-вызовы `python scripts/<name>.py ...` падают на `ModuleNotFoundError: No module named 'src'`.
- Затронутые scripts:
  - `scripts/generate_contracts.py`
  - `scripts/check_schema_evolution.py`
  - `scripts/rotate_keys.py`
  - `scripts/init_iceberg.py`
- `scripts/generate_contracts.py` уже вручную добавляет в `sys.path` только `sdk/`, но не repo root; остальные scripts не bootstrap-ят import path вообще.

## Deliverables

1. Выбрать единый способ bootstrap для repo scripts:
   - либо явное добавление repo root в `sys.path`,
   - либо переход на package/module entrypoints,
   - либо другой консистентный вариант без скрытого окружения.
2. Исправить все четыре затронутых script entrypoints так, чтобы они работали из subprocess в чистом env.
3. Получить зелёный прогон минимум для:
   - `tests/unit/test_contracts_in_sync.py`
   - `tests/unit/test_schema_evolution.py`
   - `tests/unit/test_security.py::test_rotate_keys_script_prints_plaintext_once_and_writes_hash`
   - `tests/integration/test_iceberg_sink.py::test_init_iceberg_script_creates_five_tables`

## Acceptance

- `python scripts/generate_contracts.py --check` работает из repo root в чистом editable env.
- `python scripts/check_schema_evolution.py ...` работает внутри temp git repo fixture без внешнего `PYTHONPATH`.
- `python scripts/rotate_keys.py ...` и `python scripts/init_iceberg.py ...` не падают на import этапе.
- Указанные 7 tests из TA02 становятся зелёными.

## Notes

- Не чинить это ad hoc через тестовый monkeypatch окружения; нужен рабочий production CLI path.
- Не разносить разные bootstrap-стратегии по разным scripts без причины: нужен один понятный контракт для repo entrypoints.
