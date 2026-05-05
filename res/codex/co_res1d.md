# AgentFlow audit_kimi remaining items: source-backed status

Date: 2026-05-05
Project: `D:\DE_project`
Baseline: HEAD `10bc3c7`, `673` tracked files. Bundle size and i18n key count are not applicable to this research-only artifact.

Scope: `audit_kimi_04_05_26.md` items H3/H4/H5/H6, M1/M2/M3/M4/M7/M8/M9, L6/L7 after the local remediation package of 2026-05-05.

Already closed/out of scope per prompt: Docker editable install, `.dockerignore`, Docker healthcheck, pinned MinIO tags, Helm image tag `1.1.0`, request body size middleware.

Boundary: local research and evidence classification only. No deploy, apply, push, live-cluster, registry publication, or paid action is proposed.

## Primary sources checked

Storage and Kubernetes:

- Kubernetes PersistentVolume access modes: https://kubernetes.io/docs/concepts/storage/persistent-volumes/
- DuckDB concurrency: https://duckdb.org/docs/stable/connect/concurrency
- DuckDB encrypted `ATTACH`: https://duckdb.org/docs/current/sql/statements/attach.html
- DuckDB data-at-rest encryption note: https://duckdb.org/2025/11/19/encryption-in-duckdb
- ClickHouse replication: https://clickhouse.com/docs/architecture/replication
- ClickHouse Replicated MergeTree engines: https://clickhouse.com/docs/engines/table-engines/mergetree-family/replication
- ClickHouse SharedMergeTree: https://clickhouse.com/docs/cloud/reference/shared-merge-tree

CI/IaC/release recovery:

- GitHub Actions OIDC for AWS: https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws
- Terraform S3 backend: https://developer.hashicorp.com/terraform/language/backend/s3
- Helm upgrade and rollback: https://helm.sh/docs/helm/helm_upgrade/ and https://helm.sh/docs/helm/helm_rollback/

Security, logging, and secrets:

- OWASP ASVS 5.0 V13.3 Secret Management: https://cornucopia.owasp.org/taxonomy/asvs-5.0/13-configuration/03-secret-management
- OWASP ASVS 5.0 V16 Security Logging: https://cornucopia.owasp.org/taxonomy/asvs-5.0/16-security-logging-and-error-handling
- OWASP WSTG stable introduction and testing principles: https://owasp.org/www-project-web-security-testing-guide/stable/2-Introduction/README
- Kubernetes Secrets good practices: https://kubernetes.io/docs/concepts/security/secrets-good-practices/

Static analysis, coverage, and supply chain:

- Ruff S608 and per-file ignores: https://docs.astral.sh/ruff/rules/hardcoded-sql-expression/ and https://docs.astral.sh/ruff/settings/#lint_per-file-ignores
- Bandit B608 and suppression/config docs: https://bandit.readthedocs.io/en/latest/plugins/b608_hardcoded_sql_expressions.html and https://bandit.readthedocs.io/en/latest/config.html
- mypy config: https://mypy.readthedocs.io/en/stable/config_file.html
- pytest-cov config: https://pytest-cov.readthedocs.io/en/latest/config.html
- Codecov status checks: https://docs.codecov.com/docs/commit-status
- Syft SBOM docs: https://oss.anchore.com/docs/guides/sbom/getting-started/ and https://oss.anchore.com/docs/guides/sbom/formats/
- Trivy SBOM docs: https://trivy.dev/docs/latest/guide/target/sbom/
- Sigstore Cosign container signing: https://docs.sigstore.dev/cosign/signing/signing_with_containers/
- SLSA v1.2 specification and build provenance: https://slsa.dev/spec/ and https://slsa.dev/spec/v1.2/build-provenance
- GitHub artifact attestations: https://docs.github.com/en/actions/concepts/security/artifact-attestations

## Local verification commands

- `git ls-files | Measure-Object`
- `rg` over `audit_kimi_04_05_26.md`, `helm/agentflow`, `.github/workflows`, `infrastructure/terraform`, `src`, `config`, `scripts`, and `docs`
- `.venv\Scripts\python.exe -m ruff check src sdk integrations --select S608 --isolated --output-format json`
- `.venv\Scripts\python.exe -m bandit -r src sdk integrations -t B608 -f json -q`
- `.venv\Scripts\python.exe -m mypy src\quality --config-file pyproject.toml --disallow-untyped-defs --follow-imports=skip --no-incremental --show-error-codes`
- AST scan for missing annotations under `src/serving`
- DuckDB read-only `duckdb_databases()` inspection
- `coverage.xml` line-rate extraction

## Current best-practice synthesis

High confidence:

- Kubernetes `ReadWriteOnce` is not a single-Pod or single-writer database control. Kubernetes explicitly distinguishes `ReadWriteOncePod` for single-Pod access and notes that volume access modes do not enforce write protection after mount.
- DuckDB remains a single-process write database model. Multiple writer threads are supported inside one writer process, but automatic multi-process writes to one database file are not supported. This is incompatible with a default multi-replica writer shape.
- DuckDB at-rest encryption is now a current feature. The current documented path is encrypted `ATTACH ... ENCRYPTION_KEY`, with AES-256 GCM by default and coverage for main DB, WAL, and temp files. DuckDB also documents NIST-compliance caveats.
- For replicated serving, the local ClickHouse backend aligns better with primary docs than DuckDB-on-PVC. ClickHouse replication is table-level through replicated MergeTree engines and ClickHouse Keeper; ClickHouse Cloud's SharedMergeTree separates compute/storage and uses shared storage plus Keeper coordination.
- GitHub OIDC best practice is short-lived cloud credentials with a trust policy constrained by claims such as `sub`; Terraform S3 backend currently documents `use_lockfile` locking and marks DynamoDB-based locking deprecated.
- OWASP ASVS V13.3 expects backend secrets and API keys to be managed outside source/build artifacts. OWASP ASVS V16 expects log inventory, protected logs that cannot be modified, and secure transmission to a logically separate system.
- Ruff S608 and Bandit B608 both exist to catch SQL-looking strings built through interpolation/formatting. Tool docs support narrow, reviewed suppressions more strongly than broad global disables.
- mypy supports per-module strictness and `disallow_untyped_defs`; pytest-cov and Codecov support explicit coverage gates, but target choice is a project policy decision.
- Syft/Trivy support SPDX/CycloneDX SBOM workflows. Sigstore/Cosign and SLSA/GitHub attestations support signed containers and verifiable build provenance; attestations still require downstream verification policy to have security value.

## Verdict matrix

| ID | Status after remediation | Confidence | Local evidence | Source-backed interpretation |
|---|---|---:|---|---|
| H3 | Open | High | `helm/agentflow/values.yaml` still has `replicaCount: 2`, HPA `minReplicas: 2`, `persistence.accessModes: [ReadWriteOnce]`, and DuckDB paths under `/data`; `helm/agentflow/templates/deployment.yaml` mounts one PVC as `data`; `config/serving.yaml` defaults to `backend: duckdb`; staging narrows to `replicaCount: 1`. | This remains an unsafe default for DuckDB-backed multi-replica writes. `ReadWriteOnce` is node-scoped, not single-writer; DuckDB does not support automatic multi-process writes to one file. |
| H4 | Partial / external evidence gap | High | `.github/workflows/terraform-apply.yml` has `permissions.id-token: write` and `aws-actions/configure-aws-credentials@v4`, but both jobs are `if: false`; docs state `AWS_TERRAFORM_ROLE_ARN`, real tfvars, and OIDC proof are absent; `infrastructure/terraform/main.tf` uses S3 backend with `dynamodb_table`; no `use_lockfile` hit was found. | The OIDC shape is partly present, but current primary guidance requires an actual configured trust path and constrained token claims. Terraform backend locking is also behind current S3 lockfile guidance. This is not locally closed by code presence alone. |
| H5 | Open / external evidence gap | High | `docs/security-audit.md`, `docs/release-readiness.md`, and `docs/operations/external-pen-test-attestation-handoff.md` explicitly record no third-party tester, report, signed attestation, scope, severity summary, remediation map, retest status, or owner. | OWASP WSTG frames security testing as a documented program, not just scanner output. Internal scans/source review cannot be reclassified as third-party attestation. No paid action is proposed. |
| H6 | Open | High | Local DuckDB package is `1.5.1`; `duckdb_databases()` reports `encrypted=False` for `agentflow_api.duckdb` and `agentflow_demo_api.duckdb`; `agentflow_demo.duckdb` failed WAL replay and is not encryption evidence. `rg` found no `ENCRYPTION_KEY`, `ENCRYPTION_CIPHER`, `temp_file_encryption`, or encrypted `ATTACH` runtime path. | DuckDB encryption is currently available, but AgentFlow runtime paths use plain `duckdb.connect(...)`. At-rest encryption is therefore not evidenced for the DuckDB deployment. |
| M1 | Open | High | `pyproject.toml` globally ignores `S608`; isolated Ruff check reports 21 S608 findings in `src`, `sdk`, and `integrations`. | Ruff S608 directly targets SQL string-building. Current reviewed SQL builders may be legitimate, but the global ignore means normal lint does not catch new unreviewed SQL construction. |
| M2 | Open | High | `.bandit` globally skips `B608`; direct Bandit B608 run reports `results=0 skipped_tests=21`, because current sites are locally suppressed. | Bandit docs support `# nosec` for reviewed acceptable lines and specific IDs. The global skip is broader than the line-level suppressions and weakens the default security gate. |
| M3 | Open | Medium-high | `pyproject.toml` has `disallow_untyped_defs = false`; strict mypy on `src\quality` reports 4 `no-untyped-def` errors in 3 files; AST scan found 81 serving definitions with missing arg/return annotations after excluding `self`/`cls`. | mypy supports per-module strictness and explicit disallowing of untyped definitions. The quality/serving boundary is not ready for a strict gate without staged typing work. |
| M4 | Open | High | `helm/agentflow/values.yaml` and `config/api_keys.yaml` contain bcrypt `key_hash` entries; `helm/agentflow/templates/secret.yaml` renders chart values into a Kubernetes Secret. | Bcrypt hashes are safer than plaintext API keys, but they are still checked-in verifier material. ASVS V13.3 says API keys/backend secrets should not be in source/build artifacts; Kubernetes also warns that checked-in Secret manifests expose values to repo readers and base64 is not encryption. |
| M7 | Open | Medium-high | `scripts/k8s_staging_up.sh` uses `helm upgrade --install ... --wait --timeout 5m --debug`; repo search found no AgentFlow `helm rollback`, `--atomic`, or release-revision recovery workflow. | Helm and Kubernetes expose failure/rollback semantics, but AgentFlow currently has readiness waiting and diagnostics, not a checked-in recovery path. No rollout or rollback action is proposed. |
| M8 | Open / target advisory | Medium | `.github/workflows/ci.yml` enforces `--cov-fail-under=60`; `coverage.xml` has `line-rate="0.623"`; `codecov.yml` has project target `auto` and patch target `80%`. | pytest-cov can fail a run below a total coverage floor; Codecov can gate project/patch coverage. A 75% total target is directionally defensible, but current measured total coverage is about 62.3%, so treating 75% as an immediate hard floor would not be locally green without more tests or narrower module gates. |
| M9 | Open | High | API telemetry is stored in mutable local DuckDB tables: `api_usage` in auth middleware and `api_sessions` in analytics, including `INSERT OR REPLACE` for sessions. Repo search found no `api_usage.audit` Kafka topic, external log sink, WORM control, or immutable audit store. | ASVS V16 requires documented, protected, non-modifiable logs and secure transmission to a logically separate system. Current DuckDB tables are useful operational telemetry, not immutable audit logging. |
| L6 | Open | High | `.github/workflows/security.yml` runs Trivy SARIF image scanning only; repo search found no `syft`, `trivy sbom`, `cyclonedx`, `spdx`, or SBOM artifact generation. | Syft and Trivy both support SPDX/CycloneDX SBOM workflows. Current vulnerability scanning does not produce a consumable SBOM artifact. |
| L7 | Open / conditional on container release scope | High | Repo search found no `cosign`, `sigstore`, `slsa`, `attest-build-provenance`, container image signing, or container provenance step. No clear container publication workflow/digest was found either. | If AgentFlow distributes container images as release artifacts, signed image/provenance evidence is absent. If container images are not release artifacts, the item should be classified as not-applicable-by-scope rather than closed. |

## Item notes

### H3 / H6: DuckDB serving topology and encryption

H3 and H6 remain the most direct DuckDB risks. The Helm default still combines multiple API replicas, HPA minimum 2, a single RWO PVC, and DuckDB file paths. Kubernetes and DuckDB primary docs agree that this does not form a safe multi-writer database topology.

DuckDB encryption is now current, but AgentFlow does not use the encrypted `ATTACH` path. The local DB metadata check is direct evidence for two runtime files: `agentflow_api.duckdb` and `agentflow_demo_api.duckdb` are unencrypted. The WAL replay error for `agentflow_demo.duckdb` is a local inspection failure, not proof of encryption.

### H4 / H5: external evidence boundaries

H4 is no longer "no code exists"; it is a readiness/evidence gap. The workflow has OIDC permissions and AWS credential exchange wiring, but is disabled and lacks repo evidence for the role variable, real tfvars, trust-policy proof, and first successful run. Terraform's current S3 backend docs also make `dynamodb_table` a modernization note.

H5 is not locally closable by static analysis. The repo correctly keeps internal audit evidence separate from third-party pen-test attestation evidence. No external testing or paid service action is proposed here.

### M1 / M2 / M3 / M8: quality gates

M1 and M2 are confirmed. The codebase contains intentional SQL construction with local rationale, but the global Ruff ignore and Bandit skip mean the normal gates cannot detect new unreviewed SQL construction. The source-aligned classification is: reviewed local suppressions can be valid; global disablement remains open.

M3 is confirmed at least for `src\quality`, and the serving AST scan shows a larger annotation backlog. A staged per-module strictness posture is better supported by the evidence than claiming the global gate is ready.

M8 is open, but the number should be treated as advisory against the measured baseline. Current total coverage is 62.3%; patch coverage is already stricter at 80%.

### M4 / M9: secrets and audit evidence

M4 remains open because checked-in bcrypt API-key verifier hashes are still security-sensitive verifier material in production-shaped defaults. Rendering them as a Kubernetes Secret does not remove source-control exposure.

M9 remains open because mutable local DuckDB analytics tables do not satisfy ASVS-style protected, logically separate, non-modifiable security log evidence. ClickHouse query logs or app telemetry can help observability, but no current AgentFlow path shows immutable audit-log semantics.

### M7 / L6 / L7: release recovery and supply chain metadata

M7 remains open because the local staging script waits for Helm readiness but does not evidence release-revision recovery. This report does not propose running any rollout or rollback.

L6 is a straightforward missing artifact-generation gap: scan results exist, SBOM artifact generation does not.

L7 is conditional on release scope. Container signing/provenance is absent; if the project is not publishing container images, the accurate result is scoped not-applicable rather than remediated.

## Confidence summary

| Theme | Confidence | Basis |
|---|---:|---|
| DuckDB multi-replica write risk | High | Direct Helm/config evidence plus Kubernetes and DuckDB primary docs. |
| DuckDB encryption gap | High | Direct grep and `duckdb_databases()` output plus DuckDB encryption docs. |
| ClickHouse as production serving alternative | High | Local backend support plus ClickHouse replication/SharedMergeTree docs. |
| H4/H5 external evidence gaps | High | Direct workflow/docs evidence plus GitHub/Terraform/OWASP docs. |
| Static-analysis gates M1/M2 | High | Direct config plus Ruff/Bandit command output. |
| Typing gate M3 | Medium-high | Direct config, targeted strict mypy output, and AST scan. |
| Secrets/audit-log M4/M9 | High | Direct Helm/code evidence plus Kubernetes/ASVS docs. |
| Coverage gate M8 | Medium | Direct CI/config/coverage evidence; exact target is policy-dependent. |
| SBOM/signing L6/L7 | High | Direct workflow search plus Syft/Trivy/Sigstore/SLSA/GitHub docs. |

## Bottom line

All requested remaining points are still open, partially open, or conditional after the local remediation package. The strongest local blockers are H3, H6, M4, M9, L6, and L7 because they are direct evidence gaps against current primary guidance. H4 and H5 are external evidence boundaries rather than hidden code defects. M8's 75% target is best treated as advisory unless the project chooses scoped core-module coverage gates or raises tests enough to make a higher total threshold green.
