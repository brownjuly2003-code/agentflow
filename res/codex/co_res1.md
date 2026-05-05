# AgentFlow remaining audit items after local remediation package

Date: 2026-05-05
Scope: `audit_kimi_04_05_26.md` items H3/H4/H5/H6, M1/M2/M3/M4/M7/M8/M9, L6/L7.
Excluded as already remediated per prompt: Docker editable install, `.dockerignore`, Docker healthcheck, pinned MinIO tags, Helm image tag `1.1.0`, request body size middleware.

No live cloud, cluster, registry-publication, or commercial-service action is proposed here. This file records source-backed status only.

## Primary sources checked

- Kubernetes Persistent Volumes access modes: https://kubernetes.io/docs/concepts/storage/persistent-volumes/
- Kubernetes Deployments rollout/failure semantics: https://kubernetes.io/docs/concepts/workloads/controllers/deployment/
- Helm rollback command reference: https://helm.sh/docs/helm/helm_rollback/
- DuckDB concurrency: https://duckdb.org/docs/stable/connect/concurrency
- DuckDB `ATTACH` database encryption: https://duckdb.org/docs/current/sql/statements/attach.html
- DuckDB data-at-rest encryption implementation note: https://duckdb.org/2025/11/19/encryption-in-duckdb
- ClickHouse replication: https://clickhouse.com/docs/engines/table-engines/mergetree-family/replication and https://clickhouse.com/docs/architecture/replication
- GitHub Actions OIDC: https://docs.github.com/en/actions/security-for-github-actions/security-hardening-your-deployments/about-security-hardening-with-openid-connect and https://docs.github.com/en/actions/security-for-github-actions/security-hardening-your-deployments/configuring-openid-connect-in-cloud-providers
- Terraform S3 backend: https://developer.hashicorp.com/terraform/language/backend/s3
- OWASP ASVS 5.0.0 configuration/data/logging: https://raw.githubusercontent.com/OWASP/ASVS/v5.0.0/5.0/en/0x22-V13-Configuration.md, https://raw.githubusercontent.com/OWASP/ASVS/v5.0.0/5.0/en/0x23-V14-Data-Protection.md, https://raw.githubusercontent.com/OWASP/ASVS/v5.0.0/5.0/en/0x25-V16-Security-Logging-and-Error-Handling.md
- OWASP WSTG stable introduction/testing principles: https://owasp.org/www-project-web-security-testing-guide/stable/2-Introduction/README
- SLSA provenance: https://slsa.dev/spec/v1.1/provenance
- Sigstore Cosign container signing: https://docs.sigstore.dev/cosign/signing/signing_with_containers/
- Syft SBOM generation: https://github.com/anchore/syft
- Trivy SBOM docs: https://trivy.dev/docs/latest/guide/target/sbom/
- Ruff S608: https://docs.astral.sh/ruff/rules/hardcoded-sql-expression/
- Bandit B608: https://bandit.readthedocs.io/en/latest/plugins/b608_hardcoded_sql_expressions.html
- mypy config: https://mypy.readthedocs.io/en/stable/config_file.html
- pytest-cov / Codecov gates: https://pytest-cov.readthedocs.io/en/latest/config.html and https://docs.codecov.com/docs/commit-status

## Verdict matrix

| ID | Status | Confidence | Current local evidence | Source-backed interpretation |
|---|---|---:|---|---|
| H3 | Open | High | `helm/agentflow/values.yaml:4` has `replicaCount: 2`; autoscaling min is `2`; PVC is `ReadWriteOnce`; chart mounts one PVC into all replicas. | Kubernetes `ReadWriteOnce` is node-scoped, not single-pod. DuckDB supports one writing process; multiple writer processes are not automatic. This chart default still presents a split-brain/write-contention risk for DuckDB-backed serving. `k8s/staging/values-staging.yaml` uses `replicaCount: 1`, so staging is narrower than the default chart. |
| H4 | Partial / evidence gap | High | `.github/workflows/terraform-apply.yml` has `id-token: write` and AWS OIDC wiring but both jobs are `if: false`; only `*.tfvars.example` files exist under `infrastructure/terraform/environments`; OIDC module exists in `infrastructure/terraform/oidc.tf`. | GitHub OIDC best practice is short-lived tokens with explicit trust conditions. Terraform state backend has encryption enabled, but it still uses deprecated DynamoDB-style locking rather than current S3 lockfile guidance. Local code is partly prepared, but there is no repository evidence that the cloud trust path and environment variables are live. |
| H5 | Open / external evidence gap | High | `docs/operations/external-pen-test-attestation-handoff.md` states no tester, report, scope, window, severity summary, remediation map, retest status, or owner is present. | OWASP WSTG treats penetration testing as one part of a broader testing program and stresses documented, reproducible results. The repo correctly avoids claiming completion; internal audits and CI scans are not equivalent evidence. |
| H6 | Open | High | Installed DuckDB is `1.4.4`; no `ENCRYPTION_KEY`, `ENCRYPTION_CIPHER`, `temp_file_encryption`, or encrypted attach path is present in `src/`, `helm/`, `config/`, `.github/`, or `scripts/`. `duckdb_databases()` reports `encrypted=False` for `agentflow_api.duckdb` and `agentflow_demo_api.duckdb`. | DuckDB now supports AES-256 database encryption through `ATTACH ... ENCRYPTION_KEY`, covering main DB, WAL, and temp files. AgentFlow's default DuckDB connection path uses plain `duckdb.connect(...)`, so at-rest encryption is not evidenced. DuckDB's own note says current encryption is not yet official NIST-compliant. |
| M1 | Open | High | `pyproject.toml:119` globally ignores `S608`; `ruff check src sdk integrations --select S608 --isolated` finds 21 S608 hits. | Ruff S608 is specifically for SQL built through string construction. The code has many inline rationales, but the global ignore prevents new unreviewed S608 sites from surfacing in normal lint. |
| M2 | Open | High | `.bandit` globally skips `B608`; direct `bandit -r src sdk integrations -t B608` shows 21 skipped B608 tests due `# nosec` comments and zero reported issues. | Bandit B608 is the same SQL-construction risk family. A global skip plus local `nosec` means the regular Bandit gate cannot distinguish justified SQL builders from accidental new interpolation. |
| M3 | Open | Medium-high | `pyproject.toml:178` has `disallow_untyped_defs = false`; strict mypy on `src/quality` reports 4 `no-untyped-def` errors in 3 files; strict checks on larger `src/serving` slices timed out locally. | mypy supports per-module strictness. Current config opts into checking function bodies but does not require typed function boundaries, so this remains a real quality gate gap, especially for serving and quality modules. |
| M4 | Open | High | `helm/agentflow/values.yaml:218-236` and `config/api_keys.yaml` contain bcrypt API-key verifier hashes; chart Secret template renders those values into Kubernetes Secret data. | ASVS 13.3 expects backend secrets and API keys to be managed outside source and build artifacts. Bcrypt hashes are safer than plaintext keys, but they are still reusable offline-verification material and should not be treated as harmless sample config in production-shaped defaults. |
| M7 | Open | Medium-high | No workflow or script matching rollback/cosigned release recovery exists; `staging-deploy.yml` brings up kind staging and tears it down but has no release-revision recovery path. | Kubernetes reports failed rollout progress and explicitly notes higher-level orchestrators can act on it. Helm has first-class release revision rollback. Current repo has probes and rolling update settings, but not a recorded recovery path for failed chart revisions. |
| M8 | Open / target advisory | Medium | CI uses `--cov-fail-under=60` in `.github/workflows/ci.yml`; `coverage.xml` currently reports `line-rate="0.623"`; `codecov.yml` has patch target `80%` but project target is `auto`. | pytest-cov can enforce a total minimum; Codecov can gate project and patch status. With current measured total coverage near 62.3%, the audit's 75% target is directionally sound but not an immediate green threshold without added tests or narrower per-module gates. |
| M9 | Open | High | API usage is stored in local DuckDB tables `api_usage` and `api_sessions`; `api_sessions` uses `INSERT OR REPLACE`; no `api_usage.audit` Kafka topic, external log sink, SIEM export, or immutability control is present. | ASVS 16.1/16.4 requires documented log inventory, protected logs that cannot be modified, and transmission to a logically separate system. Current telemetry is useful operational evidence, but not an immutable audit log. |
| L6 | Open | High | Security workflow runs Trivy SARIF image scan only; no `syft`, `trivy --format cyclonedx/spdx`, `trivy sbom`, SPDX, or CycloneDX artifact generation is present. | Syft and Trivy both support SPDX/CycloneDX SBOM generation. Existing Trivy scanning is useful but does not produce a consumable SBOM artifact. |
| L7 | Open | High | No `cosign`, `sigstore`, SLSA generator, container signing, or container provenance step is present. PyPI/npm OIDC publishing exists, but container image signing is not evidenced. | Sigstore Cosign supports keyless OIDC container signatures, and SLSA provenance describes verifiable build origin. Current release pipeline does not evidence signed container images or container provenance. |

## Notes by risk cluster

### Storage and serving topology

H3 and H6 are coupled. The chart default runs more than one API replica against a DuckDB file on a `ReadWriteOnce` PVC, while DuckDB's documented concurrency model is one read/write process or multiple read-only processes. The app has an optional ClickHouse backend (`config/serving.yaml`, `src/serving/backends/__init__.py`, `docker-compose.prod.yml`), and ClickHouse documentation provides table-level replication semantics through Replicated MergeTree engines and Keeper coordination. That supports the audit's architectural concern: DuckDB is still credible for local/single-node serving, not for the current default chart's multi-replica writer shape.

DuckDB encryption is available in the installed local version, but AgentFlow does not use its encrypted attach path. The current local DB check is direct evidence for two files: `agentflow_api.duckdb` and `agentflow_demo_api.duckdb` are not encrypted. `agentflow_demo.duckdb` could not be assessed because WAL replay failed with an internal DuckDB error; that failure is not an encryption proof.

### CI, IaC, and release evidence

H4 is not a pure code absence anymore. The repo contains an OIDC Terraform module and a disabled workflow with the correct GitHub `id-token: write` permission. The remaining problem is evidence and readiness: no non-example tfvars, no active job, and no proof of successful role assumption. Current Terraform docs also make the S3 backend locking detail worth revisiting because DynamoDB-based locking is now deprecated.

L6/L7 remain straightforward supply-chain gaps. Trivy scanning is present and pinned, but SBOM generation, container signing, and container provenance are absent.

### Security verification and evidence

H5 is best treated as an attestation boundary, not a code defect. The handoff document already captures the right fields and no-go conditions. OWASP WSTG supports the conclusion that internal scans, source review, and CI gates are valuable but incomplete as a substitute for documented security testing results.

M9 is similar: the app has useful local auditability, but ASVS distinguishes security logs as protected forensic assets. Mutable DuckDB analytics tables and local backup artifacts are not enough to claim immutable audit logging.

### Static analysis and quality gates

M1/M2 are real because the SQL interpolation surface is broad. Many current hits are probably intentional identifier assembly through allowlists, but global ignores make future accidental interpolation harder to catch. The better source-aligned posture is narrow suppressions with rationale and a gate that fails on new unreviewed SQL construction.

M3 is confirmed at least in `src/quality`; strict `src/serving` checks are heavy enough locally that a staged module approach is more realistic than flipping the global flag in one pass.

M8 is open, but the measured baseline matters: total line coverage is 62.3%, so a 75% hard floor would currently fail. Patch coverage is already configured at 80%, which partially offsets the low total floor for changed lines.

## Confidence summary

| Theme | Confidence | Basis |
|---|---:|---|
| H3/H6 storage risk | High | Direct chart/code evidence plus Kubernetes and DuckDB primary docs. |
| H4 IaC/OIDC evidence gap | High | Direct workflow/module evidence plus GitHub/Terraform docs. |
| H5 verification boundary | High | Direct handoff docs plus OWASP WSTG/ASVS. |
| M1/M2 SQL static-analysis gap | High | Direct config and tool output plus Ruff/Bandit docs. |
| M3 typing gap | Medium-high | Direct config and partial strict mypy output; larger serving strict check timed out. |
| M4 secrets-in-values gap | High | Direct Helm/config evidence plus ASVS 13.3. |
| M7 recovery gap | Medium-high | Direct workflow search plus Kubernetes/Helm docs. |
| M8 coverage gate | Medium | Direct CI/config/coverage.xml evidence; threshold target is policy-dependent. |
| M9 immutable audit log | High | Direct code evidence plus ASVS logging protection requirements. |
| L6/L7 supply-chain metadata/signing | High | Direct workflow search plus Syft/Trivy/Sigstore/SLSA docs. |
