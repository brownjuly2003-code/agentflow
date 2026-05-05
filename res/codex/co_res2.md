# AgentFlow audit_kimi 2026-05-04 open items after 2026-05-05 local remediation

Date: 2026-05-05
Repo: `D:\DE_project`
Baseline: HEAD `10bc3c7`, 673 tracked files

Scope: H3/H4/H5/H6, M1/M2/M3/M4/M7/M8/M9, L6/L7 from `audit_kimi_04_05_26.md`.

Already treated as closed by the local remediation package: Docker editable install, `.dockerignore`, container healthcheck, pinned MinIO tags, Helm image tag `1.1.0`, request body size middleware.

Boundary: this report classifies local remediation potential and evidence gaps only. It does not recommend cloud execution, release publication, repository publication, or commercial procurement.

## Evidence Checked

- `helm/agentflow/values.yaml` still has `replicaCount: 2`, HPA enabled with `minReplicas: 2`, `ReadWriteOnce` PVC, DuckDB file paths under `/data`, and bcrypt API-key hashes.
- `config/serving.yaml` defaults to `backend: duckdb`; `src/serving/backends/__init__.py` supports `duckdb` and `clickhouse`, selected by config/env.
- `.github/workflows/terraform-apply.yml` still has both Terraform jobs disabled with `if: false`; it expects `vars.AWS_TERRAFORM_ROLE_ARN` and env-specific tfvars under `infrastructure/terraform/environments/`.
- `docs/operations/aws-oidc-setup.md` and `docs/release-readiness.md` record that only `AWS_REGION` was observed, `AWS_TERRAFORM_ROLE_ARN` is missing, env tfvars evidence is missing, and no real OIDC proof exists.
- `docs/operations/external-pen-test-attestation-handoff.md` records no external tester, scope, report, attestation, severity summary, remediation mapping, retest status, or owner.
- `.bandit` still skips `B608`; `pyproject.toml` still globally ignores Ruff `S608`; `python -m ruff check . --select S608` currently finds 26 `S608` sites.
- `python -m bandit -r src sdk --ini .bandit --skip B101,B311 -f txt` shows source-level `# nosec B608` suppressions are already present, but the global `.bandit` skip remains.
- `pyproject.toml` still has `disallow_untyped_defs = false`; a targeted mypy run with `--disallow-untyped-defs` over `src/serving src/quality` exposed many missing annotations before mypy hit a local module-resolution assertion.
- `.github/workflows/ci.yml` keeps `--cov-fail-under=60`; `codecov.yml` keeps patch coverage at 80%; current local `coverage.xml` shows line-rate `0.623`.
- `.github/workflows/security.yml` scans with Bandit/Safety/Trivy but does not generate SBOM artifacts.
- No workflow contains `cosign`, `actions/attest-build-provenance`, `slsa`, `syft`, `cyclonedx`, or an image registry signing/attestation step.
- API usage is still stored in DuckDB tables (`api_usage`, `api_sessions`); Kafka topic bootstrap exists for CDC/connect topics, not immutable API audit logs.

## Item Classification

### H3 - DuckDB in Kubernetes with RWO PVC and replicas > 1

- can fix locally now: Partially. A chart-only safety patch could force DuckDB mode to one replica, disable HPA for that mode, or add chart validation that rejects DuckDB with `replicaCount > 1`. This would reduce the immediate divergence risk in checked-in defaults.
- needs external owner/evidence: Yes for closure in a real environment. Need the actual runtime target, storage class semantics, selected serving backend, and observed pod/storage behavior from the operator.
- needs architecture decision: Yes. The unresolved decision is whether production serving is single-writer DuckDB, ClickHouse-backed serving, or another serving-store path. The code has ClickHouse support, but Helm defaults still run DuckDB-shaped storage.
- should stay documented risk: Yes until the production serving-store decision and runtime evidence exist. Local chart hardening alone does not prove multi-replica data consistency.

### H4 - Terraform execution workflow disabled / AWS OIDC evidence absent

- can fix locally now: Only documentation or guard consistency can be improved locally. The workflow already contains OIDC wiring shape and explicit disabled guards; removing those guards locally would not prove readiness.
- needs external owner/evidence: Yes. Missing evidence includes AWS account owner, OIDC role ARN, repository variable proof, secure env tfvars ownership, first successful OIDC role-assumption proof, reviewer, and rollback owner.
- needs architecture decision: No major architecture decision is visible. The repository already chose GitHub OIDC plus an S3/DynamoDB Terraform backend pattern.
- should stay documented risk: Yes. The current docs already keep this blocked; that should remain true until owner-provided evidence exists.

### H5 - External penetration test evidence absent

- can fix locally now: No. Internal audit docs and CI scans can be organized locally, but they cannot become third-party penetration-test evidence.
- needs external owner/evidence: Yes. Required evidence is external tester identity, scope, test window, method, report or signed attestation, severity summary, remediation mapping, retest state, and attestation owner.
- needs architecture decision: No. This is an evidence/assurance gate, not a code architecture decision.
- should stay documented risk: Yes. `docs/operations/external-pen-test-attestation-handoff.md` already sets the correct evidence boundary.

### H6 - DuckDB encryption-at-rest not proven

- can fix locally now: Partially. Local code/config could add an explicit DuckDB encryption-key path or document unsupported encrypted-DuckDB modes, but that would not prove production storage encryption.
- needs external owner/evidence: Yes for closure. Need evidence for the actual storage layer, key ownership, key rotation posture, and whether backups/snapshots inherit encryption.
- needs architecture decision: Yes. Decide whether regulated/production data may use DuckDB at all, or whether the serving path must use encrypted infrastructure or another backend.
- should stay documented risk: Yes until the storage/encryption decision and runtime evidence exist. Current code uses plain `duckdb.connect(...)` paths and Helm passes file paths only.

### M1 - Ruff globally ignores `S608`

- can fix locally now: Yes. Remove `S608` from global Ruff ignore and scope the remaining findings with per-file ignores or `# noqa: S608` only where identifier sources are validated. Current Ruff check reports 26 `S608` sites.
- needs external owner/evidence: No.
- needs architecture decision: No.
- should stay documented risk: No after the local lint policy is tightened. Until then, the global suppression is a local security-gate gap.

### M2 - Bandit globally skips `B608`

- can fix locally now: Yes. Remove `B608` from `.bandit` global skips and rely on source-local `# nosec B608` suppressions where justified. Existing source already has many local B608 suppressions; their syntax should be normalized to avoid noisy Bandit parsing warnings.
- needs external owner/evidence: No.
- needs architecture decision: No.
- should stay documented risk: No after the local Bandit policy is tightened. Until then, the global skip remains broader than necessary.

### M3 - mypy allows untyped defs

- can fix locally now: Yes, but it is a typing-hardening pass rather than a one-line config change. A targeted run over `src/serving src/quality` exposed missing annotations across routers, cache, rate limiter, analytics, backends, monitors, and catalog code.
- needs external owner/evidence: No.
- needs architecture decision: Mostly no. If the scope expands into query mixin host contracts, that separate mixin typing debt may need a design choice, but M3 itself is locally remediable.
- should stay documented risk: Yes until the stricter per-module typing gate is actually green. Do not mark it closed by changing config before annotation debt is fixed.

### M4 - Helm values contain bcrypt API-key hashes

- can fix locally now: Partially. The chart can support `existingSecret`/secret-reference mode and move demo hashes out of production-shaped defaults. That is a local Helm/template change.
- needs external owner/evidence: Yes for production closure. Need a named secret owner, approved secret source, rotation expectations, and evidence that production values do not carry checked-in key material.
- needs architecture decision: Yes. Decide the production secret-source pattern and rotation contract before the chart can claim a durable secret-management posture.
- should stay documented risk: Yes while checked-in defaults still contain hashes or while production secret ownership is unknown.

### M7 - No rollback workflow

- can fix locally now: Yes for CI/runbook mechanics. The staging workflow calls `scripts/k8s_staging_up.sh`; that script uses `helm upgrade --install --wait --timeout 5m --debug` without `--atomic`, and there is no rollback job or production rollback workflow.
- needs external owner/evidence: Yes for production readiness. Need release owner, rollback owner, target environment, and first successful rollback rehearsal evidence from the operator.
- needs architecture decision: No major architecture decision. This is release-operations workflow hardening.
- should stay documented risk: Yes until rollback ownership and rehearsal evidence exist. A local workflow change can improve mechanics but not prove operational readiness.

### M8 - Coverage gate remains 60%

- can fix locally now: Yes, but only with accompanying tests or scoped thresholds. Current CI uses `--cov-fail-under=60`; current local `coverage.xml` is about 62.3%, so raising the global floor to 75% immediately would not be evidence-based. A local fix can add core-module gates and test work for those modules.
- needs external owner/evidence: No.
- needs architecture decision: No. This is an engineering quality threshold decision, not system architecture.
- should stay documented risk: Yes until the selected higher gate is green in CI and documented consistently. Current 60% global floor is still intentional but weak.

### M9 - No immutable audit log

- can fix locally now: Partially. Code can be extended to dual-write API usage into an append-oriented audit sink interface, and Helm/Kafka topic bootstrap can define an `api_usage.audit` topic. That would only create the local mechanics.
- needs external owner/evidence: Yes for the word "immutable". Need owner-provided evidence for production Kafka retention, deletion permissions, long-term storage policy, and audit-log access controls.
- needs architecture decision: Yes. Decide the audit log system of record, retention model, schema, access policy, and whether DuckDB remains only queryable analytics while another sink is authoritative.
- should stay documented risk: Yes. Current DuckDB usage tables are mutable and local; they are useful telemetry but not an immutable audit trail.

### L6 - No SBOM generation

- can fix locally now: Yes. Add SBOM generation to the existing security/release workflow and keep the artifact as CI output. The security workflow already builds/scans the API image with Trivy, so SBOM generation fits the current local CI surface.
- needs external owner/evidence: No for generating CI artifacts. External evidence is only needed if a customer-facing supply-chain claim requires a specific registry or release artifact record.
- needs architecture decision: No. SPDX vs CycloneDX format is a tooling choice, not a system architecture blocker.
- should stay documented risk: No after a green CI artifact exists. Until then it remains a low-priority supply-chain gap.

### L7 - No signed container images

- can fix locally now: Not fully. There is no evident container-publication workflow or registry digest to sign; existing image builds are local CI/security/staging builds. A local skeleton would not prove signed distributed images.
- needs external owner/evidence: Yes if AgentFlow distributes container images. Need registry target, image digest, successful signature/attestation readback, and consumer verification instructions.
- needs architecture decision: Yes. Decide whether container images are a released artifact, which registry owns them, and whether signing uses keyless signing, native artifact attestation, or both.
- should stay documented risk: Yes as a low-priority supply-chain risk while container distribution is undefined. If no container image is published as a product artifact, this should be documented as not applicable rather than treated as an open release blocker.

## Practical Bucket View

can fix locally now:

- M1, M2, M3, M7, M8, L6.
- Partial local risk reduction only: H3, H6, M4, M9.

needs external owner/evidence:

- H4, H5.
- Also required for full closure of H3, H6, M4, M7, M9, L7.

needs architecture decision:

- H3, H6, M4, M9, L7.

should stay documented risk:

- H3, H4, H5, H6, M3, M4, M7, M8, M9, L7 until their stated gate is closed.
- M1, M2, L6 should not remain long-term documented risks because they are locally closable policy/tooling gaps.
