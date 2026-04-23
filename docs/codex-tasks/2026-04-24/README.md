# Codex tasks: DE_project follow-ups (2026-04-24)

Follow-up tickets created after the `2026-04-23` CI-repair sprint and audit sweep. Each file is an independent PR-sized task.

## Core follow-ups

| # | File | Priority | Estimate |
|---|------|----------|----------|
| T06 | [performance-workflows-baseline-repair.md](T06-performance-workflows-baseline-repair.md) | P1 | 3-5ч |
| T07 | [mutation-workflow-first-green-run.md](T07-mutation-workflow-first-green-run.md) | P2 | 2-4ч |
| T08 | [sdk-publish-workflows-release-proof.md](T08-sdk-publish-workflows-release-proof.md) | P2 | 2-3ч |
| T09 | [terraform-apply-oidc-readiness.md](T09-terraform-apply-oidc-readiness.md) | P1 | 2-4ч |

## Additional audit-created follow-ups

| # | File | Priority | Estimate |
|---|------|----------|----------|
| T10 | [ci-post-quickfix-red-jobs.md](T10-ci-post-quickfix-red-jobs.md) | P0 | 2-4ч |
| T11 | [e2e-compose-health-detection.md](T11-e2e-compose-health-detection.md) | P1 | 1-2ч |
| T12 | [staging-webhook-callback-reliability.md](T12-staging-webhook-callback-reliability.md) | P1 | 1-3ч |
| T13 | [gitignore-agentflow-pattern-hardening.md](T13-gitignore-agentflow-pattern-hardening.md) | P2 | 1-2ч |

## Notes

- `T06`-`T09` are the original post-T05 follow-ups referenced by the CI audit.
- `T10`-`T13` were added later by parallel audit work and should be treated as the same follow-up batch, not a separate sprint.
- Start with `T10` if the goal is to close the remaining red jobs immediately; `T13` is independent hygiene work and can run in parallel.
