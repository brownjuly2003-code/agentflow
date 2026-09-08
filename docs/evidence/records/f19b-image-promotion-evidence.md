# F-19b Image Promotion Evidence

## Goal

Turn the digest built, signed, and attested by the protected container workflow into a machine-readable Helm promotion packet without rebuilding the image or claiming a staging rollout.

## Tasks

- [x] Add failing tests for digest validation, exact Helm rendering, and workflow artifact wiring. → Verify: old workflow has no promotion evidence.
- [x] Generate values, deployment manifest, and provenance metadata from `steps.build.outputs.digest`. → Verify: the manifest contains only the built `repository@digest` identity.
- [x] Upload the packet from the build-owning job with pinned Helm tooling. → Verify: the external-digest signing job cannot emit build/promotion evidence.
- [x] Document the remaining staging-consumption boundary and run local plus Mac gates. → Verify: focused tests and static policy checks pass.

## Done When

- [x] One protected build produces one signed/attested digest and a checksumed Helm packet; no push, dispatch, deployment, or production claim occurs locally.

## Next-session quick start

### Rebuild repository truth first

1. Run `git status --short --branch`, `git log -1 --oneline --decorate`, and
   `git rev-list --left-right --count origin/main...HEAD` from
   `D:\DE_project`. Trust those results over this snapshot if they differ.
2. Confirm that the F-19b implementation commit `ce10670` is still in the
   current branch history. F-19a is `fa50b76` with its plan/handoff in
   `814e81d`.
3. Read the first block of `AGENT_STATE.md` and section 77 of
   `docs/SESSION_HANDOFF.md`. Both are intentionally ignored local handoff
   files; do not force-add them.

F-19a and F-19b are complete, but F-19 is not. `production.status` remains
`candidate`. No local commit described here was pushed, dispatched, signed,
attested, deployed, or published.

### Focused regression gate

Run this without WSL or Docker on Windows, using an environment with the
project dependencies and Helm 3.16.3. At this handoff the Windows `.venv`
reports Python 3.13.7; the independent Mac gate used Python 3.11:

```powershell
python -m pytest tests/unit/test_image_promotion_evidence.py tests/unit/test_container_attestation_workflow.py -q
python -m ruff check scripts/write_image_promotion_evidence.py tests/unit/test_image_promotion_evidence.py tests/unit/test_container_attestation_workflow.py
python -m ruff format --check scripts/write_image_promotion_evidence.py tests/unit/test_image_promotion_evidence.py tests/unit/test_container_attestation_workflow.py
python -m mypy scripts/write_image_promotion_evidence.py
python scripts/check_docs_links.py
python scripts/validate_project_claims.py
git diff --check
```

The focused pytest baseline at `ce10670` is 15 passing tests on Windows and
independently on Mac.

### Runtime and workspace boundaries

- Do not start WSL, Docker, kind, or another container runtime on Windows.
  Any Docker/kind verification belongs on the Mac reached through
  `deproject-mac`.
- Treat `/Users/julia/agentflow-docker-check` as read-only: it has an unrelated
  HEAD and WIP. Use a uniquely named isolated `/tmp` checkout for the exact
  commit under test.
- Preserve all existing untracked WIP: `.myflow/`, `AGENTS.md`, `New_steps/`,
  `audit-sol-2026-08-23-plan.md`, `checkpoint-restore-replay-gate.md`,
  `corrected-rollback-pair-local-design.md`,
  `docs/operations/cycle-guard.md`, `fresh-zero-failure-job-lifetime.md`,
  `golden-4h-soak-rollback-gate.md`,
  `mac-test-failures-deep-analysis-2026-08-18.md`, `plan_sol_23_07_26`,
  `production-gates-reverification-2026-08-01.md`, and
  `tests/unit/test_golden_4h_soak_verify.py`.
- A protected stale directory may still exist at
  `%TEMP%\agentflow-f19a-294d1bc025fb411e9f2cb73023e6d958`. Do not retry its
  cleanup without a new, narrow reason and an exact resolved-path check.

### Exact F-19c boundary

The next atomic slice is the staging consumer, not another image producer.
The current `.github/workflows/staging-deploy.yml` calls
`scripts/k8s_staging_up.sh`; that script still runs `docker build` and
`kind load`, so it does not yet satisfy build-once promotion.

F-19c must:

1. Select one explicit, successful `container-attestation` build run and
   download `agentflow-image-promotion-<source-sha>` from that run.
2. Before any cluster mutation, validate `promotion.json` schema version,
   selected run ID, source SHA, allowed image repository, lowercase digest,
   exact `repository@digest` subject, referenced filenames, and the rendered
   manifest SHA-256.
3. Verify the registry cosign signature and GitHub build provenance for that
   same subject and digest.
4. Deploy the packet's digest through Helm without rebuilding or loading a
   locally built API image, then retain the existing staging smoke/E2E gate.
5. Record staging evidence only. Do not claim production acceptance or close
   F-19 until the remaining release boundary is implemented and verified.

Run any F-19c Docker/kind acceptance gate only in an isolated Mac checkout.
