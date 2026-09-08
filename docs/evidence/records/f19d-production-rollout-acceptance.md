# F-19d Production Rollout and Acceptance

## Goal

Promote the exact staging-accepted OCI digest to an owner-supplied production
Kubernetes target without rebuilding it, with identity-bound rollback and
production-scoped evidence. This plan does not authorize a deployment or a
production-acceptance claim.

## Current baseline

- Source `51be8f2197d9148e6d57cc8340c303afc7189ad8`, build run
  `32989412486`, staging run `33005146264`, and image
  `ghcr.io/brownjuly2003-code/agentflow-api@sha256:58dfd77af54502e94b5dc931ecf6b31c9b9872df7c3066057a5b57905e563f5c`
  are linked by verified staging artifact `9620326516`.
- The repository has 21 workflows, but no production deployment workflow.
  Terraform apply is deliberately disabled and models only a streaming
  infrastructure reference; real `prod.tfvars` and a complete runtime target
  are absent.
- GitHub Environment `production` has a required reviewer, with
  `prevent_self_review=false`; it is an approval gate, not a four-eyes claim.
- `production.status` remains `candidate`. Full acceptance still requires the
  fresh four-hour soak plus rollback-after-traffic gate and independent
  penetration-test remediation/retest evidence.

Current implementation state: local evidence verifier complete; target-dependent
workflow/deploy remains **`BLOCKED_EXTERNAL_PRODUCTION_TARGET_CONTRACT`**.

## Tasks

- [ ] Obtain the owner packet: cluster/namespace/release identities, bounded
  credential delivery, environment-values fingerprint, existing Secret names,
  NetworkPolicy controller, ingress/TLS/CORS/trusted-proxy values, production
  smoke URL, maintenance window, monitoring owner, and exact previous
  release/digest rollback target. → Verify: a read-only preflight resolves each
  identity without printing or committing credentials, kubeconfig, or values.
- [x] Add an offline production promotion verifier for one already downloaded
  staging artifact plus its GitHub API metadata. Strictly validate the three
  files, staging JSON and hashes, expected run/source/artifact/image identity,
  build linkage, cosign and GitHub verification-result semantics, scope, and
  expiry. → Verify: `32/32` focused tests and the retained real artifact
  `9620326516` pass; tampering and substitution cases fail closed.
- [ ] Add `.github/workflows/production-deploy.yml` with inputs
  `staging_run_id`, `source_sha`, and exact confirmation `RELEASE`; use only the
  protected `production` Environment and the owner-approved target/values
  delivery contract. Validate the successful staging run, select and download
  exactly one artifact, call the offline verifier, then freshly run cosign and
  GitHub provenance verification before cluster access. → Verify: static
  workflow tests prove this ordering and that no `docker build`, image push,
  signing, or `kind load` path exists.
- [ ] Render `helm/agentflow/values-production.yaml` plus the owner-supplied
  environment values and the verified digest before mutation, then capture the
  live pre-deploy Helm revision and exact deployed digest. → Verify: Helm
  lint/template passes the production contract and fails closed on any empty,
  dev-shaped, tag-based, or identity-mismatched input.
- [ ] Deploy once, verify the exact live `repository@digest`, run the approved
  production smoke/E2E subset, and always collect diagnostics. On failure,
  restore only the captured previous revision/digest and verify the restoration;
  never guess a historical revision. → Verify: success evidence records target,
  before/after identities, gates, and cleanup; failure evidence records the
  bounded rollback result and makes no acceptance claim.
- [ ] Upload production evidence only after rollout gates pass, then update
  release readiness and machine claims only when the separate soak/rollback and
  external-pentest acceptance gates are also satisfied. → Verify: docs links,
  claims validation, exact release-SHA required checks, and scoped diff gates
  pass before any status elevation.

## Done When

- [ ] One explicitly authorized production run deploys the exact staging-
  accepted digest without rebuilding, preserves the captured rollback identity,
  proves restoration if rollback is invoked, emits bounded production evidence,
  and leaves `production.status` unchanged unless every independent acceptance
  gate is evidenced.

## Notes

If staging artifact `9620326516` expires or any identity changes, fail closed
and request a newly authorized plan; do not substitute another run or
redispatch staging merely to refresh evidence. Local Docker/kind verification,
if later required, belongs on `deproject-mac`, never Windows. Push, production
dispatch, credential changes, and status elevation remain separate explicit
owner gates. Do not procure, simulate, or self-attest the required independent
penetration test from this plan.
