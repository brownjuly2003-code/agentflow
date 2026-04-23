# T09 — Terraform Apply: validate OIDC readiness or disable explicitly

**Priority:** P1 · **Estimate:** 2-4ч

## Goal

Понять, готов ли `Terraform Apply` к безопасному использованию, и либо получить green proof на non-prod path, либо временно disable-нуть workflow явно и с планом re-enable.

## Context

- Workflow: `.github/workflows/terraform-apply.yml`
- Historical run-ов сейчас нет.
- Workflow опасный по природе:
  - manual input `confirm=APPLY`,
  - `aws-actions/configure-aws-credentials`,
  - реальные tfvars,
  - stage/apply path.
- T05 audit не запускал workflow вслепую, чтобы не сделать accidental infrastructure change.

## Deliverables

1. Проверить repo vars/secrets prerequisites:
   - `AWS_TERRAFORM_ROLE_ARN`
   - `AWS_REGION`
   - наличие expected tfvars files для staging/non-prod.
2. Подтвердить, что OIDC role assumption реально работает на GitHub Actions.
3. Если safe non-prod path существует:
   - получить successful plan/apply proof для `staging`.
4. Если prerequisites отсутствуют:
   - добавить временный disable по правилу спринта (`if: false` + comment with date/ticket),
   - описать точный re-enable checklist.

## Acceptance

- Либо есть safe green proof для non-prod `Terraform Apply`,
- либо workflow явно disabled с комментарием и ссылкой на этот ticket.

## Notes

- Не запускать production apply ради аудита.
- Не оставлять manual-but-broken workflow в неопределённом состоянии.
