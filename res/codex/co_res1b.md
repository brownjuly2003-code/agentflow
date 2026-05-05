# AgentFlow audit_kimi open items: current source-backed status

Date: 2026-05-05
Repo: `D:\DE_project`
Baseline: HEAD `10bc3c7`, 673 tracked files

Scope: `audit_kimi_04_05_26.md` items H3/H4/H5/H6, M1/M2/M3/M4/M7/M8/M9, L6/L7 after the local remediation package of 2026-05-05.

Already treated as closed by the prompt: Docker editable install, `.dockerignore`, Docker healthcheck, pinned MinIO tags, Helm image tag `1.1.0`, request body size middleware.

Boundary: this is research and local evidence classification only. No deploy, apply, push, or paid action is proposed.

## Primary sources checked

DuckDB / ClickHouse primary docs:

- DuckDB concurrency: https://duckdb.org/docs/current/connect/concurrency
- DuckDB FAQ on storage, single-node scalability, and multiple clients: https://duckdb.org/faq
- DuckDB `ATTACH` database encryption: https://duckdb.org/docs/current/sql/statements/attach
- DuckDB data-at-rest encryption implementation note: https://duckdb.org/2025/11/19/encryption-in-duckdb
- ClickHouse replication example and Keeper production guidance: https://clickhouse.com/docs/architecture/replication
- ClickHouse replicated MergeTree engines: https://clickhouse.com/docs/engines/table-engines/mergetree-family/replication
- ClickHouse SharedMergeTree: https://clickhouse.com/docs/cloud/reference/shared-merge-tree
- ClickHouse `system.query_log`: https://clickhouse.com/docs/operations/system-tables/query_log

Other primary docs used where DuckDB/ClickHouse do not define the control:

- Kubernetes PersistentVolume access modes: https://kubernetes.io/docs/concepts/storage/persistent-volumes/
- Kubernetes Deployment rollout/failure semantics: https://kubernetes.io/docs/concepts/workloads/controllers/deployment/
- Kubernetes Secrets and secret good practices: https://kubernetes.io/docs/concepts/configuration/secret/ and https://kubernetes.io/docs/concepts/security/secrets-good-practices/
- Helm upgrade and rollback references: https://helm.sh/docs/helm/helm_upgrade/ and https://helm.sh/docs/helm/helm_rollback/
- GitHub Actions OIDC for AWS: https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws
- Terraform S3 backend: https://developer.hashicorp.com/terraform/language/backend/s3
- OWASP WSTG stable intro: https://owasp.org/www-project-web-security-testing-guide/stable/2-Introduction/README
- OWASP ASVS 5.0.0 V13/V14/V16: https://github.com/OWASP/ASVS/tree/v5.0.0/5.0/en
- Ruff S608 and per-file ignores: https://docs.astral.sh/ruff/rules/hardcoded-sql-expression/ and https://docs.astral.sh/ruff/settings/#lint_per-file-ignores
- Bandit B608 and suppressions: https://bandit.readthedocs.io/en/latest/plugins/b608_hardcoded_sql_expressions.html and https://bandit.readthedocs.io/en/latest/config.html
- mypy config: https://mypy.readthedocs.io/en/stable/config_file.html
- pytest-cov config and Codecov status checks: https://pytest-cov.readthedocs.io/en/latest/config.html and https://docs.codecov.com/docs/commit-status
- Syft, Trivy SBOM, Sigstore Cosign, SLSA provenance, GitHub artifact attestations: https://github.com/anchore/syft, https://trivy.dev/docs/latest/target/sbom/, https://docs.sigstore.dev/cosign/signing/signing_with_containers/, https://slsa.dev/spec/v1.1/provenance, https://docs.github.com/en/actions/concepts/security/artifact-attestations

## DuckDB / ClickHouse synthesis

High confidence:

- DuckDB's current concurrency model is still not a multi-process writer database model. DuckDB documents one read-write process or multiple read-only processes, and says writing to the native database format from multiple processes is not currently supported. It also warns to use caution with shared directories and network filesystems.
- DuckDB is explicitly single-node / vertically scaling. The FAQ points to DuckLake with a PostgreSQL catalog for multi-client read-write collaboration, not a Kubernetes multi-replica shared DuckDB file.
- DuckDB encryption is now first-class in current docs: `ATTACH ... (ENCRYPTION_KEY ...)` uses AES-256 GCM by default and covers the main DB file, WAL, and temporary files. `duckdb_databases()` exposes `encrypted` and `cipher` metadata.
- ClickHouse is the source-aligned production serving alternative already present in AgentFlow. Self-managed replication uses replicated MergeTree engines plus ClickHouse Keeper; ClickHouse docs recommend dedicated Keeper hosts in production. ClickHouse Cloud's SharedMergeTree is optimized for shared object storage and elastic compute, but it is a ClickHouse Cloud feature, not a generic DuckDB-on-PVC pattern.
- ClickHouse `system.query_log` is valuable query telemetry, but the docs say it is local per node in Cloud and require `clusterAllReplicas` for a complete view. It is not, by itself, an application immutable audit-log control.

## Verdict matrix

| ID | Status after remediation | Confidence | Local evidence | Source-backed interpretation |
|---|---|---:|---|---|
| H3 | Open | High | `helm/agentflow/values.yaml` still has `replicaCount: 2`, HPA `minReplicas: 2`, `persistence.accessModes: [ReadWriteOnce]`, DuckDB paths under `/data`; the Deployment mounts one PVC as `data`; `config/serving.yaml` still defaults to `backend: duckdb`. | DuckDB docs do not support multiple read-write processes against one native DB file. Kubernetes `ReadWriteOnce` is not a single-writer database guarantee and does not enforce write protection after mount. The chart default is still unsafe for DuckDB-backed multi-replica serving. ClickHouse remains the better documented multi-node serving backend. |
| H4 | Open / external evidence gap | High | `.github/workflows/terraform-apply.yml` has `permissions.id-token: write` and `aws-actions/configure-aws-credentials@v4`, but both jobs are `if: false`; docs state `AWS_TERRAFORM_ROLE_ARN`, real tfvars, and OIDC proof are absent; `infrastructure/terraform/main.tf` uses S3 backend with `dynamodb_table`. | GitHub OIDC docs confirm the shape is right for short-lived AWS credentials, but local code is intentionally disabled and lacks operator evidence. Terraform now marks DynamoDB S3 backend locking as deprecated, so the backend is also not fully current. DuckDB/ClickHouse docs do not apply to this control. |
| H5 | Open / external evidence gap | High | `docs/operations/external-pen-test-attestation-handoff.md` and `docs/release-readiness.md` explicitly record no tester, report, signed attestation, scope, severity summary, remediation map, retest status, or owner. | OWASP WSTG treats security testing as a documented program and says formal test results should identify who tested, when, findings, risk, and reproducibility. Internal scans/source review cannot be represented as third-party attestation. No paid action is proposed here. |
| H6 | Open | High | Grep found no `ENCRYPTION_KEY`, `ENCRYPTION_CIPHER`, or `temp_file_encryption` usage in app/config/workflow paths. Runtime check: `agentflow_api.duckdb` and `agentflow_demo_api.duckdb` report `encrypted=False`; `agentflow_demo.duckdb` failed WAL replay and is not proof of encryption. | Current DuckDB docs support encrypted DBs through `ATTACH ... ENCRYPTION_KEY`, with main file, WAL, and temp-file coverage. AgentFlow still uses plain `duckdb.connect(...)` paths for production-shaped runtime DBs, so at-rest encryption is not evidenced. |
| M1 | Open | High | `pyproject.toml` globally ignores `S608`; `python -m ruff check src sdk integrations --select S608 --isolated` reports 21 S608 findings. | Ruff S608 targets SQL built through string construction and recommends parameterized queries. Current inline rationales may be valid, but global ignore prevents normal lint from catching new SQL construction. |
| M2 | Open | High | `.bandit` globally skips `B608`; direct `python -m bandit -r src sdk integrations -t B608 -f txt` reports 0 issues because 21 potential issues are locally suppressed with `# nosec B608`. | Bandit docs allow reviewed `# nosec` suppressions and specific test IDs. The global skip is broader than the already-present line-level suppressions, so the default Bandit gate still cannot detect new B608 surfaces. |
| M3 | Open | Medium-high | `pyproject.toml` has `disallow_untyped_defs = false`; `python -m mypy src\quality --ignore-missing-imports --disallow-untyped-defs` reports 4 `no-untyped-def` errors in 3 files. | mypy docs support per-module strictness. The current global setting leaves function boundaries untyped in quality/serving-adjacent code, so this remains a real gate gap. |
| M4 | Open | High | `helm/agentflow/values.yaml` and `config/api_keys.yaml` contain bcrypt `key_hash` entries; Helm renders `api_keys.yaml` into a Kubernetes Secret from chart values. | Kubernetes Secrets are intended for confidential data but are stored unencrypted in etcd by default unless configured otherwise; ASVS 13.3 says API keys and backend secrets should not be in source or build artifacts. Bcrypt hashes are not plaintext API keys, but they are still checked-in verifier material. |
| M7 | Open | Medium-high | `scripts/k8s_staging_up.sh` uses `helm upgrade --install ... --wait --timeout 5m --debug` without Helm rollback-on-failure behavior; repository search found no `helm rollback`, `--atomic`, or equivalent release-revision recovery workflow. | Kubernetes and Helm docs both expose rollout failure detection and rollback semantics. AgentFlow has readiness/liveness probes and `--wait`, but no checked-in recovery path for a failed chart revision. |
| M8 | Open / target advisory | Medium | `.github/workflows/ci.yml` keeps `--cov-fail-under=60`; `coverage.xml` currently reports `line-rate="0.623"`; `codecov.yml` has patch target `80%`, project target `auto`. | pytest-cov supports a hard total minimum; Codecov supports project and patch status targets. The audit's 75% direction is reasonable, but current measured total coverage is only 62.3%, so a hard 75% gate is not locally green without test work or scoped gates. |
| M9 | Open | High | API telemetry uses DuckDB tables: `api_usage` in `src/serving/api/auth/middleware.py`, `api_sessions` in `src/serving/api/analytics.py`, including `INSERT OR REPLACE` for sessions. No `api_usage.audit` topic, external log sink, WORM control, or immutable append-only audit store was found. | ASVS V16 requires protected logs that cannot be modified and secure transmission to a logically separate system. ClickHouse query logs are useful observability, but not the same as an application immutable audit trail. Mutable local DuckDB analytics tables do not close this item. |
| L6 | Open | High | `.github/workflows/security.yml` runs Trivy SARIF scanning only; no `syft`, `cyclonedx`, `spdx`, `trivy sbom`, or SBOM artifact was found in workflows/scripts. | Syft and Trivy primary docs both support SBOM generation/consumption in SPDX/CycloneDX formats. Current scanning is useful but does not produce a consumable SBOM artifact. |
| L7 | Open / conditional on container release scope | High | No `cosign`, `sigstore`, `slsa`, `attest-build-provenance`, or container image signing/attestation step was found. There is also no clear container-publication workflow/digest in the local evidence. | Sigstore Cosign supports OIDC/keyless container signing; SLSA/GitHub attestations define provenance for released artifacts. If AgentFlow distributes container images as release artifacts, this remains open. If not, it should be documented as not applicable rather than treated as a blocking release control. |

## Item notes

### H3 / H6 storage risk

H3 and H6 remain the most DuckDB-specific risks. The local Helm default still combines multi-replica API pods, HPA, a single RWO PVC, and DuckDB file paths. DuckDB's own docs make that a poor fit for multi-replica write-serving. The current best-practice split is: DuckDB for local/single-process or read-only distributed files; ClickHouse for replicated/clustered serving; DuckLake/PostgreSQL catalog if the project specifically wants DuckDB ecosystem multi-client writes.

Encryption is not just "not documented"; it is absent in code paths and false for two checked local DB files. DuckDB now gives a clean technical path for encrypted files, but AgentFlow does not use it in the current runtime path.

### H4 / H5 evidence gates

H4 and H5 are not locally closable by code inspection. H4 has partial OIDC workflow wiring but disabled execution and no proof that the external trust path exists. H5 has the right handoff file and correctly avoids claiming external attestation. These should stay marked as evidence gaps, not as hidden code defects.

### M1 / M2 / M3 quality gates

M1 and M2 are locally closable policy gaps, but still open now. Ruff and Bandit both identify the same SQL-string-construction risk family. The code already contains many local rationales, which is a better shape than broad suppressions, but the global ignore/skip still weakens the default gates.

M3 is confirmed at least in `src/quality`. A one-line global flip would currently fail, so the evidence supports staged per-module strictness rather than claiming the gate is ready.

### M4 / M9 security evidence

M4 remains open because checked-in bcrypt hashes in production-shaped Helm defaults are still secret-verifier material. Kubernetes Secret rendering does not solve source control exposure, and Kubernetes warns that Secret data has its own RBAC/etcd/encryption requirements.

M9 remains open because the current audit data is operational telemetry in mutable DuckDB tables. ASVS requires protected and non-modifiable security logs transmitted to a logically separate system. ClickHouse can be a strong analytics/logging backend, but no AgentFlow path currently shows immutable audit log semantics.

### M7 / M8 / L6 / L7 operations and supply chain

M7 is still open because the local staging script waits for Helm success but has no recorded release-revision recovery behavior. This report does not propose running any rollout or rollback.

M8 is open, but the hard number should be treated as advisory until tests raise the baseline. The actual local coverage file says 62.3%, while CI enforces 60% and Codecov patch coverage is 80%.

L6 is a straightforward missing artifact-generation gap. L7 is slightly different: signing requires a released container image identity/digest. Without a container publication artifact, the accurate status is conditional-open rather than pretending a signature can be evidenced locally.

## Confidence summary

| Theme | Confidence | Basis |
|---|---:|---|
| DuckDB multi-replica write risk | High | Direct Helm/config evidence plus current DuckDB concurrency docs. |
| DuckDB encryption gap | High | Direct grep and `duckdb_databases()` output plus current DuckDB encryption docs. |
| ClickHouse as production serving alternative | High | Local backend support plus ClickHouse replication/SharedMergeTree docs. |
| H4/H5 external evidence gaps | High | Direct workflow/docs evidence plus GitHub/Terraform/OWASP docs. |
| Static-analysis gates M1/M2 | High | Direct config plus Ruff/Bandit command output. |
| Typing gate M3 | Medium-high | Direct config plus targeted strict mypy output. |
| Secrets/audit-log M4/M9 | High | Direct Helm/code evidence plus Kubernetes/ASVS docs. |
| Coverage gate M8 | Medium | Direct CI/config/coverage evidence; target is policy-dependent. |
| SBOM/signing L6/L7 | High | Direct workflow search plus Syft/Trivy/Sigstore/SLSA/GitHub docs. |
