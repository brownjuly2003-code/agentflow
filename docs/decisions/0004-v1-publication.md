# ADR 0004: Freeze v1.0.0 for public publication

## Status

Accepted - 2026-04-20

## Context

By the end of the v15/v15.5 closeout cycle, AgentFlow had closed the release-blocking technical work:

- release verification for the checked-in code was green
- benchmark baseline and regression gate were documented
- public-facing docs (`api-reference`, `security-audit`, `competitive-analysis`) were present
- demo deployment assets existed for a lightweight hosted path

Remaining gaps were no longer code blockers. They were manual environment setup and post-release business work:

- GitHub environments and required reviewers
- AWS OIDC role wiring for Terraform apply
- production-hardware benchmark publication
- PMF and customer discovery follow-up

## Decision

Freeze the repository as `v1.0.0` for public GitHub publication and treat the remaining work as post-release follow-up rather than as blockers for the repository release itself.

This means:

- no further code-scope expansion for the initial public release
- publication work focuses on documentation, hygiene, and release assets
- future scope moves into `v1.1` or later instead of reopening the `v1.0.0` gate

## Consequences

### Positive

- The public repository can ship with a coherent story and documented evidence.
- The release boundary stays honest: technical readiness is separated from market validation.
- Future work can be prioritized as product follow-up instead of release churn.

### Negative

- Some manual setup remains outside the repository and must still be completed by the maintainer.
- Public readers will see an honest but incomplete production story around cloud credentials and GitHub environment setup.

### Follow-up

- Complete GitHub environment protection and AWS OIDC wiring.
- Publish benchmark evidence from production-like hardware.
- Use customer discovery work to decide the `v1.1` roadmap.
