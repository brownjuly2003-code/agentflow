# AgentFlow Open Audit Items — Post-Remediation Research
**Date:** 2026-05-05
**Scope:** H3/H4/H5/H6, M1/M2/M3/M4/M7/M8/M9, L6/L7
**Sources:** Kubernetes/DuckDB/ClickHouse docs, GitHub Actions OIDC/Terraform docs, OWASP ASVS 5.0.0, SLSA/Sigstore, Syft/Trivy, Bandit/Ruff/mypy docs, Confluent Kafka best practices.

---

## 1. Remediation Package 2026-05-05 — What Was Applied

| ID | Status | Evidence |
|----|--------|----------|
| H1 | **CLOSED** | `Dockerfile.api` now uses multi-stage build + `python -m build --wheel` + `pip install "${wheel}[cloud]"` |
| H2 | **CLOSED** | `.dockerignore` created with exclusions for `.env`, `*.pem`, `*.duckdb`, `mutants/`, `node_modules/`, etc. |
| L1 | **CLOSED** | `HEALTHCHECK` added to `Dockerfile.api` |
| L3 | **CLOSED** | Multi-stage build implemented in `Dockerfile.api` |
| M5 | **CLOSED** | `minio/minio:latest` replaced with pinned tag `RELEASE.2025-09-07T16-13-09Z` in `docker-compose.yml` |

**Remaining open items** (this report covers):
🔴 **H3, H4, H5, H6**
🟡 **M1, M2, M3, M4, M7, M8, M9**
🟢 **L6, L7**

---

## 2. 🔴 High Priority Items

### H3 — DuckDB in K8s with `ReadWriteOnce` PVC at `replicaCount: 2`

**Current state:** `helm/agentflow/values.yaml` sets `replicaCount: 2` with `ReadWriteOnce` PVC. Each pod gets its own DuckDB file. There is no shared writer storage.

**Primary-source best practice:**
- **DuckDB docs** (2026-01, DuckDB Developer Meeting): DuckDB is designed as an in-process, single-writer analytical database. It does not support multi-writer shared storage natively.
- **Kubernetes docs**: `ReadWriteOnce` guarantees exclusive write access to one node at a time. Running 2+ replicas with separate `ReadWriteOnce` PVCs = data divergence, not replication.
- **ClickHouse docs**: For production serving with replicas, ClickHouse uses `ReplicatedMergeTree` with ZooKeeper/Keeper coordination — this is the intended path for read-scale + consistency.

**Recommended action:**
1. **Immediate (architecture decision)**: For production serving, replace DuckDB with ClickHouse backend (already implemented in `src/serving/backends/clickhouse_backend.py`).
2. **If DuckDB must remain** (local/pilot): Force `replicaCount: 1`, disable HPA, and document "single writer" explicitly. Use DuckDB only for local/dev workloads.
3. **Deploy action**: Update `helm/agentflow/values.yaml` — add comment block: `# WARNING: DuckDB does not support multi-writer. Set replicaCount=1 for DuckDB backend.`
4. **Push action**: Add CI gate in `helm lint` that fails if `replicaCount > 1 && serving_backend == "duckdb"`.

**Paid action:** None required for pilot; for production, managed ClickHouse (e.g., Altinity Cloud, ClickHouse Cloud) is recommended if self-hosting is not viable.

---

### H4 — AWS Terraform Apply Disabled, OIDC Not Configured

**Current state:** `.github/workflows/terraform-apply.yml` has `if: false` (disabled 2026-04-23). `AWS_TERRAFORM_ROLE_ARN` is missing. No `staging.tfvars` or `production.tfvars` exists.

**Primary-source best practice:**
- **GitHub Actions OIDC docs** (docs.github.com, 2026-03-10): Use `id-token: write` + `aws-actions/configure-aws-credentials` with `role-to-assume`. Trust policy must validate `token.actions.githubusercontent.com:sub` to prevent token hijacking from other repos.
- **Terraform docs** (developer.hashicorp.com, 2025): State backend = S3 + DynamoDB locking. Never run `terraform apply` from local machines for shared state.
- **AWS docs**: IAM trust policy should use `StringEquals` on `aud: sts.amazonaws.com` and `sub: repo:ORG/REPO:environment:ENV`.

**Recommended action (deploy/apply/push):**
1. **Deploy (AWS console)**: Create IAM OIDC IdP for `https://token.actions.githubusercontent.com`. Create IAM role `AgentFlowTerraform` with trust policy restricted to `repo:yuliaedomskikh/agentflow:environment:staging` and `production`.
2. **Apply (repo settings)**: Add repository variables `AWS_TERRAFORM_ROLE_ARN` and `AWS_REGION`. Add GitHub Environments `staging` + `production` with required reviewers.
3. **Push**: Create `infrastructure/terraform/environments/staging.tfvars` with non-sensitive defaults. Keep `production.tfvars` in a separate private repo or AWS SSM/Secrets Manager — do NOT commit to public repo.
4. **Push**: Re-enable workflow by removing `if: false` and restoring `if: inputs.confirm == 'APPLY'`.
5. **Apply**: Run a green `terraform plan` in staging via workflow_dispatch, capture plan output as artifact, then enable `apply`.

**Paid action:** None; AWS Free Tier covers S3 + DynamoDB for state. If using Terraform Cloud for remote execution, ~$20/user/mo.

---

### H5 — No External Penetration Test Evidence

**Current state:** No pentest report in `docs/audits/` or repo. No attestation from third-party security firm.

**Primary-source best practice:**
- **OWASP ASVS 5.0.0** (May 2025): Level 2 (Standard Verification) — recommended for SaaS products handling user data — requires "combination of automated and manual testing, including code and documentation review." Level 3 requires "extensive manual verification or penetration testing."
- **PCI DSS / SOC 2 / HIPAA**: External penetration testing is explicitly required at least annually and after significant infrastructure changes.
- **Industry standard** (Triaxiom 2026): Annual third-party external pentest is baseline. Cost for a SaaS API platform: $8,000–$25,000 depending on scope.

**Recommended action:**
1. **Paid action**: Engage a CREST-certified firm (Bishop Fox, Cobalt, Trail of Bits, or Synack) for ASVS Level 2-aligned external pentest. Scope: API layer (`/v1/*`), admin endpoints, tenant isolation, SQL guard bypass attempts.
2. **Deploy**: Add `docs/audits/2026-05-external-pentest/` directory with scope, rules of engagement, and final report (redacted for public repo if needed).
3. **Push**: After report delivery, create GitHub issue per finding with `pentest-finding` label and remediation tracking.

**Cost estimate:** $10,000–$20,000 for solo/SMB-focused scope.

---

### H6 — DuckDB Encryption at Rest Not Documented/Proven

**Current state:** No evidence that `.duckdb` files use encryption. `config/duckdbPath: /data/agentflow.duckdb` in Helm values has no encryption key management.

**Primary-source best practice:**
- **DuckDB docs** (2025-11-19, "Data-at-Rest Encryption in DuckDB"): Since v1.4.0, DuckDB supports transparent AES-GCM-256 encryption via `ATTACH ... (ENCRYPTION_KEY '...', ENCRYPTION_CIPHER 'GCM')`.
- **Critical caveat**: "DuckDB's encryption does not yet meet the official NIST requirements" (issue #20162). For GDPR/HIPAA, this is a **blocker** — DuckDB encryption alone is insufficient for regulated data.
- **Alternative**: Use encrypted PVC (AWS EBS with KMS, GCP Persistent Disk with CMEK) or migrate to ClickHouse (supports AES encryption at rest via `encryption_codec`).

**Recommended action:**
1. **Immediate**: If targeting GDPR/HIPAA — **do not rely on DuckDB encryption**. Migrate production serving to ClickHouse with encrypted volumes.
2. **Pilot/dev**: If DuckDB is used for non-regulated data, add encryption key injection via Kubernetes Secret:
   ```yaml
   env:
     - name: DUCKDB_ENCRYPTION_KEY
       valueFrom:
         secretKeyRef:
           name: duckdb-encryption-key
           key: key
   ```
3. **Deploy**: Update `src/serving/backends/duckdb_backend.py` to pass encryption key on `ATTACH` when `DUCKDB_ENCRYPTION_KEY` is set.
4. **Push**: Add ADR `docs/decisions/ADR-012-duckdb-encryption.md` documenting the NIST-compliance gap and ClickHouse migration rationale.

**Paid action:** Managed ClickHouse Cloud includes at-rest encryption by default (~$200+/mo for production workload).

---

## 3. 🟡 Medium Priority Items

### M1 — Ruff Ignores `S608` (SQL Injection) Globally

**Current state:** `pyproject.toml` has `ignore = ["S101", "S311", "S608"]` under `[tool.ruff.lint]`.

**Primary-source best practice:**
- **Ruff docs** (docs.astral.sh): `per-file-ignores` is the preferred mechanism for scoped suppressions. Global `ignore` on security rules (`S*`) is an anti-pattern for growing codebases.
- **OWASP ASVS 5.0.0 V1/V5**: SQL injection must be prevented via parameterized queries AND static analysis gates.

**Recommended action (push):**
1. Remove `"S608"` from global `ignore`.
2. Add scoped `per-file-ignores` ONLY for files with verified `sqlglot` guards:
   ```toml
   [tool.ruff.lint.per-file-ignores]
   "src/serving/semantic_layer/query_engine.py" = ["S608"]
   "src/serving/backends/duckdb_backend.py" = ["S608"]
   ```
3. Add `# noqa: S608` comments on individual lines where `sqlglot` AST validation is proven, with justification.
4. Add CI gate: if `S608` is added to global ignore in a PR, fail review.

**Cost:** Free. Effort: ~30 min.

---

### M2 — Bandit Skips `B608` Globally

**Current state:** `.bandit` has `skips = B101,B311,B608`.

**Primary-source best practice:**
- **Bandit docs** (bandit.readthedocs.io): `skips` in `.bandit` applies globally. Per-file suppression should use `# nosec: B608` on validated lines, or use multiple config files for different paths.
- Best practice: keep baseline minimal, suppress locally with justification.

**Recommended action (push):**
1. Change `.bandit` to: `skips = B101,B311` (remove B608).
2. In `src/serving/semantic_layer/query_engine.py` and other sqlglot-validated paths, add `# nosec: B608` with inline comment: `# sqlglot AST guard validates no DDL/DML and tenant scoping`.
3. Update `scripts/bandit_diff.py` to treat newly introduced B608 findings as blocking (if not annotated).

**Cost:** Free. Effort: ~30 min.

---

### M3 — mypy `disallow_untyped_defs = false`

**Current state:** Global `disallow_untyped_defs = false`. Flink paths are fully ignored (`ignore_errors = true`).

**Primary-source best practice:**
- **mypy docs** (mypy.readthedocs.io, 2026-04-12): `disallow_untyped_defs = true` is part of `--strict` mode. For incremental adoption, use per-module overrides.
- Per-module example from docs:
  ```toml
  [[tool.mypy.overrides]]
  module = "src.serving.*"
  disallow_untyped_defs = true
  ```

**Recommended action (push):**
1. Set global `disallow_untyped_defs = true`.
2. Add overrides for legacy/experimental paths:
   ```toml
   [[tool.mypy.overrides]]
   module = ["src.processing.flink_jobs.*", "tests.*"]
   disallow_untyped_defs = false
   ```
3. Run `mypy src/` — fix newly surfaced untyped defs in `src/serving/`, `src/quality/`, `src/ingestion/`.
4. Target: 100% typed defs in `src/serving/` and `src/quality/` within 2 sprints.

**Cost:** Free. Effort: 2–4 hours of typing fixes.

---

### M4 — Helm Values Contain bcrypt Hashes

**Current state:** `helm/agentflow/values.yaml` contains:
```yaml
secrets:
  apiKeys:
    keys:
      - key_hash: "$2b$12$UNE9Vh..."
```

**Primary-source best practice:**
- **Kubernetes docs / External Secrets Operator docs** (external-secrets.io, 2025): For production, use External Secrets Operator (ESO) or Vault Agent Injector. Helm values should reference external secrets, never contain hashes/credentials.
- **Helm best practices** (cycode.com, 2025): "Prefer SOPS or External Secrets Operator for production."

**Recommended action (deploy/apply):**
1. **Deploy (K8s)**: Install External Secrets Operator:
   ```bash
   helm repo add external-secrets https://charts.external-secrets.io
   helm install external-secrets external-secrets/external-secrets -n external-secrets --create-namespace
   ```
2. **Apply**: Create `SecretStore` (or `ClusterSecretStore`) pointing to AWS Secrets Manager / Vault / 1Password.
3. **Push**: Replace hardcoded hashes in `values.yaml` with:
   ```yaml
   secrets:
     apiKeys:
       externalSecretRef:
         name: agentflow-api-keys
         key: api_keys.yaml
   ```
4. **Push**: Add template `templates/external-secret.yaml` to fetch secret from external store into K8s Secret.
5. **Local/dev fallback**: Keep a `values-local.yaml` with demo hashes (non-production), never used in staging/prod.

**Paid action:** AWS Secrets Manager ~$0.40/secret/mo. HashiCorp Vault HCP starts at ~$0.03/hour. For solo dev, 1Password Secrets Automation (~$7.99/mo) is also viable.

---

### M7 — No Rollback Workflow

**Current state:** `staging-deploy.yml` deploys to Kind but has no rollback on failure. No production rollback workflow exists.

**Primary-source best practice:**
- **Helm docs**: `helm rollback <release> <revision>` restores previous known-good state. `--atomic` flag on `helm upgrade` auto-rolls back on failure.
- **GitHub Actions best practice** (oneuptime.com, 2026-02): Capture `previous_revision` before deploy, trigger rollback job `if: failure()`.

**Recommended action (push):**
1. Add `helm rollback` job to `staging-deploy.yml` (and create `production-deploy.yml`):
   ```yaml
   deploy:
     outputs:
       previous_revision: ${{ steps.get_revision.outputs.prev }}
     steps:
       - id: get_revision
         run: |
           REV=$(helm history agentflow -n agentflow -o json | jq -r 'last | .revision')
           echo "prev=$REV" >> $GITHUB_OUTPUT
       - run: helm upgrade --install agentflow ./helm/agentflow -f values.yaml --wait --timeout 10m --atomic

   rollback:
     needs: deploy
     if: failure()
     steps:
       - run: helm rollback agentflow ${{ needs.deploy.outputs.previous_revision }} -n agentflow --wait
   ```
2. Add `--atomic` to all `helm upgrade` commands for automatic rollback on failed release.
3. Document rollback runbook in `docs/runbook.md`.

**Cost:** Free.

---

### M8 — Coverage Gate 60% is Low

**Current state:** `pytest --cov-fail-under=60` in CI. Core modules (auth, query engine, rate limiter) should have higher assurance.

**Primary-source best practice:**
- **pytest-cov docs** (pypi.org, 2026-03): `--cov-fail-under` supports per-module precision. Combine with `coverage report --fail-under=X`.
- **Industry standard** (python-basics-tutorial, 2026-04): 80% is common baseline for Python services; 60% is acceptable only for experimental modules.

**Recommended action (push):**
1. Keep 60% as global floor, add per-module gates:
   ```toml
   [tool.coverage.report]
   fail_under = 60

   [tool.coverage.report.paths]
   source = ["src"]
   ```
2. Add separate CI job for core modules with higher threshold:
   ```bash
   pytest tests/unit/ tests/property/ --cov=src.serving.api.auth,src.serving.semantic_layer.query_engine,src.serving.api.rate_limiter --cov-fail-under=85
   ```
3. Use Codecov "patch" status (already configured) to enforce 80% on changed code.

**Cost:** Free.

---

### M9 — No Immutable Audit Log

**Current state:** `api_usage` table writes to DuckDB — mutable, deletable. No Kafka topic for compliance audit trail.

**Primary-source best practice:**
- **Confluent / Kafka docs** (2025-10, 2026-04): Audit logs should go to a dedicated topic with `retention.ms=-1` (infinite retention) + strict ACLs preventing deletion. For long-term compliance, sink to WORM object storage (S3 Object Lock).
- **Conduktor glossary** (2026-04): "Immutable Storage: Write audit logs to append-only storage or use Kafka topics with `retention.ms=-1` and strict ACLs preventing deletion."

**Recommended action (deploy/push):**
1. **Push**: Add Kafka topic bootstrap in `scripts/kafka_topics_init.py`:
   ```python
   topics.append(NewTopic(name="api_usage.audit", num_partitions=6, replication_factor=3, config={"retention.ms": "-1", "cleanup.policy": "delete"}))
   ```
2. **Push**: Update `src/serving/api/analytics.py` to dual-write: DuckDB (queryable) + Kafka topic (immutable).
3. **Deploy**: Configure Kafka Connect to sink `api_usage.audit` to S3 bucket with S3 Object Lock (WORM) for 7-year retention (GDPR/HIPAA).
4. **Deploy**: Add Kafka ACLs denying `Delete` on `api_usage.audit` topic to all non-admin principals.

**Paid action:** S3 storage cost for audit logs is negligible (~$0.023/GB/mo). No paid tooling required.

---

## 4. 🟢 Low Priority Items

### L6 — No SBOM Generation

**Current state:** `security.yml` runs Trivy vulnerability scan but does not generate SBOM artifacts.

**Primary-source best practice:**
- **SLSA / Syft docs** (2025-11, 2026-04): Generate SBOMs in SPDX or CycloneDX format for every release. Tools: Syft (fast, multi-format), Trivy (already in use), or CycloneDX build plugins.
- **Wiz.io / Branch8** (2025-12, 2026-04): SBOMs must be generated at build time, stored as OCI artifacts or alongside releases. They stale quickly — automate in CI.

**Recommended action (push):**
1. Add SBOM generation step to `security.yml` (or `publish-pypi.yml`):
   ```yaml
   - name: Generate SBOM
     uses: anchore/sbom-action@v0
     with:
       image: agentflow-api:${{ github.sha }}
       format: spdx-json
       output-file: sbom.spdx.json
   ```
2. Attach SBOM to GitHub Release assets (for Python packages) and/or container registry as OCI artifact using `oras attach`.
3. For Python-specific SBOM, also use `cyclonedx-py` on `requirements.txt` + `pyproject.toml` to capture exact dependency tree.

**Cost:** Free. Syft and `anchore/sbom-action` are open-source.

---

### L7 — No Signed Container Images

**Current state:** API Docker image is built in CI but not cryptographically signed. No SLSA provenance attestation.

**Primary-source best practice:**
- **Sigstore / Cosign docs** (2026-01, 2026-03): Keyless signing via GitHub OIDC + Fulcio is now standard. No key management needed.
- **SLSA GitHub Generator** (slsa.dev, 2023; updated 2025): Use `slsa-framework/slsa-github-generator/.github/workflows/generator_container_slsa3.yml` for SLSA Level 3 provenance.
- **GitHub artifact attestations** (2026): `actions/attest-build-provenance@v2` is native GitHub support for SLSA provenance.

**Recommended action (push):**
1. **Option A — Cosign keyless signing** (fastest, ~10 lines):
   ```yaml
   - uses: sigstore/cosign-installer@v3
   - run: cosign sign --yes ghcr.io/OWNER/agentflow-api@${{ steps.build.outputs.digest }}
   ```
2. **Option B — GitHub native attestation** (SLSA provenance, ~5 lines):
   ```yaml
   - uses: actions/attest-build-provenance@v2
     with:
       subject-name: ghcr.io/OWNER/agentflow-api
       subject-digest: ${{ steps.build.outputs.digest }}
       push-to-registry: true
   ```
3. **Option C — Both (recommended)** for maximum compatibility with enterprise consumers using Kyverno/OPA Gatekeeper.
4. Add verification instructions to `docs/security-audit.md`:
   ```bash
   cosign verify ghcr.io/OWNER/agentflow-api:v1.1.0 \
     --certificate-identity-regexp="https://github.com/OWNER/agentflow/" \
     --certificate-oidc-issuer="https://token.actions.githubusercontent.com"
   ```

**Cost:** Free. Sigstore/Cosign and GitHub attestations are free for public repos.

---

## 5. Summary Table: Actions & Costs

| ID | Priority | Action Type | Effort | Cost | Owner |
|----|----------|-------------|--------|------|-------|
| H3 | 🔴 High | Architecture + Push | 1–2 days | Free | Architecture |
| H4 | 🔴 High | Deploy (AWS) + Push | 2–4 hours | Free | DevOps |
| H5 | 🔴 High | **Paid** pentest | 2–4 weeks | $10k–$20k | Security |
| H6 | 🔴 High | Architecture + Deploy | 1–2 days | Free / ClickHouse Cloud | Security |
| M1 | 🟡 Med | Push (config) | 30 min | Free | Dev |
| M2 | 🟡 Med | Push (config) | 30 min | Free | Dev |
| M3 | 🟡 Med | Push (typing) | 2–4 hours | Free | Dev |
| M4 | 🟡 Med | Deploy (K8s) + Push | 4–8 hours | ~$0.40/secret/mo | DevOps |
| M7 | 🟡 Med | Push (workflow) | 1–2 hours | Free | DevOps |
| M8 | 🟡 Med | Push (CI config) | 1 hour | Free | Dev |
| M9 | 🟡 Med | Deploy (Kafka) + Push | 4–8 hours | S3 storage only | DevOps |
| L6 | 🟢 Low | Push (CI) | 30 min | Free | DevOps |
| L7 | 🟢 Low | Push (CI) | 30 min | Free | DevOps |

---

## 6. Recommended Next Steps (Ordered)

1. **This week**: Close M1, M2, M3, M7, L6, L7 — all are config-only, zero-cost pushes.
2. **This week**: Close H4 — enable AWS OIDC + terraform-apply workflow (DevOps deploy).
3. **Next 2 weeks**: Close M4 — migrate Helm secrets to External Secrets Operator (pilot with AWS Secrets Manager).
4. **Next 2 weeks**: Close M8 — raise core module coverage gate to 85%.
5. **Next month**: Close M9 — create immutable audit Kafka topic + S3 sink.
6. **Next month**: Close H3 — production decision: ClickHouse-only serving OR single-replica DuckDB with explicit architecture doc.
7. **Next quarter**: Close H5 — schedule external pentest (Bishop Fox / Cobalt).
8. **Next quarter**: Close H6 — either ClickHouse migration (recommended) or encrypted volume + documented NIST gap.

---

*Report compiled from primary sources: DuckDB.org (2025-11, 2026-01), Kubernetes.io, GitHub Actions docs (2026-03), Terraform docs (2025), OWASP ASVS 5.0.0 (2025-05), SLSA.dev, Sigstore/Cosign docs (2026), Syft/Trivy docs (2026), Bandit/Ruff/mypy docs, Confluent/Conduktor Kafka best practices (2025-2026).*
