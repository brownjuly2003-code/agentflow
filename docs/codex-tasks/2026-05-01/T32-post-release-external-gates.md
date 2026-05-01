# T32 - Post-release external gates

**Status:** Open
**Priority:** P2
**Track:** Post-release operations / release evidence

## Goal

Close the remaining post-v1.1 external gates that could not be completed from
the local code-only session: Docker-backed verification, AWS OIDC Terraform
apply readiness, npm Trusted Publishing CLI readback, and production CDC source
onboarding approval.

## Current State

- Local code/docs changes for npm Trusted Publishing, the new npm package scope,
  production CDC onboarding docs, and SDK artifact policy are prepared in the
  working tree.
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
- Docker Desktop is running but both Docker contexts return daemon `500` or
  timeout, so Redis/full-suite, chaos/load, and Docker image gates were not run.
- The new npm package `@yuliaedomskikh/agentflow-client@1.1.0` is public and
  npm Trusted Publisher setup was verified in the package settings UI.
- Do not consume another npm recovery code until the recovery-code reserve is
  refilled or another valid second factor is available.

## Scope

1. Restore Docker Desktop daemon health without changing repo code.
2. Rerun Docker-backed local gates:
   - `docker compose up -d redis`
   - full `python -m pytest -p no:schemathesis -q` with project-local temp/cache
   - chaos smoke if Docker remains stable
   - any Docker image/security gate required before push
3. Finish npm Trusted Publishing CLI readback only after the 2FA reserve is safe:
   - use the active `npm-recovery-codes` skill
   - do not print tokens, OTPs, cookies, recovery codes, or auth URLs
   - run `npm trust list @yuliaedomskikh/agentflow-client --json --registry https://registry.npmjs.org/`
4. Complete AWS OIDC Terraform apply readiness:
   - create/apply the IAM role
   - add `AWS_TERRAFORM_ROLE_ARN`
   - provide real environment tfvars
   - re-enable `.github/workflows/terraform-apply.yml`
5. Start production CDC source onboarding only after the required decision record
   in `docs/operations/cdc-production-onboarding.md` is filled and approved.

## Acceptance

- Docker daemon responds normally for the selected context.
- Redis-backed full suite passes locally or any remaining failure is captured as
  a new specific task with reproduction evidence.
- npm Trusted Publishing readback confirms GitHub Actions provider, repository
  `brownjuly2003-code/agentflow`, workflow `publish-npm.yml`, and no environment.
- AWS Terraform apply workflow is enabled only after role, variables, and tfvars
  exist.
- Production CDC is not enabled until the source owner, secret owner, table
  scope, private network path, monitoring owner, and rollback owner are recorded.

## Notes

- Do not move or recreate the already-published `v1.1.0` tag.
- Do not push unless explicitly asked.
- Use explicit `git add <path>...`; never use `git add -A` or `git add .`.
- Keep local secret-note paths and secret values out of publishable docs.
