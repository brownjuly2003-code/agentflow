# T26 — A05 helm values schema live validation on kind/staging

**Priority:** P2 · **Estimate:** 4-6 часов · **Track:** Operationalize Q2 decisions

## Goal

A05 (`4e9b0e3`) добавил JSON Schema валидацию helm values (`helm/agentflow/values.schema.json`) и unit test (`tests/unit/test_helm_values_contract.py`). Unit test проверяет schema формально; **live validation** (что `helm install` реально падает на invalid values и проходит на valid) не тестировался. Настроить это через kind cluster, зафиксировать как integration-test или E2E smoke.

## Context

- Schema файл: `helm/agentflow/values.schema.json`.
- Unit test: `tests/unit/test_helm_values_contract.py` (импортит yaml, проверяет что `values.yaml` матчит schema).
- Staging-deploy workflow (`.github/workflows/staging-deploy.yml`) использует kind cluster — pattern есть.
- `helm` CLI автоматически валидирует против `values.schema.json` при `helm install` / `helm lint` если файл в chart'е. **Нужно проверить**, работает ли это в текущем setup.

## Deliverables

1. **Reproduce локально (kind cluster):**
   ```bash
   kind create cluster --config k8s/kind-config.yaml --name agentflow-a05-test
   helm lint helm/agentflow -f k8s/staging/values-staging.yaml  # должен пройти
   helm install agentflow helm/agentflow -f k8s/staging/values-staging.yaml --dry-run  # проверка
   ```
2. **Создать invalid values fixture** — `tests/integration/fixtures/helm-values-invalid.yaml`:
   - Выбрать 2-3 нарушения schema: wrong type (e.g. `replicas: "two"` вместо number), unknown property (если schema additionalProperties=false), missing required field, value out of range.
3. **Integration test** — `tests/integration/test_helm_values_live_validation.py`:
   - Fixture: kind cluster (создать в `conftest.py` session-scope, teardown на сессии).
   - Test 1: `helm lint` на `values-staging.yaml` — 0 exit code.
   - Test 2: `helm lint` на `helm-values-invalid.yaml` — non-zero exit, stderr содержит expected schema violation message (для каждого из 2-3 нарушений).
   - Test 3: `helm install --dry-run` на invalid — non-zero exit.
   - Pytest mark: `@pytest.mark.integration @pytest.mark.kind` чтобы можно было skip локально без kind.
4. **CI wiring** — добавить новый job `helm-schema-live` в `.github/workflows/ci.yml` или в staging-deploy.yml. Требует kind + helm (обе есть в staging-deploy.yml).
5. **Обновить `tests/unit/test_helm_values_contract.py` docstring** — сослаться на integration test для live coverage.
6. Коммит(ы) по разумной логике: unit+integration test + CI wiring.

## Acceptance

- `pytest tests/integration/test_helm_values_live_validation.py -v -m integration` — 3 passed (с kind cluster up).
- Новый CI job зелёный на main.
- Invalid values реально отвергаются helm'ом (не проходят из-за other reasons — убедись, что error message именно schema-related).
- Test не занимает > 3 минуты на CI.

## Notes

- Если `helm lint` не валидирует schema автоматически (зависит от helm version — 3.11+ required) — проверь версию и pin в CI (`azure/setup-helm@v4.3.0` — тот же, что в staging-deploy.yml). Не меняй version без причины.
- Kind cluster cleanup — обязателен (autouse fixture с teardown), иначе CI runner забьётся.
- **Не** включать этот test в default `pytest tests/integration/`. Использовать explicit marker `-m kind` или pytest config чтобы по умолчанию skip без infra.
- Если выясняется, что `helm lint` на invalid values **не падает** (например, schema.json имеет `additionalProperties=true` и пропускает unknown fields) — это потенциальный A05 bug. Задокументируй в commit, **но не фикси в этом таске** — это сфера A05 revisit, открой отдельный ticket.
