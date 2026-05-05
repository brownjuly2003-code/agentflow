# AgentFlow audit_kimi task 4: external gate evidence boundary

Date: 2026-05-05
Repo: `D:\DE_project`
Baseline: HEAD `10bc3c7`, `673` tracked files. Bundle size and i18n key count are not applicable to this evidence-boundary artifact.

Scope: H3/H4/H5/H6, M1/M2/M3/M4/M7/M8/M9, L6/L7 from `audit_kimi_04_05_26.md`, after the 2026-05-05 local remediation package.

Already closed/out of scope per task context: Docker editable install, `.dockerignore`, Docker healthcheck, pinned MinIO tags, Helm image tag `1.1.0`, request body size middleware.

Boundary: this file does not run or recommend deploy, apply, push, live-cluster mutation, registry publication, paid services, external scans, or customer outreach. It only states which gates must remain incomplete unless an owner supplies acceptable evidence.

## Rule Applied

Do not mark an external gate complete from local repo analysis, local dry runs, modeled plans, internal reviews, disabled workflows, example configs, or verbal claims. Completion requires owner-provided evidence with an accountable owner, date, scope, artifact location, and reviewer who can inspect the artifact.

Acceptable evidence must be redacted before repo linkage. Do not record secrets, tokens, private hostnames, account IDs, raw customer data, production credentials, or confidential report contents directly in the repository.

## Evidence Sources Checked

- `audit_kimi_04_05_26.md:475-478`, `:484-492`, `:506-507` for the scoped item list.
- `res/codex/co_res1.md`, `res/codex/co_res1a.md`, `res/codex/co_res1d.md` for source-backed status and local command evidence.
- `res/codex/co_res2.md` for local/external/architecture/risk classification.
- `res/codex/co_res3.md` for minimal local implementation boundaries and rollback notes.
- `docs/operations/external-gate-evidence-intake.md` for owner-provided evidence intake rules.
- `docs/operations/aws-oidc-setup.md` for H4 evidence requirements.
- `docs/operations/external-pen-test-attestation-handoff.md` for H5 evidence requirements.
- `docs/release-readiness.md` for current blocked external-gate status.
- `docs/operations/cdc-production-onboarding.md`, `docs/pricing-validation-plan.md`, and `docs/perf/public-production-hardware-benchmark-plan.md` as adjacent examples of the same evidence-boundary pattern.

## Completion Status Matrix

| ID | External gate? | Owner-provided evidence currently present? | Completion status to record now | Evidence needed before external completion |
|---|---|---:|---|---|
| H3 | Yes, for production/runtime closure | No | Not complete. Local chart hardening can reduce risk, but cannot close the production topology gate. | Production serving-backend decision, operator-named runtime target, storage class/access-mode evidence, selected backend evidence, and observed pod/storage behavior. |
| H4 | Yes | No | Blocked. The Terraform workflow must stay treated as incomplete while apply jobs are disabled and AWS OIDC proof is absent. | AWS account owner, bootstrap operator, `AWS_TERRAFORM_ROLE_ARN` repo-variable proof, secure tfvars owner/location, approval to remove `if: false`, first apply run URL or transcript, CloudTrail `AssumeRoleWithWebIdentity` proof, reviewer, and rollback owner. |
| H5 | Yes | No | Blocked. Internal audits, CI scans, and AI-assisted reviews are not third-party penetration-test evidence. | External tester identity, scope, test window, method, redacted report or signed attestation, severity summary, remediation mapping, retest status, and attestation owner. |
| H6 | Yes, for production at-rest encryption closure | No | Not complete. Local code/config can add encryption mechanics, but production encryption cannot be claimed from that alone. | Storage/encryption owner, key ownership, rotation posture, encrypted runtime database proof, backup/snapshot encryption evidence, and decision on whether production DuckDB is allowed. |
| M1 | No | N/A | Local gate only. Do not require external owner evidence; mark complete only after config changes plus Ruff evidence are green. | Local proof such as removal of global `S608` ignore, reviewed scoped suppressions, and green `ruff --select S608`/test output. |
| M2 | No | N/A | Local gate only. Do not require external owner evidence; mark complete only after Bandit policy is narrowed and green. | Local proof such as removal of global `B608` skip, reviewed `nosec B608` suppressions, and green Bandit/diff output. |
| M3 | No | N/A | Local gate only. Not externally blocked, but also not complete until stricter mypy slice is green. | Local proof from selected strict mypy modules and any affected tests. |
| M4 | Yes, for production secret-management closure | No | Not complete for production. Local Helm support for external secrets would be partial only. | Named secret owner, approved secret source, rotation expectations, production values proof showing checked-in verifier material is not used, and reviewer acceptance. |
| M7 | Yes, for production rollback-readiness closure | No | Not complete for production. Local rollback mechanics or `--atomic` can improve staging safety but do not prove operational readiness. | Release owner, rollback owner, target environment, failed-release recovery procedure, successful rollback rehearsal evidence, run URL/transcript, and reviewer signoff. |
| M8 | No | N/A | Local quality gate only. Do not require external owner evidence; mark complete only when the chosen threshold is green with actual command output. | Local/CI coverage evidence for the selected global or scoped threshold, plus docs/config alignment. |
| M9 | Yes, for immutable audit-log closure | No | Not complete. Current DuckDB usage/session tables are mutable operational telemetry, not immutable audit evidence. | Audit log system-of-record decision, retention policy, deletion/alteration controls, access-control owner, separate sink evidence, first event proof, and reviewer signoff. |
| L6 | Usually no for CI SBOM generation; yes only for customer/release claims | No CI SBOM artifact is present | Not complete locally. Can be completed by adding a green SBOM artifact workflow; external evidence is only needed for a customer-facing release artifact claim. | For local closure: SBOM workflow artifact plus green CI evidence. For external release claim: owner-approved artifact location and release/digest mapping. |
| L7 | Yes if container images are distributed artifacts | No | Blocked or conditionally not applicable. Do not mark complete without a registry/digest owner and signed artifact proof; if no container image is published, document N/A by owner decision rather than "done." | Registry target, image digest, release owner, successful signature/attestation readback, consumer verification instructions, and decision on keyless signing/provenance policy. |

## Gates That Must Stay Blocked Now

- H4 AWS Terraform apply/OIDC: no role ARN, no real tfvars, disabled workflow guards, no first OIDC/apply proof.
- H5 external penetration test: no third-party tester/report/attestation/scope/severity/retest evidence.
- H3 production DuckDB/Kubernetes topology: no operator evidence proving safe production backend/storage behavior.
- H6 production at-rest encryption: no owner evidence proving encrypted runtime storage and backups.
- M4 production API-key secret management: checked-in hashes remain present and no production secret owner/source evidence exists.
- M7 production rollback readiness: no owner-named rollback rehearsal evidence.
- M9 immutable audit log: no separate immutable/protected sink evidence.
- L7 signed container images: no registry digest, signature, attestation, or distribution-scope owner evidence.

## Gates That Can Be Closed Locally Later

- M1 and M2 can close with local static-analysis policy changes plus green Ruff/Bandit evidence.
- M3 can close by staging stricter mypy coverage and proving the selected slice is green.
- M8 can close by adding tests or scoped thresholds until the selected coverage gate is green.
- L6 can close for local CI supply-chain posture once SBOM generation/upload is added and the artifact exists in a green workflow.

These local completions must not be used to imply H4/H5/H3/H6/M4/M7/M9/L7 external readiness.

## Insufficient Evidence Patterns

The following are useful local signals but must not close external gates:

- `terraform init -backend=false`, `terraform validate`, or a disabled Terraform workflow.
- Presence of `AWS_REGION` without `AWS_TERRAFORM_ROLE_ARN`, real tfvars ownership, and OIDC role-assumption proof.
- Helm render/lint output without operator evidence from the target runtime environment.
- Internal security audits, static analysis, Trivy/Bandit/Ruff output, or this AI-assisted report as a replacement for third-party pen-test attestation.
- Local DuckDB metadata checks for demo files as proof of production storage encryption.
- Checked-in examples, synthetic/modelled plans, dry-run docs, or verbal claims.
- Local benchmark or CI results as proof of production-hardware benchmark, production rollback rehearsal, signed released containers, or immutable audit-log operation.

## Practical Closeout Rule

For each external item, the release/readiness record should use one of these statuses only:

- `blocked: evidence absent`
- `blocked: owner decision absent`
- `accepted: owner evidence recorded at <artifact>`
- `not applicable: owner decision recorded at <artifact>`

Do not use `complete`, `done`, `closed`, `ready`, or customer-facing security/release language until the accepted evidence artifact is present and reviewable.

## Security Disclaimer

This is an AI-assisted evidence-boundary review, not a substitute for a professional security audit or third-party penetration test. It can help prevent false closure of gates, but production security and compliance claims still require accountable owner evidence and qualified review.
