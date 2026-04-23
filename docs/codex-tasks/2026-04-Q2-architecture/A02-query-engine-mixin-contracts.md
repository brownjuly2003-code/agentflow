# A02 — Query engine mixin host contracts

**Priority:** P1 · **Estimated effort:** 1-2 weeks (**flag for project planning**)

## Goal

Убрать неявную host-class coupling в `src/serving/semantic_layer/query/` и вернуть типовую проверку query layer без broad `attr-defined` suppression.

## Context

- `src/serving/semantic_layer/query/engine.py` собирает `QueryEngine` из `SQLBuilderMixin`, `NLQueryMixin`, `EntityQueryMixin`, `MetricQueryMixin`.
- Эти mixin-классы напрямую читают host attributes вроде `self._tenant_router`, `self.catalog`, `self._backend`, `self._duckdb_backend`, `self._backend_name`.
- В `pyproject.toml` добавлен override `disable_error_code = ["attr-defined"]` для `src.serving.semantic_layer.query.*`, что подтверждает structural typing debt.
- TA03 не нашёл runtime regression, но текущая защита держится на blind spot в mypy, а не на явном contract.

## Deliverables

1. Принять target design для query layer:
   - Protocol-based host requirements,
   - или composition/service objects вместо mixin inheritance.
2. Описать dependency boundaries:
   - кто владеет catalog,
   - кто резолвит tenant context,
   - кто отвечает за backend execution.
3. Убрать broad mypy suppression и заменить её локально типизированным contract.
4. Добавить regression-proof test coverage на выбранный design boundary.

## Acceptance

- `src.serving.semantic_layer.query.*` проходит mypy без `disable_error_code = ["attr-defined"]`.
- Query layer не зависит от неописанных host attributes.
- Следующий rename/refactor shared attributes ловится типами или targeted tests до runtime.

## Risk if not fixed

Следующий hardening или refactor query engine снова сможет сломать `_backend`/`catalog`/`_tenant_router` только на runtime; type-checker этого не увидит, и debt будет накапливаться в самой чувствительной части serving path.

## Notes

- Это кандидат в next sprint: debt уже всплыл в T00/TA03 и легко регрессирует снова.
- Не решать точечными `cast()`/`# type: ignore` поверх текущей схемы.
