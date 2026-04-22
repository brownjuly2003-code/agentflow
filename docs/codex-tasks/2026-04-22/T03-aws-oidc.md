# T03 — AWS OIDC Terraform module

**Priority:** P1 · **Estimate:** 4-6ч

## Goal

Добавить Terraform-модуль для AWS IAM OIDC provider + IAM Role с trust policy на GitHub Actions, интегрировать в workflow `terraform-apply.yml`. Закрыть P1 release-readiness блокер.

## Context

- Репо: `D:\DE_project\` (AgentFlow)
- Workflow `.github/workflows/terraform-apply.yml` уже wired под OIDC pattern, но реальной AWS IAM Role нет
- Без роли `terraform apply` в CI невозможен без ручных long-lived credentials
- Terraform config живёт в `infrastructure/terraform/` (`dev.tfvars`, `prod.tfvars`, Flink job config, RDS, ALB, Glue)
- GitHub Actions OIDC issuer: `token.actions.githubusercontent.com`

## Deliverables

1. **Модуль** `infrastructure/terraform/modules/github-oidc/`:
   - `main.tf`:
     - `aws_iam_openid_connect_provider` для `token.actions.githubusercontent.com`, thumbprint актуальный
     - `aws_iam_role` с trust policy на `repo:<OWNER>/<REPO>:ref:refs/heads/main` + `repo:<OWNER>/<REPO>:environment:production` + `repo:<OWNER>/<REPO>:environment:staging`
     - `aws_iam_role_policy` с minimal permissions для ресурсов в корневом `infrastructure/terraform/` (прочитать существующие `.tf` файлы, собрать list of managed resources, сгенерить policy по необходимым actions)
   - `variables.tf`: `github_org`, `github_repo`, `role_name`, `allowed_branches` (list), `allowed_environments` (list)
   - `outputs.tf`: `role_arn`, `provider_arn`
   - `README.md`: назначение, inputs/outputs, bootstrap-инструкция

2. **Интеграция в корневой модуль** `infrastructure/terraform/oidc.tf`:
   ```hcl
   module "github_oidc" {
     source = "./modules/github-oidc"
     github_org = var.github_org
     github_repo = var.github_repo
     role_name = "agentflow-terraform-${var.environment}"
     allowed_branches = ["main"]
     allowed_environments = ["production", "staging"]
   }
   ```
   + добавить переменные в `variables.tf`, дефолты — в `dev.tfvars`/`prod.tfvars`

3. **Workflow** `.github/workflows/terraform-apply.yml`:
   - Шаг `aws-actions/configure-aws-credentials@v4` с:
     ```yaml
     role-to-assume: ${{ vars.AWS_TERRAFORM_ROLE_ARN }}
     aws-region: ${{ vars.AWS_REGION }}
     role-session-name: gha-terraform-${{ github.run_id }}
     ```
   - Убрать `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` из secrets если присутствуют
   - `permissions: id-token: write, contents: read` — обязательно

4. **Документация** `docs/operations/aws-oidc-setup.md`:
   - Prerequisites (AWS account, admin credentials для bootstrap)
   - Bootstrap шаги (первый `terraform apply` локально с админом, чтобы создать роль)
   - Настройка GitHub (Settings → Environments → production/staging, secrets vs vars, required reviewers)
   - Verify: как проверить что workflow использует OIDC (не long-lived keys)
   - Rotation: thumbprint актуальный на 2026-04, как обновить

## Acceptance

- `cd infrastructure/terraform && terraform init && terraform validate` успешен
- `terraform plan -var-file=dev.tfvars` выполняется без ошибок (может требовать admin credentials локально — это ожидаемо)
- Workflow `terraform-apply.yml` после merge не требует `AWS_ACCESS_KEY_ID` в secrets
- `docs/operations/aws-oidc-setup.md` читается и воспроизводим сторонним читателем
- `gh workflow view terraform-apply.yml` — `permissions.id-token: write` присутствует

## Notes

- НЕ применять `terraform apply` — только код и валидация плана. Реальный bootstrap — ручной шаг юзера
- Trust policy должна быть **branch-locked** (`ref:refs/heads/main`) + **environment-locked** (`environment:production`), НЕ global (`*`)
- Политика прав — minimal. Deny by default. Только actions что используют ресурсы в `infrastructure/terraform/*.tf`. Если роль нужна широкая — обосновать в PR description
- Thumbprint для OIDC provider — брать актуальный на момент выполнения из AWS docs (меняется редко, но проверить)
- Commit message: `feat(infra): add AWS OIDC role module for GitHub Actions Terraform apply`
