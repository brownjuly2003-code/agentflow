# Next Session Free Local Audit Gates Plan

## Goal

Close every audit item that can be closed with local code, free/open-source tooling, and repository evidence only, while keeping the product described as commercial-like or production-shaped, not as a commercial product.

## Starting State

- Branch: `main`
- Baseline HEAD at handoff: `5c96f74`
- Tracked files at handoff: `701`
- Current local remediation already closed: first Kimi five-point package, M1/M2, L6, M7, M3 scoped mypy, and M8 scoped validators coverage.
- Remaining scope from `res/codex/codex_kimi_audit_synthesis_05_05_26.md`: H3, H4, H5, H6, M4, M9, L7.
- Hard boundary: do not use paid services, do not run deploys, do not run Terraform apply, do not publish packages/images, do not claim enterprise/commercial readiness, and do not mark external gates complete without owner-provided evidence.

## Tasks

- [ ] Measure the real baseline before edits.
  Verify: record `git rev-parse --short HEAD`, `git status --short --branch`, and `git ls-files` count in the first progress update.

- [ ] Close H3/M4 local Helm hardening with tests first.
  Verify: add failing Helm policy/render tests, then implement DuckDB multi-replica guardrails plus `existingSecret`/external-secret-friendly API-key values; `helm template` and the new tests pass; default Helm values no longer contain production-shaped API-key verifier hashes.

- [ ] Close H6 local encryption readiness without compliance overclaim.
  Verify: add failing unit tests first, then implement optional DuckDB encryption bootstrap through operator-supplied env/secret and document the DuckDB/NIST/compliance caveat; tests prove the encrypted path is used only when configured and the default remains backward-compatible.

- [ ] Close M9 local immutable-audit readiness with free alternatives.
  Verify: add failing tests first, then implement an append-only audit publisher abstraction using OSS/local-safe targets only, such as Kafka/Redpanda-compatible topic config or hash-chained file/S3-compatible Object Lock documentation; tests prove mutation-prone DuckDB analytics are not the only audit path.

- [ ] Close L7 local signing setup with free GitHub/Sigstore tooling.
  Verify: add workflow policy tests first, then add cosign keyless/GitHub artifact attestation skeleton for container images by digest; workflow YAML parses and tests assert that unsigned release-image paths are not accepted. Full gate stays evidence-pending until a real CI run signs a published digest.

- [ ] Improve H4 as free local readiness only.
  Verify: add Terraform/OIDC preflight docs or workflow checks that validate required variables and plan readiness without `apply`; keep H4 open unless a real AWS owner supplies role, tfvars, and successful assume-role/apply evidence.

- [ ] Improve H5 with no-cost security evidence only.
  Verify: add or wire free local/security scan evidence templates using existing scanners where practical; keep H5 open because ZAP/Nuclei/Semgrep/CodeQL/Trivy/internal audits do not replace an external penetration-test attestation.

- [ ] Update audit status documents with precise wording.
  Verify: `res/codex/*`, `AGENT_STATE.md`, and any touched docs distinguish `closed locally`, `ready for evidence`, and `blocked on external evidence`; no text says the product is commercial, enterprise-ready, GDPR/HIPAA-ready, or externally attested unless evidence exists.

- [ ] Run verification last.
  Verify: run relevant targeted tests first, then `python -m ruff check src/ tests/`, `python -m ruff format --check src/ tests/`, workflow/Helm YAML checks, full `python -m pytest -p no:schemathesis`, `cd sdk-ts; npm run test:unit`, `cd sdk-ts; npm run typecheck`, and `git diff --check`.

## Done When

- [ ] H3/M4/H6/M9/L7 have the maximum free local remediation merged or are explicitly documented as evidence-pending.
- [ ] H4 and H5 are improved only as free readiness/evidence-intake work and remain open without external owner evidence.
- [ ] No paid service, deploy, publish, Terraform apply, external scan, credential use, or commercial-readiness claim was introduced.
- [ ] All changed files are committed with explicit pathspecs; push only if the user explicitly asks.
