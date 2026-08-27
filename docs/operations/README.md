# Operations index

> Updated: 2026-08-27. This page routes operators to the maintained procedure
> or reference that owns a task. It does not replace the
> [engineering status](../STATUS.md) or turn a recorded result into current
> readiness.

Start with the [documentation hub](../README.md) for the full corpus. For
routine local operation use the [operational runbook](../runbook.md); for a
production-shaped incident use the [on-call runbooks](../runbooks/README.md).
The tables below cover the more specialized material in this directory.

## Current procedures and controlled gates

These documents own commands, preconditions, or acceptance boundaries that an
operator may need now. A document that requires separate authorization remains
a procedure, not an authorization to run it.

| Need | Owning document | Boundary |
| --- | --- | --- |
| Rehearse the reserved E26 DuckDB scratch path | [E26 non-target scratch rehearsal](api-duckdb-non-target-scratch-rehearsal-e26-runbook.md) | `READY_NOT_AUTHORIZED`; use only in a separately authorized rehearsal |
| Configure Terraform's AWS identity | [AWS OIDC setup](aws-oidc-setup.md) | Repository and AWS owner inputs must already exist |
| Attach a production CDC source | [Production CDC source onboarding](cdc-production-onboarding.md) | Complete the decision record and no-go checks before rollout |
| Run or triage controlled fault injection | [Chaos runbook](chaos-runbook.md) | Preserve the severity and exit criteria |
| Resume CI-soak work | [CI-soak next-session runbook](ci-soak-next-session-runbook.md) | Live repository facts override copied handoff text; external actions still need authority |
| Connect coverage reporting | [Codecov setup](codecov-setup.md) | Distinguishes repository wiring from external service state |
| Back up, restore, or rehearse host loss | [Disaster recovery runbook](disaster-recovery.md) | Follow the data-preservation and drill boundaries |
| Recover dependencies after the recorded Colima lifecycle gap | [External dependency recovery gate](external-dependency-recovery-gate.md) | The recorded pass does not establish workload or production readiness |
| Operate Flink jobs | [Flink operator reference](flink-operators.md) | Detailed job and checkpoint guidance; general service triage stays in the operational runbook |
| Install or upgrade through Helm | [Helm deployment reference](helm-deployment.md) | Production values remain fail-closed until their owner inputs are supplied |
| Prepare a GitHub or registry release | [Publication checklist](publication-checklist.md) | A checklist does not authorize push, publish, or release actions |
| Exercise PostgreSQL control-plane guarantees | [Control-plane testing](testing-control-plane.md) | Requires the live database path described by the guide |
| Receive independent security-test evidence | [Third-party pen-test intake](third-party-pen-test-intake.md) | Intake criteria do not claim that an engagement or test exists |

## Active designs and reference material

These files explain a live design boundary or implementation topology. They
are inputs to later work, not general-purpose procedures.

| Material | Role | Operator boundary |
| --- | --- | --- |
| [API DuckDB persistence and recovery design](api-duckdb-persistence-recovery-design.md) | Preservation, rollback, and acceptance design plus its dated decision history | Status is `CAPABILITY_REHEARSAL_REQUIRED`; it is not an approved operator runbook |
| [CI-soak Compose foundation](ci-soak-compose-foundation.md) | Topology and historical implementation reference | Its runtime-status sequence is superseded; resume from the current CI-soak runbook above |
| [OpenSSF security posture](openssf-security-posture.md) | Scope and interpretation of free supply-chain posture signals | Neither Scorecard nor self-certification is a penetration test or attestation |

## Consumed and dated records

The following files preserve point-in-time outcomes and are **not current
instructions**. Do not execute consumed identities or infer present readiness
from an old PASS or blocker.

| Record | Preserved result | Current use |
| --- | --- | --- |
| [E24 non-target scratch rehearsal](api-duckdb-non-target-scratch-rehearsal-e24-runbook.md) | `CONSUMED_SCRATCH_REHEARSAL_BLOCKED` | Historical evidence only; do not execute or reuse |
| [Original non-target scratch rehearsal](api-duckdb-non-target-scratch-rehearsal-runbook.md) | `CONSUMED_TRANSPORT_BLOCKED` | Historical evidence only; do not execute or reuse |
| [External pentest evidence blocker, 2026-08-01](external-pentest-evidence-blocker-2026-08-01.md) | `BLOCKED_NO_ENGAGEMENT_OR_EVIDENCE` at the recorded audit | Use the current intake guide and engineering status for present truth |
| [npm environment approval verification, 2026-08-03](npm-environment-approval-2026-08-03.md) | Read-only PASS at the recorded identity | Evidence of that check only |
| [npm environment approval blocker, 2026-08-01](npm-environment-approval-blocker-2026-08-01.md) | `BLOCKED_ENVIRONMENT_ABSENT` before the later verification | Superseded point-in-time evidence |

## Maintenance contract

- List every other tracked Markdown file directly under `docs/operations/`
  exactly once in one of the three sections above.
- Classify by the document's declared status and authority boundary, not by a
  filename containing `runbook` or `gate`.
- Keep immutable results intact. When a procedure is superseded, add the
  replacement relationship before moving the old narrative to the archive.
- Run `tests/unit/test_docs_operations_index.py` and the documentation link
  gate after changing this directory.
