# A05 — Helm values contract validation

**Priority:** P1 · **Estimated effort:** 3-5 days

## Goal

Сделать contract для Helm values явным и fail-fast, чтобы missing required fields ловились до staging deploy.

## Context

- `helm/agentflow/` не содержит `values.schema.json`.
- `staging-deploy.yml` сейчас полагается на `helm lint helm/agentflow -f k8s/staging/values-staging.yaml`, что валидирует chart/template surface, но не даёт полного schema contract для embedded values blobs.
- В `helm/agentflow/values.yaml` default `secrets.apiKeys` не содержит `key_id`, хотя runtime auth/rotation path уже использует `key_id` как обязательный operational field.
- TA08 специально фиксирует staging fragility как recurring pattern, а не как разовый miss в `values-staging.yaml`.

## Deliverables

1. Добавить formal values schema для chart:
   - required fields,
   - types,
   - enum/shape там, где это реалистично.
2. Отдельно закрыть validation gap для embedded YAML blocks вроде `secrets.apiKeys` и `config.tenants`.
3. Встроить pre-install validation в deploy path так, чтобы missing required keys падали до rollout.
4. Документировать, какие runtime config changes требуют обновления chart contract.

## Acceptance

- `helm lint` или equivalent validation step падает до deploy, если `key_id` или другой required field отсутствует.
- Chart defaults и staging overrides синхронизированы с runtime config expectations.
- Следующий config drift в values проявляется как validation error, а не как staging failure.

## Risk if not fixed

Следующее изменение auth/config schema снова всплывёт только во время deploy, с потерей CI времени и поздней диагностикой уже на staging path.

## Notes

- Это кандидат в next sprint: проблема уже доказала способность регрессировать.
- Не ограничиваться только `key_id`; цель — целостный contract для chart values.
