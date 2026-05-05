# Task 4: External Gates — Owner-Provided Evidence Requirements

**Scope:** H3/H4/H5/H6, M1/M2/M3/M4/M7/M8/M9, L6/L7
**Context:** Remediation 2026-05-05 closed H1/H2/L1 (Docker), M5 (MinIO pin), M10 (Helm tag), M12 (request body middleware).
**Rule:** No external gate may be marked `complete` without explicit, verifiable evidence supplied by the designated owner.

---

## 1. External vs Local Classification

| ID | Item | Type | Rationale |
|----|------|------|-----------|
| **H3** | DuckDB in K8s (`ReadWriteOnce` PVC × 2 replicas) | **External gate** | Requires either provisioned ClickHouse cluster (infra owner) or signed architecture exception (product owner). Cannot be verified by code change alone. |
| **H4** | AWS Terraform apply disabled / OIDC absent | **External gate** | Requires AWS account owner to create IAM OIDC provider + role + `tfvars`. Local code changes (workflow `if: true`) are insufficient without successful apply evidence. |
| **H5** | No external penetration test | **External gate** | Requires third-party security vendor engagement and deliverables. Local remediation cannot substitute attestation. |
| **H6** | DuckDB at-rest encryption not proven | **External gate** | Requires security/compliance owner to provide cryptographic verification output or cloud-volume encryption attestation. |
| **M1** | Ruff global ignore `S608` | Local fix | Config-only change (`pyproject.toml` per-file ignores). |
| **M2** | Bandit global skip `B608` | Local fix | Config-only change (`.bandit` per-file skips). |
| **M3** | mypy `disallow_untyped_defs = false` | Local fix | Config-only change + incremental typing. |
| **M4** | Helm values contain bcrypt hashes | **External gate** | Requires deployed external secret manager (Vault / ESO / AWS SM) and migration of hashes. Local chart templating alone does not close the gate. |
| **M7** | No rollback workflow | Local fix | New GitHub Action workflow file + `helm rollback` command. |
| **M8** | Coverage gate 60 % too low | Local fix | `pyproject.toml` / `pytest.ini` threshold change + test additions. |
| **M9** | No immutable audit log | **External gate** | Requires platform/Kafka owner to create `api_usage.audit` topic with infinite retention and verify writes/reads. Local producer code change is not enough. |
| **L6** | No SBOM generation | Local fix | Add `syft` / `trivy sbom` step to existing CI workflow. |
| **L7** | No signed container images | **External gate** | Requires Sigstore/cosign key ceremony and published public key / verification policy. CI step alone without key evidence leaves gate open. |

---

## 2. Required Evidence per External Gate

### H3 — DuckDB K8s Architecture Decision
**Owner:** Architecture / Platform
**Evidence required:**
1. **Decision record** (ADR or ticket) selecting one of:
   - ClickHouse production cluster sizing & connection string committed to `helm/values-prod.yaml` (redacted), **or**
   - Signed risk acceptance document acknowledging split-brain under `replicaCount > 1` with `ReadWriteOnce` PVC.
2. **Operational proof:**
   - If ClickHouse: `SELECT 1` from pod in target namespace + HPA / podDisruptionBudget manifests for ClickHouse.
   - If single-replica DuckDB: Helm values showing `replicaCount: 1` and `autoscaling.enabled: false` with architecture-owner sign-off.

**Why local code is insufficient:** Changing a YAML key without owner attestation does not prove the backend is ready or the risk is accepted.

---

### H4 — AWS Terraform Apply / OIDC
**Owner:** DevOps / Cloud Account Owner
**Evidence required:**
1. IAM OIDC provider for GitHub (`arn:aws:iam::<account>:oidc-provider/token.actions.githubusercontent.com`) present in AWS account screenshot or CLI output.
2. IAM role `AgentFlowTerraformRole` (or equivalent) with trust policy referencing OIDC + least-privilege policy attached.
3. `AWS_TERRAFORM_ROLE_ARN` set as repository secret or environment variable (non-sensitive prefix + role name may be shown).
4. Successful `terraform plan` or `terraform apply` output (account IDs redacted) from the enabled workflow run.
5. `environments/*.tfvars` exist in secure storage (S3 / Vault) with reference in docs; commit of `.tfvars.example` updated to match real structure.

**Why local code is insufficient:** Enabling `if: true` in the workflow without a configured role causes hard failures and does not prove infrastructure exists.

---

### H5 — External Penetration Test
**Owner:** Security / Product Owner
**Evidence required:**
1. **Engagement letter or SOW** with scoped target (AgentFlow API, tenant isolation, admin endpoints) and vendor name (e.g., Bishop Fox, Cobalt, Syndis).
2. **Pentest report** (Executive Summary + Findings) dated within 12 months.
3. **Remediation tracker** showing all `High` / `Critical` findings closed or accepted with residual risk note.
4. For enterprise readiness: certificate or attestation letter stating the product was tested and no `Critical` findings remain open.

**Why local code is insufficient:** Self-assessment, SAST, or code review do not satisfy customer/regulatory expectations for independent adversarial testing.

---

### H6 — DuckDB At-Rest Encryption
**Owner:** Security / Compliance
**Evidence required:**
1. **Cryptographic verification:**
   - `PRAGMA encryption;` output from a production-class DuckDB file showing cipher enabled (e.g., `AES-256-GCM`), **or**
   - Cloud provider volume encryption attestation (EBS `Encrypted: true` + KMS key ARN) for the PVC backing store.
2. **Key management doc:** Where encryption keys are stored (KMS, HSM, sealed secret) and rotation schedule.
3. If migrating away from DuckDB for prod: reference to H3 decision record plus deletion procedure for unencrypted DuckDB files.

**Why local code is insufficient:** Setting a config flag without proof the database file is actually encrypted leaves GDPR/HIPAA exposure unverified.

---

### M4 — External Secret Manager for Helm Values
**Owner:** DevOps / Security
**Evidence required:**
1. **Infrastructure proof:** Vault instance / External Secrets Operator / AWS Secrets Manager accessible from cluster.
2. **Migration evidence:**
   - Helm values no longer contain `key_hash` literals; instead reference `existingSecret` or ESO `ExternalSecret` resource.
   - Redacted screenshot or `kubectl get secret` showing secret exists in target namespace.
3. **Rotation procedure:** Document or runbook for rotating API key hashes without Helm upgrade.

**Why local code is insufficient:** Replacing a string with a template variable does not prove the external store is operational or the secret is actually injected at runtime.

---

### M9 — Immutable Audit Log Kafka Topic
**Owner:** Platform / Kafka Owner
**Evidence required:**
1. Topic `api_usage.audit` exists in target cluster:
   ```bash
   kafka-topics.sh --describe --topic api_usage.audit
   ```
   Output showing `Retention: -1` (or equivalent infinite policy) and `cleanup.policy=delete` with no time/size limits.
2. **Write verification:** Producer log or `kcat` test showing audit events land in the topic.
3. **Read verification:** Consumer group lag check or S3/WORM sink proving events are durably retained and tamper-evident.
4. If using alternative (e.g., SIEM forwarder): architecture note + evidence of WORM storage (S3 Object Lock, GCS retention policy).

**Why local code is insufficient:** Adding a producer call in Python does not guarantee the topic exists with correct retention or that compliance officers can retrieve a year-old record.

---

### L7 — Signed Container Images (cosign)
**Owner:** DevOps / Security
**Evidence required:**
1. **Key ceremony record:**
   - Cosign key pair generated (`cosign generate-key-pair`) or Sigstore keyless flow configured with OIDC.
   - Public key published to repository (`cosign.pub`) or in docs with fingerprint.
2. **CI evidence:** `publish-pypi.yml` (or dedicated image workflow) contains `cosign sign` step and the run log shows `Successfully signed index.docker.io/...`.
3. **Verifiable by anyone:**
   ```bash
   cosign verify --key cosign.pub <image>:<tag>
   ```
   Output captured in runbook or CI artifact.
4. **Policy enforcement (optional but preferred):** Kyverno / OPA Gatekeeper policy requiring `cosign verify` before pod admission in target cluster.

**Why local code is insufficient:** A CI step that signs with a missing or ephemeral key produces no trust material; consumers cannot verify the signature, so SLSA / supply-chain gate remains open.

---

## 3. Local Fixes (No External Evidence Needed)

These items can be closed purely by repository changes and CI passing:

| ID | Verification Command / Check |
|----|------------------------------|
| **M1** | `ruff check src/` passes with `S608` removed from global ignore and only per-file ignores in sqlglot-validated modules. |
| **M2** | `bandit -r src/` passes with `B608` removed from global skips and only targeted skips. |
| **M3** | `mypy src/serving/ src/quality/` passes with `disallow_untyped_defs = true` in override. |
| **M7** | Workflow file exists; dry-run `helm rollback` command validated in CI or local act runner. |
| **M8** | `pytest --cov=src/auth --cov=src/query_engine --cov=src/rate_limiter` shows ≥ 75 % and CI gate updated. |
| **L6** | `syft <image> -o spdx-json` or `trivy image --format spdx-json` produces valid SBOM in CI artifact. |

---

## 4. Gate Closure Protocol

```
FOR each external gate:
  1. Owner assigns to themselves in tracking system.
  2. Owner provides evidence artifact (screenshot, CLI output, doc, SOW).
  3. Evidence is reviewed and stored in docs/compliance/YYYY-MM-DD/.
  4. Ticket status moved to "Closed — Evidence Attached".
  5. IF evidence is missing or insufficient → status stays "Open — Awaiting Owner Evidence".
```

**Hard rule:** A Git commit, PR merge, or local test success does **not** advance an external gate to `complete`. Only owner-attested, externally verifiable evidence does.

---

*Generated: 2026-05-05*
*Applies to: AgentFlow audit items H3-H6, M4, M9, L7*
