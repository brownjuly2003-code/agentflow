# AgentFlow audit follow-up: co_res1c

Date: 2026-05-05
Project: `D:\DE_project`
Scope: remaining `audit_kimi_04_05_26.md` items H3/H4/H5/H6, M1/M2/M3/M4/M7/M8/M9, L6/L7 after the local remediation package. Already-closed Docker editable install, `.dockerignore`, healthcheck, pinned MinIO tags, Helm image tag `1.1.0`, and request body size middleware are treated as out of scope.

This report does not propose deploy/apply/push/paid actions. It records local evidence, current primary-source guidance, and closure boundaries.

## Baseline

- HEAD: `10bc3c7868fad2849c59023f34dbf8d8e12f40c0`
- Tracked file count: `673`
- Bundle/key baseline: no root frontend bundle and no i18n/locales key set were found. Existing Python dist artifacts are `dist/agentflow_runtime-1.1.0-py3-none-any.whl` at `154498` bytes and `dist/agentflow_runtime-1.1.0.tar.gz` at `124555` bytes.
- Current worktree already had remediation/doc changes before this file; `co_res1c.md` did not exist before this report.

## Current best-practice anchors

- GitHub Actions OIDC: GitHub documents OIDC as the way for workflows to access AWS without long-lived GitHub secrets, with `id-token: write`, `aws-actions/configure-aws-credentials`, and cloud trust conditions on `aud` and especially `sub`. AWS does not support GitHub custom OIDC claims, so branch/environment/repo constraints must be represented through supported trust-policy conditions. Sources: [GitHub OIDC reference](https://docs.github.com/en/actions/reference/security/oidc), [GitHub OIDC in AWS](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws).
- Terraform automation: HashiCorp documents `init -input=false`, `plan -out=tfplan -input=false`, reviewed plan, and `apply -input=false tfplan` as the core automation shape. For plan/apply on different machines, the robust strategy is to archive the whole working directory including `.terraform` and restore it at the same absolute path. Production manual review is still the strong default; `-auto-approve` is framed for non-critical contexts. Source: [Running Terraform in automation](https://developer.hashicorp.com/terraform/tutorials/automation/automate-terraform).
- Terraform S3 backend: current docs support S3 lockfile locking via `use_lockfile = true`; DynamoDB locking is deprecated and slated for removal in a future minor version. State and plan files can contain sensitive data, so credentials should stay in environment variables and state should be remote, encrypted, access-controlled, and auditable. Sources: [Terraform S3 backend](https://developer.hashicorp.com/terraform/language/backend/s3), [Terraform sensitive data](https://developer.hashicorp.com/terraform/language/manage-sensitive-data).
- Helm rollback behavior changed across major versions: Helm 4 current docs expose `--rollback-on-failure`; Helm 3 docs expose `--atomic`. A repo should not depend on an implicit rollback if neither mechanism nor an explicit `helm rollback` path is present. Sources: [Helm upgrade](https://helm.sh/docs/helm/helm_upgrade/), [Helm rollback](https://helm.sh/docs/helm/helm_rollback/).

## Item verdicts

| Item | Status | Local evidence | Source-aligned verdict |
|---|---|---|---|
| H3 | Open | `helm/agentflow/values.yaml:4` keeps `replicaCount: 2`; `:39` keeps HPA `minReplicas: 2`; `:46` keeps `ReadWriteOnce`; `:117-118` keep DuckDB DB paths. Deployment mounts the same PVC into replicas. `config/serving.yaml:1` defaults to `backend: duckdb`. | Kubernetes says `ReadWriteOnce` can still allow multiple pods on one node and does not enforce write protection after mount; only `ReadWriteOncePod` constrains to one pod. DuckDB says one process can read/write, multiple processes can only read in read-only mode, and native multi-process writes are unsupported. The chart default remains unsafe for DuckDB-backed multi-replica serving. Confidence: High. |
| H4 | Open / external evidence gap | `.github/workflows/terraform-apply.yml:20` has `id-token: write` and lines `47-49`/`94-96` use `aws-actions/configure-aws-credentials@v4` with `vars.AWS_TERRAFORM_ROLE_ARN`, but both jobs are disabled at `:31` and `:75`. Docs record missing `AWS_TERRAFORM_ROLE_ARN`, real tfvars, and OIDC proof. `infrastructure/terraform/main.tf:12-16` uses S3 backend with `dynamodb_table` and no `use_lockfile`. The workflow uploads only `tfplan`, not the full `.terraform` working directory. | The OIDC shape is partially correct, but the local repo lacks evidence that AWS trust, variables, tfvars, and a successful role assumption exist. Terraform backend locking is not current because it still uses deprecated DynamoDB locking without S3 `use_lockfile`. The disabled plan/apply workflow also falls short of HashiCorp's robust cross-machine saved-plan guidance. Confidence: High. |
| H5 | Open / attestation evidence gap | `docs/release-readiness.md:174` records missing third-party tester, report artifact, signed attestation, scope, severity summary, remediation map, retest status, and owner. | OWASP WSTG treats penetration testing as a structured security testing activity with methodology, coverage, and reportable results. Internal scans/source review do not equal external attestation evidence. This is not locally closable by code inspection. Confidence: High. |
| H6 | Open | Local DuckDB version is `1.4.4`. `agentflow_api.duckdb` and `agentflow_demo_api.duckdb` report `encrypted=False, cipher=None` via `duckdb_databases()`. Grep found plain `duckdb.connect(...)` runtime paths and no `ENCRYPTION_KEY`, `ENCRYPTION_CIPHER`, or `temp_file_encryption` runtime/config/workflow path. | DuckDB supports database encryption through `ATTACH ... ENCRYPTION_KEY`, covering main DB, WAL, and temp files, with AES-256 GCM by default, while noting NIST-compliance caveats. AgentFlow has no local proof of encrypted-at-rest DuckDB files. Confidence: High. |
| M1 | Open | `pyproject.toml:119` globally ignores `S608`. `python -m ruff check src sdk integrations --select S608 --isolated` reports `21` S608 findings. | Ruff S608 specifically flags SQL-like strings involved in string building and recommends parameterized queries. Existing inline rationales may be valid, but the global ignore prevents the normal Ruff gate from catching new SQL-construction surfaces. Confidence: High. |
| M2 | Open | `.bandit:3` globally skips `B608`. Direct `python -m bandit -r src sdk integrations -t B608 -f json` reports `_totals.skipped_tests = 21` and no active B608 findings because suppressions are skipped. | Bandit B608 targets string-built SQL injection risk. Current global skip is broader than local reviewed suppressions and keeps the default Bandit gate from distinguishing reviewed paths from new accidental interpolation. Confidence: High. |
| M3 | Open | `pyproject.toml:178` keeps `disallow_untyped_defs = false`. `python -m mypy src\quality --ignore-missing-imports --disallow-untyped-defs` reports `4` errors in `3` files. | mypy supports per-module options and selective `disallow_untyped_defs`. The current setting leaves core quality/serving-adjacent boundaries below that stricter bar. Confidence: High for `src\quality`; Medium-high for wider `src\serving` because it was not fully rerun in this pass. |
| M4 | Open | `helm/agentflow/values.yaml:218-232` contains checked-in bcrypt `key_hash` values under `secrets.apiKeys`; `helm/agentflow/templates/secret.yaml:11` renders those values into a Kubernetes Secret. `config/api_keys.yaml:2` and `:10` also contain bcrypt verifier hashes. | Kubernetes warns that checked-in Secret manifests expose secret data to repo readers and that base64 is not encryption; it also points to external Secret stores as a pattern. Bcrypt hashes are not plaintext keys, but they are still checked-in verifier material. Confidence: High. |
| M7 | Open | `scripts/k8s_staging_up.sh:200-205` uses `helm upgrade --install ... --wait --timeout 5m --debug`. Repo search found no `helm rollback`, no Helm 3 `--atomic`, and no Helm 4 `--rollback-on-failure`. | Helm has explicit rollback and rollback-on-failure semantics. AgentFlow currently has readiness waiting but no checked-in release-revision recovery mechanism. Confidence: Medium-high because exact rollout policy is a project choice, but absence is direct. |
| M8 | Open / threshold advisory | `.github/workflows/ci.yml:67` keeps `--cov-fail-under=60`; `coverage.xml:2` reports line-rate `0.623`; `codecov.yml:5` keeps project target `auto`, while `:9` sets patch target `80%`. | Codecov supports project and patch status targets, including path-specific contexts; pytest-cov enforces a local total floor. The audit's `75%` target is directionally reasonable but not an immediate green total threshold against the measured `62.3%` baseline. Confidence: Medium. |
| M9 | Open | API usage/session telemetry remains local mutable DuckDB tables: `src/serving/api/auth/middleware.py:215` creates `api_usage`; `src/serving/api/analytics.py` uses `api_sessions`; no `api_usage.audit` topic, append-only external sink, tamper-detection, read-only media, or log-management integration was found. | OWASP logging guidance says logs should be protected against tampering, unauthorized modification/deletion, and can be copied to read-only media; Kubernetes audit docs model audit backends as persisted file or external webhook stores. Kafka is an implementation option, not uniquely required by the primary sources, but mutable local DuckDB telemetry does not close immutable/protected audit logging. Confidence: High. |
| L6 | Open | `.github/workflows/security.yml:181-219` runs Trivy SARIF image scanning only. Workflow/script search found no `sbom`, `cyclonedx`, `spdx`, `trivy --format ...`, `trivy sbom`, or Syft generation path. | Trivy can generate CycloneDX and SPDX SBOMs for images/filesystems via `--format`; existing vulnerability scanning is not a consumable SBOM artifact. Confidence: High. |
| L7 | Open / release-scope conditional | Workflow/script search found no `cosign`, `sigstore`, SLSA/provenance, image attestation, or image signing path. PyPI/npm OIDC publishing exists but is not container-image signing. | Sigstore Cosign supports keyless OIDC container signing and attestations. If AgentFlow publishes container images, this remains an open supply-chain control; if it only ships source/PyPI/npm artifacts, the container-specific severity is conditional. Confidence: High for absence, Medium for priority. |

## Synthesis

All requested remaining items are still open, or open with an external evidence boundary. The only material update from current primary sources is H4/M7 nuance:

- H4 is more than "workflow disabled": the OIDC skeleton is present, but local evidence is missing and the Terraform backend/workflow shape is stale against current HashiCorp guidance (`dynamodb_table` locking, no `use_lockfile`, and only `tfplan` archived).
- M7 should be phrased as "no recorded rollback-on-failure mechanism" rather than only "no `helm rollback` workflow", because current Helm 4 and Helm 3 spell the automatic rollback flag differently.
- M9 should not require Kafka specifically as the only compliant answer. The durable requirement is protected/tamper-resistant audit logging outside mutable local analytics tables; Kafka topic `api_usage.audit` is one implementation candidate from the original audit.

Confidence summary:

| Theme | Confidence | Basis |
|---|---:|---|
| OIDC/Terraform readiness | High | Direct workflow/backend evidence plus GitHub and HashiCorp docs. |
| DuckDB/Kubernetes storage risk | High | Direct chart/config evidence plus Kubernetes PV and DuckDB concurrency/encryption docs. |
| Static-analysis and typing gates | High | Direct config plus targeted Ruff/Bandit/mypy command outputs. |
| Secrets/audit/supply-chain gaps | High | Direct repo absence plus Kubernetes, OWASP, Trivy, and Sigstore primary docs. |
| Coverage threshold | Medium | Current `62.3%` is factual; exact target remains policy-dependent. |

## Primary sources consulted

- GitHub: [OpenID Connect reference](https://docs.github.com/en/actions/reference/security/oidc)
- GitHub: [Configuring OpenID Connect in Amazon Web Services](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws)
- HashiCorp: [Running Terraform in automation](https://developer.hashicorp.com/terraform/tutorials/automation/automate-terraform)
- HashiCorp: [Terraform S3 backend](https://developer.hashicorp.com/terraform/language/backend/s3)
- HashiCorp: [Manage sensitive data in your configuration](https://developer.hashicorp.com/terraform/language/manage-sensitive-data)
- Kubernetes: [Persistent Volumes](https://kubernetes.io/docs/concepts/storage/persistent-volumes/)
- Kubernetes: [Good practices for Kubernetes Secrets](https://kubernetes.io/docs/concepts/security/secrets-good-practices/)
- Kubernetes: [Auditing](https://kubernetes.io/docs/tasks/debug/debug-cluster/audit/)
- DuckDB: [Concurrency](https://duckdb.org/docs/current/connect/concurrency)
- DuckDB: [ATTACH and database encryption](https://duckdb.org/docs/current/sql/statements/attach)
- Ruff: [S608 hardcoded SQL expression](https://docs.astral.sh/ruff/rules/hardcoded-sql-expression/)
- Bandit: [B608 hardcoded SQL expressions](https://bandit.readthedocs.io/en/latest/plugins/b608_hardcoded_sql_expressions.html)
- mypy: [Configuration file and per-module options](https://mypy.readthedocs.io/en/stable/config_file.html)
- Helm: [helm upgrade](https://helm.sh/docs/helm/helm_upgrade/), [helm rollback](https://helm.sh/docs/helm/helm_rollback/)
- Codecov: [Status checks](https://docs.codecov.com/docs/commit-status)
- OWASP: [Web Security Testing Guide](https://owasp.org/www-project-web-security-testing-guide/), [Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html)
- Trivy: [SBOM](https://trivy.dev/docs/latest/supply-chain/sbom/)
- Sigstore: [Signing containers with Cosign](https://docs.sigstore.dev/cosign/signing/signing_with_containers/)
