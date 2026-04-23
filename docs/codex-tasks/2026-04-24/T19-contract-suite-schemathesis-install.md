# T19 - Contract suite: include schemathesis in the documented audit/dev install path

**Priority:** P2 - **Estimate:** 30-60м

## Goal

Убрать неявную частичность `tests/contract/`: documented audit/dev install должен либо реально запускать весь suite, либо явно документировать, что часть contract coverage optional.

## Context

- TA02 audit использовал документированный install:
  - `pip install -e ".[dev,integrations,cloud,load,llm]"`
  - `pip install -e "./integrations[mcp]"`
  - `pip install -e "./sdk"`
- После этого `tests/contract/` дал `6 passed, 1 skipped`.
- Skip причина:
  - `tests/contract/test_openapi_compliance.py:11`
  - `pytest.importorskip("schemathesis")`
  - `No module named 'schemathesis'`
- В результате advertised "full extras" env не исполняет весь contract surface и скрыто теряет OpenAPI property-based coverage.

## Deliverables

1. Решить, где должен жить `schemathesis`:
   - в `dev` extra,
   - в отдельном `contract` extra,
   - либо в workflow/documented one-off install с явной документацией.
2. Привести install path и документацию к выбранному контракту.
3. Получить либо full green `pytest tests/contract/`, либо явно задокументированную intentional partial mode.

## Acceptance

- Пользователь, повторяющий документированный contract/audit install, получает ожидаемый coverage contract без скрытого skip.
- `tests/contract/test_openapi_compliance.py` либо реально запускается, либо его optional status явно описан в docs/workflow.

## Notes

- Не оставлять skip как "молчаливую норму" без явного решения.
- Если выбран отдельный extra, его нужно встроить в соответствующие task/docs/workflow инструкции.
