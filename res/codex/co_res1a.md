# AgentFlow: remaining audit items after local remediation package

Date: 2026-05-05
Project: `D:\DE_project`
Baseline: HEAD `10bc3c7`, repo file count observed `89838`. Bundle size and i18n key count are not applicable to this research-only artifact.
Scope: `audit_kimi_04_05_26.md` items H3/H4/H5/H6, M1/M2/M3/M4/M7/M8/M9, L6/L7.
Already out of scope per prompt: Docker editable install, `.dockerignore`, Docker healthcheck, pinned MinIO tags, Helm image tag `1.1.0`, request body size middleware.

No deploy, apply, push, live-cluster, paid, or commercial-service actions were performed or proposed here.

## Primary sources checked

- Kubernetes Persistent Volumes access modes: https://kubernetes.io/docs/concepts/storage/persistent-volumes/
- Kubernetes StatefulSets stable storage: https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/
- Kubernetes Deployments and rollout behavior: https://kubernetes.io/docs/concepts/workloads/controllers/deployment/
- Kubernetes rolling update and rollback task: https://kubernetes.io/docs/tasks/run-application/update-deployment-rolling/
- Kubernetes Secrets good practices: https://kubernetes.io/docs/concepts/security/secrets-good-practices/
- Kubernetes auditing: https://kubernetes.io/docs/tasks/debug/debug-cluster/audit/
- Kubernetes images and digest guidance: https://kubernetes.io/docs/concepts/containers/images/
- Kubernetes signed artifacts and SBOM verification: https://kubernetes.io/docs/tasks/administer-cluster/verify-signed-artifacts/
- Helm rollback and upgrade command docs: https://helm.sh/docs/helm/helm_rollback/ and https://helm.sh/docs/helm/helm_upgrade/
- GitHub Actions OIDC docs: https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-cloud-providers
- Terraform S3 backend docs: https://developer.hashicorp.com/terraform/language/backend/s3
- DuckDB concurrency docs: https://duckdb.org/docs/stable/connect/concurrency
- DuckDB 1.4 encryption announcement and implementation note: https://duckdb.org/2025/09/16/announcing-duckdb-140.html and https://duckdb.org/2025/11/19/encryption-in-duckdb
- Ruff `S608`: https://docs.astral.sh/ruff/rules/hardcoded-sql-expression/
- Ruff per-file ignores: https://docs.astral.sh/ruff/settings/#lint_per-file-ignores
- Bandit `B608`: https://bandit.readthedocs.io/en/latest/plugins/b608_hardcoded_sql_expressions.html
- mypy config docs: https://mypy.readthedocs.io/en/stable/config_file.html
- pytest-cov config docs: https://pytest-cov.readthedocs.io/en/latest/config.html
- Codecov status docs: https://docs.codecov.com/docs/commit-status
- OWASP ASVS 5.0.0 V13/V14/V16: https://raw.githubusercontent.com/OWASP/ASVS/v5.0.0/5.0/en/0x22-V13-Configuration.md, https://raw.githubusercontent.com/OWASP/ASVS/v5.0.0/5.0/en/0x23-V14-Data-Protection.md, https://raw.githubusercontent.com/OWASP/ASVS/v5.0.0/5.0/en/0x25-V16-Security-Logging-and-Error-Handling.md
- OWASP WSTG penetration testing methodology: https://owasp.org/www-project-web-security-testing-guide/v42/3-The_OWASP_Testing_Framework/1-Penetration_Testing_Methodologies
- Trivy SBOM docs: https://trivy.dev/v0.49/docs/supply-chain/sbom/
- Syft SBOM docs: https://oss.anchore.com/docs/guides/sbom/getting-started/
- Sigstore Cosign container signing docs: https://docs.sigstore.dev/cosign/signing/signing_with_containers/
- SLSA specification: https://slsa.dev/spec/

## Local verification commands

- `rg` over `helm/agentflow`, `.github/workflows`, `src/`, `config/`, `scripts/`, and `docs/security-audit.md`.
- `python -m ruff check src sdk integrations --select S608 --isolated --output-format json`
- `python -m bandit -r src sdk integrations -t B608 -f json`
- `python -m mypy src\quality --config-file pyproject.toml --disallow-untyped-defs --follow-imports=skip --no-incremental --show-error-codes`
- DuckDB read-only inspection via `duckdb_databases()`.
- `coverage.xml` line-rate extraction.

## Verdict matrix

| ID | Status | Confidence | Current local evidence | Source-backed interpretation |
|---|---|---:|---|---|
| H3 | Open | High | `helm/agentflow/values.yaml:4` keeps `replicaCount: 2`; `helm/agentflow/values.yaml:39` has HPA min `2`; `helm/agentflow/values.yaml:46` uses `ReadWriteOnce`; one PVC is mounted into all API replicas through `helm/agentflow/templates/deployment.yaml:142-143`. `k8s/staging/values-staging.yaml:1` narrows staging to one replica. | Kubernetes says `ReadWriteOnce` is single-node and can still allow multiple pods on that node; `ReadWriteOncePod` is the single-Pod access mode. DuckDB supports one writing process, not automatic multi-process writes. The default chart remains unsafe for DuckDB-backed multi-replica writes. |
| H4 | Partial / evidence gap | High | `.github/workflows/terraform-apply.yml:20` has `id-token: write`, and lines 49/96 use `vars.AWS_TERRAFORM_ROLE_ARN`; both jobs are disabled at lines 31 and 75. `infrastructure/terraform/environments/` contains only `*.tfvars.example`. `infrastructure/terraform/main.tf:15` still uses `dynamodb_table`; no `use_lockfile` hit was found. | GitHub OIDC best practice is short-lived tokens plus cloud trust configuration; Terraform now documents S3 lockfile locking and deprecates DynamoDB-based locking. The repo has wiring, but no local evidence that the trust path, variables, and tfvars are live. |
| H5 | Open / external evidence gap | High | `docs/security-audit.md:14-15` and `docs/operations/external-pen-test-attestation-handoff.md` state third-party pen-test attestation is absent. | OWASP WSTG treats penetration testing as a structured security testing discipline with documented methodology and results. Internal scans and AI-assisted audits are useful, but they are not equivalent attestation evidence. |
| H6 | Open | High | Installed DuckDB is `1.4.4`; `duckdb_databases()` reports `encrypted=False` for `agentflow_api.duckdb` and `agentflow_demo_api.duckdb`. `rg` found plain `duckdb.connect(...)` paths and no `ENCRYPTION_KEY`, `ENCRYPTION_CIPHER`, `temp_file_encryption`, or encrypted `ATTACH` path in runtime/config/Helm/workflows/scripts. | DuckDB 1.4 supports AES-256 at-rest encryption via `ATTACH ... ENCRYPTION_KEY`, covering DB, WAL, and temp files, but AgentFlow does not evidence that mode. DuckDB's own implementation note also flags NIST-compliance caveats. |
| M1 | Open | High | `pyproject.toml:119` globally ignores `S608`; isolated Ruff check reports `ruff_s608_count=21`. | Ruff `S608` exists specifically to flag SQL-looking strings built through interpolation/formatting. Per-file ignores exist, so a global ignore is broader than needed for reviewed SQL builder paths. |
| M2 | Open | High | `.bandit:3` globally skips `B608`; direct Bandit `-t B608` produced `bandit_b608_results=0` and `bandit_b608_skipped_tests=21`. | Bandit `B608` targets string-built SQL injection risk. Current config/suppressions mean the normal Bandit gate cannot distinguish reviewed SQL assembly from new accidental interpolation. |
| M3 | Open | High | `pyproject.toml:178` sets `disallow_untyped_defs = false`; strict local mypy on `src\quality` reports 4 `no-untyped-def` errors in 3 files. AST scan also found 81 serving definitions with missing arg/return annotations. | mypy supports per-module strictness and `disallow_untyped_defs`; current config is lenient for core serving/quality boundaries. |
| M4 | Open | High | `helm/agentflow/values.yaml:223` and `:232` contain bcrypt API-key verifier hashes; `helm/agentflow/templates/secret.yaml:11` renders `.Values.secrets.apiKeys` into a Kubernetes Secret. `config/api_keys.yaml` also contains verifier hashes. | Kubernetes warns that checked-in Secret manifests expose the secret material to repo readers, and base64 is not encryption. ASVS V13.3 expects backend secrets/API keys to be managed outside source and build artifacts. Bcrypt hashes are safer than plaintext keys, but still offline-verification material. |
| M7 | Open | Medium-high | `.github/workflows/staging-deploy.yml` runs kind staging and diagnostics, and `scripts/k8s_staging_up.sh` waits for rollout status. Repo search found no release rollback workflow or `helm rollback` path for the AgentFlow chart. | Kubernetes reports stalled rollouts through Deployment conditions and documents manual rollout undo; Helm has first-class rollback and rollback-on-failure behavior. Current repo has readiness checks, not a recorded chart revision recovery path. |
| M8 | Open / target advisory | Medium | `.github/workflows/ci.yml:67` enforces `--cov-fail-under=60`; `coverage.xml` line-rate is `0.623`; `codecov.yml:5` keeps project target `auto`, while `codecov.yml:9` sets patch target `80%`. | pytest-cov can enforce a total floor; Codecov can gate project or patch status. Because measured total coverage is ~62.3%, a 75% total target remains directionally valid but not immediately green without added tests or narrower per-module gates. |
| M9 | Open | High | `api_usage` and `api_sessions` are local DuckDB tables; `src/serving/api/analytics.py:428` uses `INSERT OR REPLACE` for sessions. Repo search found no `api_usage.audit` topic, external audit sink, immutability control, or SIEM export. | Kubernetes audit docs model security logs as chronological records persisted to backends; ASVS V16 requires protected logs that cannot be modified and transmission to a logically separate system. Mutable local DuckDB analytics are useful telemetry, not immutable audit logging. |
| L6 | Open | High | `.github/workflows/security.yml:181-219` runs Trivy SARIF image scanning only; no `syft`, `trivy --format cyclonedx/spdx`, `trivy sbom`, SPDX, or CycloneDX artifact generation is present. | Kubernetes releases publish verifiable SBOMs; Trivy and Syft both support SPDX/CycloneDX SBOM generation. AgentFlow's scan is useful but does not produce a consumable SBOM artifact. |
| L7 | Open | High | Repo search found no `cosign`, `sigstore`, SLSA generator, container signing, image attestation, or container provenance workflow. | Kubernetes signs release artifacts and documents cosign verification plus digest-pinned images. Sigstore supports OIDC/keyless container signing; SLSA defines provenance expectations. AgentFlow does not evidence signed container images or container provenance. |

## Cross-source synthesis

### Storage and database safety

H3 and H6 are coupled. Kubernetes `ReadWriteOnce` does not mean single writer or single Pod, and DuckDB's documented model does not support automatic writes from multiple processes. The Helm default therefore remains a real architecture risk even though staging narrows to one replica. DuckDB encryption is available in the local installed version, but current runtime paths use plain `duckdb.connect(...)`; no source/config evidence proves encrypted-at-rest DuckDB files.

Confidence: High, because the chart values, PVC template, runtime connection paths, local DuckDB metadata, Kubernetes docs, and DuckDB docs all agree.

### Infrastructure and release evidence

H4 is no longer "no code exists"; it is an evidence/readiness gap. The workflow has OIDC permissions and AWS credential exchange wiring, but the jobs are disabled and the required repo variable/tfvars evidence is absent in repo docs. Terraform's current S3 backend docs also make the legacy DynamoDB locking config a modernization note.

M7, L6, and L7 are similar release-process gaps. The repo has staging smoke behavior and Trivy SARIF scanning, but not recorded Helm rollback recovery, SBOM artifact generation, container signing, or container provenance.

Confidence: High for absence/evidence gaps; medium-high for M7 because rollback workflow shape is a policy choice, but current absence is direct.

### Security verification and logging

H5 and M9 cannot be closed by local code inspection alone. The repository honestly states third-party pen-test attestation is absent, and the local audit/analytics tables are mutable. Kubernetes and ASVS both support the need for protected chronological audit records, while OWASP WSTG supports the distinction between internal checks and structured penetration-testing evidence.

Confidence: High.

### Static analysis and quality gates

M1/M2/M3/M8 are confirmed. Ruff and Bandit SQL-construction checks are disabled or suppressed broadly enough that new unreviewed SQL interpolation could pass normal gates. mypy is lenient at function boundaries, and a targeted strict check already fails in `src\quality`. Coverage is objectively above the current 60% floor but far below a clean 75% total floor.

Confidence: High for M1/M2/M3; medium for M8 because the exact target is a project policy decision.

## Bottom line

All requested remaining points remain open or partially open after the local remediation package. The strongest current blockers are H3, H6, M4, M9, L6, and L7 because they are direct evidence gaps against Kubernetes/DuckDB/ASVS/supply-chain primary guidance. H4 and H5 are external evidence boundaries rather than local code defects. M8's 75% target should be treated as advisory against the measured 62.3% baseline unless the project chooses narrower core-module gates.
