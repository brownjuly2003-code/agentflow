# T32 - Post-release external gates

**Status:** Local gates closed; AWS/prod CDC blocked on external inputs
**Priority:** P2
**Track:** Post-release operations / release evidence

## Goal

Close the remaining post-v1.1 external gates that could not be completed from
the local code-only session: Docker-backed verification, AWS OIDC Terraform
apply readiness, npm Trusted Publishing CLI readback, and production CDC source
onboarding approval.

## Current State

- Local code/docs changes for npm Trusted Publishing, the new npm package scope,
  production CDC onboarding docs, and SDK artifact policy are committed on
  `main`.
- No-Docker verification on 2026-05-01 passed:
  - `tests/unit`: 448 passed
  - `tests/property`: 15 passed
  - `.venv` integration slice without Docker: 200 passed, 3 skipped, 5 deselected
  - `.venv` e2e: 18 passed
  - TypeScript SDK: `npm ci`, audit, typecheck, 42 unit tests, build, pack dry-run
  - Runtime + SDK artifacts: build, `twine check`, and release artifact policy
  - `scripts/export_openapi.py --check` through project `.venv`
  - `scripts/generate_contracts.py --check`
  - `scripts/check_schema_evolution.py`
  - Bandit baseline diff: no new findings
- Docker Desktop was recovered on 2026-05-01 by stopping Docker Desktop,
  terminating the `docker-desktop` WSL distribution, and restarting Docker
  Desktop. `docker desktop status` returned `running`; `docker version` reported
  Docker Desktop 4.69.0 / Engine 29.4.0.
- Docker-backed gates passed on 2026-05-01:
  - `docker compose up -d redis`: Redis healthy.
  - Full suite: `.venv\Scripts\python.exe -m pytest -p no:schemathesis -q`
    with project-local `TMP`/`TEMP` and `--basetemp`: 741 passed, 4 skipped in
    393.84s.
  - Chaos smoke with the CI compose path: 3 passed in 16.71s.
  - Production API image build through `docker-compose.prod.yml`: pass.
  - Trivy image scan through `aquasec/trivy:0.68.1` with
    `--severity HIGH,CRITICAL --ignore-unfixed --exit-code 1`: 0 findings.
  - CDC compose integration: connectors reached `RUNNING`, and the gated
    Postgres/MySQL CDC capture test passed in 103.60s.
- The new npm package `@yuliaedomskikh/agentflow-client@1.1.0` is public.
  Trusted Publisher CLI readback now confirms provider `github`, repository
  `brownjuly2003-code/agentflow`, workflow `publish-npm.yml`, and no
  environment. One recovery code was accepted; usable saved recovery-code reserve
  is now 4.
- Terraform config sanity passed through `hashicorp/terraform:1.13.5`:
  `terraform init -backend=false` and `terraform validate`.
- AWS apply readiness remains blocked on missing external inputs: no AWS
  credentials are configured on this workstation, repo variables contain
  `AWS_REGION` only, `AWS_TERRAFORM_ROLE_ARN` is absent, and real
  `infrastructure/terraform/environments/staging.tfvars` and `prod.tfvars` are
  absent.
- Production CDC source onboarding remains blocked by the documented approval
  gate: the decision record does not yet contain source owner, secret owner,
  table scope, private network path, monitoring owner, or rollback owner.

## Scope

1. Restore Docker Desktop daemon health without changing repo code. Done.
2. Rerun Docker-backed local gates. Done:
   - `docker compose up -d redis`
   - full `python -m pytest -p no:schemathesis -q` with project-local temp/cache
   - chaos smoke if Docker remains stable
   - any Docker image/security gate required before push
3. Finish npm Trusted Publishing CLI readback only after the 2FA reserve is safe.
   Done:
   - use the active `npm-recovery-codes` skill
   - do not print tokens, OTPs, cookies, recovery codes, or auth URLs
   - run `npm trust list @yuliaedomskikh/agentflow-client --json --registry https://registry.npmjs.org/`
4. Complete AWS OIDC Terraform apply readiness. Blocked on external AWS account
   inputs:
   - create/apply the IAM role
   - add `AWS_TERRAFORM_ROLE_ARN`
   - provide real environment tfvars
   - re-enable `.github/workflows/terraform-apply.yml`
5. Start production CDC source onboarding only after the required decision record
   in `docs/operations/cdc-production-onboarding.md` is filled and approved.
   Not started; the approval record is still empty by design.

## Acceptance

- Docker daemon responds normally for the selected context. Done.
- Redis-backed full suite passes locally or any remaining failure is captured as
  a new specific task with reproduction evidence. Done: 741 passed, 4 skipped.
- npm Trusted Publishing readback confirms GitHub Actions provider, repository
  `brownjuly2003-code/agentflow`, workflow `publish-npm.yml`, and no
  environment. Done.
- AWS Terraform apply workflow is enabled only after role, variables, and tfvars
  exist. Preserved: workflow remains disabled because the role ARN and real
  tfvars do not exist yet.
- Production CDC is not enabled until the source owner, secret owner, table
  scope, private network path, monitoring owner, and rollback owner are
  recorded. Preserved: production CDC remains disabled.

## Notes

- Do not move or recreate the already-published `v1.1.0` tag.
- Do not push unless explicitly asked.
- Use explicit `git add <path>...`; never use `git add -A` or `git add .`.
- Keep local secret-note paths and secret values out of publishable docs.
