# T07 — Mutation workflow: получить первый зелёный run

**Priority:** P2 · **Estimate:** 2-4ч

## Goal

Получить первый успешный `workflow_dispatch` run для `Mutation Testing` или сузить scope так, чтобы это стало реалистично в отдельном PR.

## Context

- Workflow: `.github/workflows/mutation.yml`
- Исторических run-ов для workflow сейчас нет.
- Workflow heavy by design:
  - timeout `60` minutes,
  - `mutmut`,
  - editable install + extra deps.
- T05 intentionally не занимался mutation flow внутри общего audit-а, потому что это отдельный complex workflow.

## Deliverables

1. Запустить workflow вручную и снять первый failure point.
2. Если проблема в install/import path:
   - починить deps/install pattern.
3. Если проблема в объёме:
   - сузить target modules,
   - уменьшить количество тестов,
   - улучшить artifact/reporting,
   - сохранить полезность mutation score.
4. Добиться одного зелёного run-а или зафиксировать минимальный justified disable plan отдельным коммитом и отдельным ticket update.

## Acceptance

- Есть recent successful run для `Mutation Testing`, либо отдельное явно обоснованное решение о временном disable.
- Workflow укладывается в timeout и отдаёт artifact/report.

## Notes

- Не переносить heavy mutation investigation обратно в T05.
- Не выключать workflow молча.
