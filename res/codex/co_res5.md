# AgentFlow audit_kimi task 5: commit/PR split

Date: 2026-05-05
Repo: `D:\DE_project`
Baseline: HEAD `10bc3c7`, `673` tracked files. Bundle size and i18n key count are not applicable to this planning artifact.

Scope: H3/H4/H5/H6, M1/M2/M3/M4/M7/M8/M9, L6/L7 from `audit_kimi_04_05_26.md`, after the 2026-05-05 local remediation package.

Already closed/out of scope per task context: Docker editable install, `.dockerignore`, Docker healthcheck, pinned MinIO tags, Helm image tag `1.1.0`, request body size middleware.

Boundary: this is only a commit/PR split. It does not recommend deploy, Terraform execution, repository publication, registry publication, paid procurement, live-cluster mutation, or marking external gates complete without owner-provided evidence.

## Sources Integrated

- `audit_kimi_04_05_26.md` for the original H/M/L item list.
- `res/codex/co_res1d.md` for source-backed status and local evidence.
- `res/codex/co_res2.md` for local/external/architecture/risk classification.
- `res/codex/co_res3.md` for minimal implementation plans, likely files, verification, and rollback boundaries.
- `res/codex/co_res4.md` for external evidence boundaries.

## Split Principles

- Separate local code/config remediation from owner-evidence closure.
- Separate architecture decisions from implementation PRs.
- Do not combine unrelated gates just because they share CI.
- Serialize PRs that touch the same high-conflict files, especially `helm/agentflow/values.yaml`, `helm/agentflow/values.schema.json`, `helm/agentflow/templates/deployment.yaml`, `.github/workflows/*`, and auth/audit code.
- For implementation PRs, use commit order: failing focused test/check first, implementation second, docs/config sync last.

## Recommended Separate PRs

| Order | PR | Items | Why separate | Likely local closure |
|---:|---|---|---|---|
| 1 | SQL static-analysis gate tightening | M1, M2 | Ruff `S608` and Bandit `B608` cover the same SQL-string-construction risk and should be reviewed together. This PR should not be mixed with typing or coverage cleanup. | Yes, if Ruff/Bandit focused checks are green and suppressions are narrow/reviewed. |
| 2 | SBOM artifact generation | L6 | Small supply-chain CI artifact change; independent from signing/provenance and from security scanner findings. | Yes for local CI SBOM generation once a green artifact exists. |
| 3 | Staging rollback mechanics | M7 local part | Helm rollback/atomic behavior is release-operations logic and should stay separate from chart topology or secrets. | Partial: local staging safety only; production readiness still needs owner evidence. |
| 4 | First strict mypy slice | M3 | Typing work can touch broad Python surfaces and should be staged by module, starting with the smallest green slice. | Yes for the selected slice only. |
| 5 | Coverage gate/test uplift | M8 | Coverage threshold changes must be paired with tests. Current total coverage is about 62.3%, so a 75% global gate should not be bundled into unrelated remediation. | Yes only for a green scoped or raised threshold. |
| 6 | DuckDB Helm topology fail-closed | H3 local part | Chart topology is an architecture-sensitive Helm change. It likely conflicts with M4/H6 Helm edits, so do it as a dedicated PR. | Partial: prevents unsafe checked-in defaults; production closure still needs runtime/backend evidence. |
| 7 | API-key secret source support | M4 local part | Secret-management review should not be mixed with topology or encryption changes even though Helm files overlap. | Partial: chart can stop relying on production-shaped checked-in verifier material; production closure needs secret owner/source evidence. |
| 8 | DuckDB encryption mechanics | H6 local part | Runtime DB encryption touches connection paths and config; it depends on the decision that DuckDB remains allowed for the target data. | Partial: local encrypted connection path only; production storage/backups need owner evidence. |
| 9 | Immutable audit-log architecture record | M9 decision | The system-of-record, retention, access controls, and sink choice need a decision before code is added. | No code closure; enables a safe implementation PR. |
| 10 | Audit sink implementation | M9 local part | Auth/usage logging changes should follow the architecture record and stay separate from existing DuckDB analytics behavior. | Partial: local append-only sink mechanics; immutable production operation needs owner evidence. |
| 11 | Terraform OIDC/readiness evidence hygiene | H4 | This is an external readiness gate. Keep docs/preflight/backend hygiene separate from any live infrastructure action. | No external closure without owner evidence. |
| 12 | External pen-test evidence intake update | H5 | Evidence-only PR when owner-provided artifacts exist. Do not mix with internal scanner findings or code remediation. | No local closure without third-party evidence. |
| 13 | Container signing scope decision | L7 decision | There is no clear container publication artifact/digest to sign. First decide whether container images are release artifacts. | Either `not applicable` by owner decision or enables a future signing PR. |
| 14 | Container image signing/provenance workflow | L7 implementation | Only after PR 13 selects registry/digest/signing policy. Do not combine with L6 SBOM generation. | External/supply-chain closure only with owner-provided digest and signature readback evidence. |

## Suggested Commit Breakdown Inside PRs

### PR 1 - M1/M2 SQL static-analysis gates

1. Add or adjust focused SQL-builder tests that prove existing allowed SQL construction is validated.
2. Remove global Ruff `S608` ignore and Bandit `B608` skip.
3. Add narrow `# noqa: S608` / `# nosec B608` suppressions only where the reviewed SQL path is safe, with existing tests covering the justification.

Keep this as one PR because the same SQL sites and suppressions need one review context.

### PR 2 - L6 SBOM artifact generation

1. Add SBOM generation to the existing security workflow.
2. Upload SPDX or CycloneDX JSON as a workflow artifact.
3. Update release-readiness/publication docs only if they reference CI artifacts.

Keep separate from L7 because SBOM generation can close locally without a published image digest.

### PR 3 - M7 staging rollback mechanics

1. Add a failing/static check that detects missing Helm rollback/atomic behavior if the repo has script/workflow contract tests.
2. Add `--atomic` or equivalent staging rollback-on-failure mechanics and `helm history` diagnostics.
3. Update runbook text only for local/staging behavior.

Do not claim production rollback readiness from this PR.

### PR 4 - M3 first strict mypy slice

1. Select one small module slice, preferably `src/quality` first.
2. Add the per-module mypy strictness target for that slice.
3. Add annotations until the selected strict command is green.

Use later PRs for additional slices. Do not combine with broad runtime changes.

### PR 5 - M8 coverage gate/test uplift

1. Add tests for the selected core module(s) until the intended threshold is green.
2. Add or raise only the threshold that is already green locally.
3. Sync Codecov/CI/docs language so the selected threshold is not overstated.

Do not raise the global floor to 75% in the same PR unless the full suite is already above it.

### PR 6 - H3 DuckDB Helm topology fail-closed

1. Add a negative Helm render/schema test for DuckDB with multi-replica or HPA min replicas greater than one.
2. Change Helm defaults/validation to reject unsafe DuckDB writer topology or require ClickHouse for multi-replica serving.
3. Update staging values only if the schema requires an explicit backend value.

This PR reduces local chart risk but does not close production H3 without operator evidence.

### PR 7 - M4 API-key secret source support

1. Add Helm tests/render checks for `existingSecret` or secret-reference mode.
2. Add chart values/schema/template support for externally supplied API-key verifier material.
3. Move demo/test hashes into clearly test-scoped values or docs, not production-shaped defaults.

Keep separate from H3/H6 because secret ownership and review are different from topology/encryption.

### PR 8 - H6 DuckDB encryption mechanics

1. Add unit tests around encrypted DuckDB connection creation/config loading.
2. Add explicit encryption config and update the runtime `duckdb.connect(...)` paths selected for serving/auth/usage databases.
3. Document that existing database migration/backfill is not included.

Do not include real database migration, backup mutation, or production encryption claims.

### PR 9 - M9 audit-log architecture record

1. Record the audit log system-of-record choice, retention model, deletion controls, and access owner.
2. Define the event schema and whether Kafka, another append-only sink, or a managed logging system is authoritative.
3. State that existing DuckDB `api_usage` and `api_sessions` remain operational analytics, not immutable audit logs.

This should be docs/ADR only unless an owner decision already exists.

### PR 10 - M9 audit sink implementation

1. Add tests for audit event emission and failure behavior.
2. Add a disabled-by-default audit sink interface and wire API usage events to it.
3. Add optional Helm/config values for the selected sink only after PR 9 is accepted.

Keep Kafka topic bootstrap, retention controls, and production evidence out unless the architecture decision explicitly includes them.

### PR 11 - H4 Terraform OIDC/readiness evidence hygiene

1. Update evidence-intake docs and readiness checklists for required AWS OIDC artifacts.
2. Keep workflow execution guards in place while evidence is absent.
3. If Terraform backend syntax is modernized, keep it as validation-only code hygiene with `terraform init -backend=false` / `terraform validate` evidence.

Do not combine this with any live infrastructure execution or external closure claim.

### PR 12 - H5 external pen-test evidence intake

1. Update the handoff/readiness docs only when owner-provided third-party evidence exists.
2. Record scope, tester identity, dates, severity summary, remediation mapping, retest state, artifact location, owner, and reviewer.
3. Keep confidential report contents out of the repo; link only redacted/approved artifact references.

If evidence is still absent, no remediation PR is warranted beyond preserving the blocked status.

### PR 13 - L7 container signing scope decision

1. Decide whether AgentFlow distributes container images as release artifacts.
2. If no, record L7 as not applicable by owner decision.
3. If yes, record registry, image naming, digest owner, signing policy, provenance policy, and consumer verification expectations.

Do this before any signing workflow change.

### PR 14 - L7 signing/provenance workflow

1. Add workflow logic only to the actual future container publication path.
2. Sign or attest an owner-provided image digest according to the accepted policy.
3. Add verification docs for consumers and a readback check for the signature/attestation.

Keep this separate from L6 because signing has external artifact identity and owner-evidence requirements.

## Parallelism Guidance

Can run in parallel if owners coordinate paths:

- PR 1 (M1/M2), PR 2 (L6), PR 3 (M7), PR 11 (H4 docs/hygiene), and PR 12 (H5 evidence docs) mostly touch different files.
- PR 4 (M3) can run in parallel only if its selected module slice does not overlap H6/M9 code paths.
- PR 5 (M8) can run in parallel only if its tests do not overlap the active implementation PR's tests.

Should be serialized:

- PR 6 (H3), PR 7 (M4), and PR 8 (H6), because all likely touch Helm values/schema/templates.
- PR 8 (H6) and PR 10 (M9), because both may touch auth/usage DuckDB connection paths.
- PR 13 (L7 decision) before PR 14 (L7 signing workflow).
- PR 9 (M9 decision) before PR 10 (M9 implementation).

## Do Not Combine

- Do not combine H4/H5/L7 external evidence closure with local remediation code.
- Do not combine H3 DuckDB topology, H6 encryption, and M4 secret handling even though they share Helm files.
- Do not combine M3 typing with M8 coverage unless the exact same module/test slice is intentionally scoped and remains small.
- Do not combine L6 SBOM generation with L7 signing/provenance.
- Do not combine M9 audit-log implementation with a claim that logs are immutable in production.

## Minimal Execution Order

1. M1/M2 SQL static-analysis gates.
2. L6 SBOM artifact generation.
3. M7 local staging rollback mechanics.
4. M3 first strict mypy slice.
5. M8 scoped coverage/test uplift.
6. H3 DuckDB Helm topology fail-closed.
7. M4 API-key secret source support.
8. H6 DuckDB encryption mechanics only if DuckDB remains in production scope.
9. M9 architecture record, then M9 audit sink implementation.
10. H4/H5/L7 evidence-only or decision PRs only when owner evidence/decisions exist.

## Bottom Line

The locally closable work should be small PRs: M1/M2, L6, M7, M3, and M8. The architecture-sensitive work should be separate and mostly serialized: H3, M4, H6, and M9. External gates H4, H5, and L7 should not be mixed with implementation PRs and should remain blocked or conditional until owner-provided evidence or an owner decision exists.
