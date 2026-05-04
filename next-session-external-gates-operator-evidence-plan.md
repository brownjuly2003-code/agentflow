# Next Session External Gates Operator Evidence Plan

## Goal

Advance backlog tasks 18-22 only when real owner-provided evidence is available, and keep every gate blocked when evidence is missing or unsafe to record.

## Starting State

- Branch: `main`
- Baseline HEAD: `001694b`
- Tracked files at handoff: `672`
- Current manual work already added access-triage notes and next operator packets for tasks 18-22.
- Do not use autopilot. Do not push unless explicitly asked.

## Tasks

- [ ] Inspect the working tree before edits.
  Verify: `git status --short --untracked-files=no` shows only expected files from the prior manual handoff or is clean.
- [ ] For task 18, review the AWS OIDC operator packet.
  Verify: only close or update the gate if a role ARN, real tfvars ownership, workflow-enable approval, first apply evidence, and redacted OIDC proof are supplied.
- [ ] For task 19, review the production CDC operator packet.
  Verify: only close or update the gate if source owner, secret owner, table allowlist, private network path, Kubernetes Secret owner, monitoring owner, rollback owner, and first-run evidence are supplied.
- [ ] For task 20, review PMF and pricing evidence.
  Verify: only count real outreach/interviews/pricing signals when redacted CRM, email, calendar, notes, LOI, invoice, procurement, or paid-pilot artifacts exist.
- [ ] For task 21, review production-hardware benchmark evidence.
  Verify: only update release readiness if approved hardware, budget, command transcript, JSON/report artifacts, fixture-safety confirmation, host metadata, and publication approval are supplied.
- [ ] For task 22, review external pen-test attestation.
  Verify: only update release readiness if tester identity, scope, test window, severity summary, report/attestation, remediation mapping, retest status, and attestation owner are supplied.
- [ ] Keep blocked gates blocked when evidence is absent.
  Verify: `BACKLOG.md`, `AGENT_STATE.md`, and the relevant handoff doc state the missing fields without inventing completion.
- [ ] Run verification last.
  Verify: `git diff --check`, `python -m pytest -p no:schemathesis --basetemp .tmp\<task-basetemp> -o cache_dir=.tmp\<task-cache>`, `cd sdk-ts; npm run test:unit`, and `cd sdk-ts; npm run typecheck` pass.

## Done When

- [ ] Every gate touched has either an accepted evidence record or a precise blocker.
- [ ] No secrets, tokens, credentials, raw customer data, private hostnames, account IDs, or recovery codes are written to the repo.
- [ ] No Terraform apply, production CDC change, outreach send, paid benchmark, external scan, deploy, push, or package publish runs without explicit operator instruction.
