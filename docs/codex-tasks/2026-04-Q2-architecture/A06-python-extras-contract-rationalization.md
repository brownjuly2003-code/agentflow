# A06 — Python extras contract rationalization

**Priority:** P2 · **Estimated effort:** 4-6 days

## Goal

Сделать один явный dependency-profile contract для runtime, tests, perf и integrations, чтобы CI/workflow install steps не drift-или от реальных import paths.

## Context

- Root `pyproject.toml` держит extras `dev`, `cloud`, `load`, `integrations`; рядом живёт отдельный subpackage `integrations/pyproject.toml`.
- TA04 показал системный drift:
  - `ci.yml:test-unit` тащит root `integrations` и отдельно `./integrations[mcp]`,
  - `ci.yml:perf-check` не дотягивает `cloud`,
  - `mutation.yml` ставит `integrations`, хотя по факту нужен `cloud`.
- Текущие quick fixes уже разъехались по follow-up tickets (`T06`, `T07`, `T10`), но корневой contract не формализован.

## Deliverables

1. Описать canonical dependency matrix:
   - какой workflow/profile какие extras обязан ставить,
   - какие extras mutually redundant,
   - где нужен subpackage install вместо root extra.
2. Синхронизировать package metadata и workflow install lines с этой матрицей.
3. Убрать известные over-install и under-install patterns.
4. Добавить maintainable verification path, чтобы новый workflow не гадал extras вручную.

## Acceptance

- Для каждого Python workflow есть documented install contract, выводимый из одной dependency matrix.
- `cloud`/`load`/`integrations` assumptions не живут в ad hoc knowledge по workflow-файлам.
- Новый job или local setup может выбрать правильный install profile без manual archaeology.

## Risk if not fixed

Следующие workflow и local reproductions продолжат падать на скрытых optional deps или будут платить за лишние install-ы, а team снова будет чинить это по одному job за раз.

## Notes

- Этот item добавлен по findings TA04.
- Координировать с `T06`, `T07`, `T10`, чтобы quick CI repair не был потерян при более глубокой rationalization.
