# T02 — Staging Deploy: diagnostics + root-cause fix

**Priority:** P0 · **Estimate:** 3-5ч

## Goal

CI workflow `Staging Deploy` (`.github/workflows/staging-deploy.yml`) падает на шаге `Deploy staging` с `Error: resource Deployment/agentflow/agentflow not ready. status: InProgress, message: Available: 0/1` после 3-минутного timeout-а на `helm upgrade --install --wait`. Root cause неизвестен — pod logs не собираются. Нужно (a) добавить диагностику в `scripts/k8s_staging_up.sh`, чтобы причина была видна в логах CI, и (b) исправить актуальную причину.

## Context

- Workflow: `.github/workflows/staging-deploy.yml` — поднимает kind cluster (`helm/kind-action@v1.14.0` + `k8s/kind-config.yaml`), грузит образ, ставит Redis, запускает `bash scripts/k8s_staging_up.sh`.
- Скрипт строит образ через локальный inline `Dockerfile` (FROM python:3.11-slim, copy src+config, pip install requirements + bcrypt + `-e .`), грузит в kind, ставит Helm chart `helm/agentflow` с `k8s/staging/values-staging.yaml`, ждёт rollout.
- Helm chart `helm/agentflow/` закоммичен в `8bedb1d` (был раньше под `.gitignore` `AgentFlow*`).
- Последний failed run (push 5631353): `helm upgrade --install` зашёл, но `helm --wait --timeout 3m` сообщил `Deployment/agentflow/agentflow not ready. status: InProgress, message: Available: 0/1` → `context deadline exceeded` → exit 1. Шаг `Tear down staging` (с `if: always()`) выполняется, но логов pod-ов до teardown нет.
- Возможные причины (нужно проверить, не угадывать):
  - Pod в CrashLoopBackOff — миграции, отсутствует config, плохая команда uvicorn
  - Pod в ImagePullBackOff — образ не загрузился в kind (`kind load docker-image` мог отвалиться, есть fallback на `ctr import` но без проверки)
  - Readiness probe не проходит (`/v1/health` возвращает 503 пока depends on Redis/Kafka которых может не быть)
  - Resource limits в `values-staging.yaml` не подходят для kind на runner-е (CPU/memory request больше доступного)
  - Образ не находит `bcrypt` или другую runtime dep (хотя установка bcrypt отдельно в Dockerfile это проверяет)

## Deliverables

### Часть A — диагностика (PR Шаг 1)

1. В `scripts/k8s_staging_up.sh` добавить trap, который на failure (или при `helm` timeout) собирает:
   ```bash
   on_failure() {
     echo "==> FAILURE: collecting diagnostics"
     kubectl get all --all-namespaces || true
     kubectl describe deployment "$RELEASE_NAME" --namespace "$NAMESPACE" || true
     kubectl describe pod --namespace "$NAMESPACE" -l "app.kubernetes.io/instance=$RELEASE_NAME" || true
     for pod in $(kubectl get pods --namespace "$NAMESPACE" -l "app.kubernetes.io/instance=$RELEASE_NAME" -o name 2>/dev/null); do
       echo "--- logs $pod (current) ---"
       kubectl logs --namespace "$NAMESPACE" "$pod" --tail=200 || true
       echo "--- logs $pod (previous) ---"
       kubectl logs --namespace "$NAMESPACE" "$pod" --tail=200 -p || true
     done
     kubectl get events --namespace "$NAMESPACE" --sort-by='.lastTimestamp' | tail -50 || true
   }
   trap on_failure ERR
   ```
2. На `helm upgrade --install` команду — заменить `--wait --timeout 3m` на `--wait --timeout 5m` и добавить `--debug` (опционально, увеличивает шум, но даёт visibility).
3. В CI workflow `staging-deploy.yml` — добавить шаг ПЕРЕД `Tear down staging`:
   ```yaml
   - name: Capture diagnostics on failure
     if: failure()
     run: |
       kubectl get all --all-namespaces
       kubectl get events --all-namespaces --sort-by='.lastTimestamp' | tail -100
       for ns in agentflow default; do
         for pod in $(kubectl get pods -n "$ns" -o name 2>/dev/null); do
           echo "=== $ns/$pod ==="
           kubectl describe -n "$ns" "$pod" || true
           kubectl logs -n "$ns" "$pod" --tail=200 || true
         done
       done
   ```
4. Push PR с этой частью отдельно — это "instrumentation only" коммит, можно мержить даже если CI всё ещё красный (он становится debuggable). Имя коммита: `ci(staging): collect pod logs and events on deploy failure`.

### Часть B — root-cause fix (PR Шаг 2, после получения логов)

5. Запустить CI после части A — посмотреть собранные диагностики.
6. **Если можно воспроизвести локально** (есть Docker + kind): `bash scripts/k8s_staging_up.sh` с теми же `values-staging.yaml`. Иначе — итеративно через CI.
7. Исправить root cause:
   - Если CrashLoop из-за missing config — добавить в `values-staging.yaml` или в `helm/agentflow/templates/configmap.yaml`
   - Если ImagePullBackOff — починить `kind load docker-image` (возможно, нужно `--name` параметр или другой image tag)
   - Если readiness probe — выровнять `helm/agentflow/templates/deployment.yaml` probe с реальным `/v1/health` поведением
   - Если resource limits — снизить в `values-staging.yaml` (kind on GitHub runner: 7GB RAM, 2 CPU)
8. Коммит: `fix(staging): <конкретная причина — например, raise readiness probe initialDelay to 60s>`

## Acceptance

- **Часть A:** после merge — следующий failed CI run показывает в логах `kubectl describe pod` + pod logs (current и previous) + namespace events. CI всё ещё может быть красный, но теперь debuggable.
- **Часть B:** `Staging Deploy` workflow зелёный end-to-end на push в main. `Deploy staging` шаг отрабатывает без timeout-а, `Run rate-limit E2E against staging` и `Run remaining E2E suite against staging` зелёные.
- Локально (если есть kind + Docker): `bash scripts/k8s_staging_up.sh` поднимает stack за <5 мин и `curl http://127.0.0.1:8080/v1/health` возвращает 200.

## Notes

- НЕ убирать `--wait` — без него helm считает install успешным сразу после apply, и тесты будут падать на 503 от не-готового pod-а.
- НЕ увеличивать timeout до 10+ минут — это маскирует проблему. Корректное состояние: pod ready за 60-90 сек.
- Если root cause — отсутствие init/migration job-а — добавить Helm hook `pre-install` который ждёт DB ready перед apply deployment.
- `helm/agentflow/values.yaml` и `k8s/staging/values-staging.yaml` — посмотреть оба, override-ы могут конфликтовать.
- Если корневая причина — Redis dependency (deployment стартует до того как `agentflow-redis` ready), добавить `initContainer` который ждёт Redis. Но Redis уже apply-ится перед helm install, и `kubectl rollout status agentflow-redis` ждёт. Проверить именно эту последовательность.
- Backstop: если за 5 часов не получается зелёный staging-deploy — закрыть таск с конкретным root-cause findings и предложением (например, "перейти на minikube вместо kind", "уменьшить replicas до 1 + skipReadiness", "запустить тесты против local docker-compose вместо kind").
