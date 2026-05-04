# Backlog

## 0. Reconcile The Autopilot Handoff State

Status: Done.

Allowed files/directories:
- `.gitignore`
- `AGENT_STATE.md`
- `AUTOPILOT.md`
- `BACKLOG.md`
- `scripts/autopilot.ps1`
- `scripts/install-autopilot-task.ps1`
- `.autopilot/`

Acceptance criteria:
- Decide whether the autopilot handoff files are project artifacts or local-only runtime state.
- If project artifacts, add only the intended files with explicit pathspecs and keep `.autopilot/` ignored as local runtime state.
- If local-only, move or remove them deliberately so `git status --short` no longer blocks guarded runs.
- Remove `.autopilot/BLOCKED.md` only after the dirty-worktree cause is resolved.

Required verification:
- `git status --short`
- `git diff --check`
- `powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun`

Forbidden scope:
- No source code changes.
- No deploy, publish, secret, external account, or scheduler install commands.

## 1. Document The Local Verification Matrix

Status: Done.

Allowed files/directories:
- `docs/operations/`
- `AGENT_STATE.md`
- `BACKLOG.md`

Acceptance criteria:
- Document which local gates are safe by default and which require Docker, cloud credentials, or external services.
- Include exact commands for unit, integration, TypeScript SDK, benchmark, and security checks.
- Keep deploy, publish, and Terraform apply flows out of the default autopilot path.

Required verification:
- `git diff --check`

Forbidden scope:
- No source code changes.
- No deploy, publish, secret, or external account commands.

## 2. Add Unit Coverage For Search Index Token Edge Cases

Status: Done.

Allowed files/directories:
- `tests/unit/`
- `src/serving/semantic_layer/search_index.py`
- `AGENT_STATE.md`
- `BACKLOG.md`

Acceptance criteria:
- Add a failing unit test before any behavior change.
- Cover at least one edge case around token normalization or matching.
- Keep public query behavior backward compatible unless the test documents an existing bug.

Required verification:
- `python -m pytest tests/unit -p no:schemathesis`
- `python -m ruff check src/ tests/`
- `python -m ruff format --check src/ tests/`

Forbidden scope:
- No API route changes.
- No database, Docker, deploy, or benchmark changes.

## 3. Tighten TypeScript SDK Example Verification

Status: Done.

Allowed files/directories:
- `sdk-ts/`
- `tests/client.test.ts`
- `AGENT_STATE.md`
- `BACKLOG.md`

Acceptance criteria:
- Improve or add a small SDK example/test that runs locally without network access.
- Preserve the published package surface.
- Do not touch npm publishing workflow or package ownership metadata.

Required verification:
- `cd sdk-ts; npm run typecheck`
- `cd sdk-ts; npm run test:unit`
- `cd sdk-ts; npm run build`

Forbidden scope:
- No `npm publish`, `npm login`, `npm token`, or package ownership changes.
- No root backend source changes unless a later task explicitly allows them.

## 4. Document Guarded Autopilot Allowed-Paths Bootstrap

Status: Done.

Allowed files/directories:
- `docs/operations/`
- `AGENT_STATE.md`
- `BACKLOG.md`

Acceptance criteria:
- Add a concise local-operations note for creating `.autopilot/allowed-paths.txt` for one bounded backlog item.
- Explain that `.autopilot/` is ignored local runtime state and should not be committed.
- Include exact preflight commands for `git status`, `git diff --check`, and `scripts/autopilot.ps1 -DryRun`.
- Keep deploy, publish, Terraform, secret, scheduler install, and external account operations out of the flow.

Required verification:
- `git diff --check`
- `powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun`

Forbidden scope:
- No source code changes.
- No test, SDK package, deployment, Terraform, secret, scheduler install, or external account changes.

## 5. Document Guarded Autopilot Pause And Blocked Recovery

Status: Done.

Allowed files/directories:
- `docs/operations/`
- `AGENT_STATE.md`
- `BACKLOG.md`

Acceptance criteria:
- Add a concise local-operations note for handling `.autopilot/PAUSE` and `.autopilot/BLOCKED.md`.
- Include exact commands to inspect state, resume after PAUSE, and remove BLOCKED only after the blocker is resolved.
- Explain that `.autopilot/` is ignored runtime state and should not be committed.
- Keep deploy, publish, Terraform, secret, scheduler install, and external account operations out of the flow.

Required verification:
- `git diff --check`
- `powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun`

Forbidden scope:
- No source code changes.
- No test, SDK package, deployment, Terraform, secret, scheduler install, or external account changes.

## 6. Document Guarded Autopilot Explicit Commit Gate

Status: Done.

Allowed files/directories:
- `docs/operations/`
- `AGENT_STATE.md`
- `BACKLOG.md`

Acceptance criteria:
- Add a concise local-operations note for when `scripts/autopilot.ps1 -Commit` is allowed.
- Document that commits must use explicit pathspecs through the runner and must never push.
- Include the pre-commit gates from `AUTOPILOT.md` and `docs/operations/local-verification-matrix.md`.
- Keep deploy, publish, Terraform, secret, scheduler install, and external account operations out of the flow.

Required verification:
- `git diff --check`
- `powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun`

Forbidden scope:
- No source code changes.
- No actual commit, push, test, SDK package, deployment, Terraform, secret, scheduler install, or external account changes.

## 7. Document Guarded Autopilot Dirty-Worktree Preflight

Status: Done.

Allowed files/directories:
- `docs/operations/`
- `AGENT_STATE.md`
- `BACKLOG.md`

Acceptance criteria:
- Add a concise local-operations note for handling a dirty worktree before a guarded non-dry autopilot run.
- Include exact commands to inspect tracked and untracked changes without deleting or reverting user work.
- Explain when to stop because another session appears to be editing shared files.
- Keep deploy, publish, Terraform, secret, scheduler install, and external account operations out of the flow.

Required verification:
- `git diff --check`
- `powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun`

Forbidden scope:
- No source code changes.
- No cleanup, revert, commit, push, test, SDK package, deployment, Terraform, secret, scheduler install, or external account changes.

## 8. Document Guarded Autopilot Log And Lock Inspection

Status: Done.

Allowed files/directories:
- `docs/operations/`
- `AGENT_STATE.md`
- `BACKLOG.md`

Acceptance criteria:
- Add a concise local-operations note for inspecting `.autopilot/logs/` and `.autopilot/autopilot.lock`.
- Include exact read-only commands to view recent logs and determine whether a lock appears stale.
- Explain that lock removal is a manual operator decision and must not be automated by routine autopilot documentation tasks.
- Keep deploy, publish, Terraform, secret, scheduler install, and external account operations out of the flow.

Required verification:
- `git diff --check`
- `powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun`

Forbidden scope:
- No source code changes.
- No lock deletion, cleanup, revert, commit, push, test, SDK package, deployment, Terraform, secret, scheduler install, or external account changes.

## 9. Document Guarded Autopilot Dry-Run Output Triage

Status: Done.

Allowed files/directories:
- `docs/operations/`
- `AGENT_STATE.md`
- `BACKLOG.md`

Acceptance criteria:
- Add a concise local-operations note for interpreting `scripts/autopilot.ps1 -DryRun` output before a guarded non-dry run.
- Include exact read-only follow-up commands for PAUSE, BLOCKED, missing `allowed-paths.txt`, dirty worktree, and missing local command reports.
- Explain that dry-run output is advisory preflight evidence and does not authorize deploy, publish, Terraform, secret, scheduler, external account, cleanup, revert, commit, or push operations.
- Keep deploy, publish, Terraform, secret, scheduler install, and external account operations out of the flow.

Required verification:
- `git diff --check`
- `powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun`

Forbidden scope:
- No source code changes.
- No cleanup, revert, commit, push, test, SDK package, deployment, Terraform, secret, scheduler install, or external account changes.

## 10. Document Guarded Autopilot Runtime Artifact Inventory

Status: Done.

Allowed files/directories:
- `docs/operations/`
- `AGENT_STATE.md`
- `BACKLOG.md`

Acceptance criteria:
- Add a concise local-operations note that inventories the `.autopilot/` runtime artifacts used by the guarded runner.
- Distinguish local-only runtime files from project artifacts and explain which files are operator inputs versus generated evidence.
- Include exact read-only commands to inspect artifact presence and timestamps without deleting, regenerating, committing, or publishing anything.
- Keep deploy, publish, Terraform, secret, scheduler install, and external account operations out of the flow.

Required verification:
- `git diff --check`
- `powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun`

Forbidden scope:
- No source code changes.
- No cleanup, revert, commit, push, test, SDK package, deployment, Terraform, secret, scheduler install, or external account changes.

## 11. Document Guarded Autopilot Verification Evidence Capture

Status: Done.

Allowed files/directories:
- `docs/operations/`
- `AGENT_STATE.md`
- `BACKLOG.md`

Acceptance criteria:
- Add a concise local-operations note for capturing verification evidence from guarded autopilot runs.
- Distinguish required gate output, advisory dry-run output, generated logs, and state updates.
- Include exact local commands for collecting evidence without deleting, regenerating, committing, pushing, publishing, deploying, or reading secrets.
- Keep deploy, publish, Terraform, secret, scheduler install, external account, paid API, cleanup, revert, and product-code work out of scope.

Required verification:
- `git diff --check`
- `powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun`

Forbidden scope:
- No source code changes.
- No cleanup, revert, commit, push, test, SDK package, deployment, Terraform, secret, scheduler install, external account, or paid service changes.

## 12. Document Guarded Autopilot Handoff Refresh Checklist

Status: Done.

Allowed files/directories:
- `docs/operations/`
- `AGENT_STATE.md`
- `BACKLOG.md`

Acceptance criteria:
- Add a concise local-operations note for refreshing guarded autopilot handoff state after a completed run.
- Include exact local commands to compare `.autopilot/NEXT_TASK.md`, `.autopilot/allowed-paths.txt`, current git status, and the next backlog item without deleting, regenerating, committing, pushing, publishing, deploying, or reading secrets.
- Explain what belongs in project state files versus ignored `.autopilot/` runtime files.
- Keep deploy, publish, Terraform, secret, scheduler install, external account, paid API, cleanup, revert, and product-code work out of scope.

Required verification:
- `git diff --check`
- `powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun`

Forbidden scope:
- No source code changes.
- No cleanup, revert, commit, push, test, SDK package, deployment, Terraform, secret, scheduler install, external account, or paid service changes.

## 13. Document Guarded Autopilot Stop Conditions

Status: Done.

Allowed files/directories:
- `docs/operations/`
- `AGENT_STATE.md`
- `BACKLOG.md`

Acceptance criteria:
- Add a concise local-operations note for deciding when a guarded autopilot run must stop before edits, state updates, or non-dry execution.
- Include exact read-only commands to detect PAUSE, BLOCKED, dirty worktree state, allowed-path mismatches, and unexpected changes without deleting, regenerating, committing, pushing, publishing, deploying, or reading secrets.
- Explain how to report a blocker without cleanup, revert, product-code work, live accounts, paid APIs, Terraform, scheduler install, deploy, or publish operations.
- Keep deploy, publish, Terraform, secret, scheduler install, external account, paid API, cleanup, revert, and product-code work out of scope.

Required verification:
- `git diff --check`
- `powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun`

Forbidden scope:
- No source code changes.
- No cleanup, revert, commit, push, test, SDK package, deployment, Terraform, secret, scheduler install, external account, or paid service changes.

## 14. Document Guarded Autopilot Self-Commit Loop

Status: Done.

Allowed files/directories:
- `docs/operations/`
- `AGENT_STATE.md`
- `BACKLOG.md`

Acceptance criteria:
- Add a concise local-operations note for running `scripts/autopilot.ps1 -Commit` as the default guarded backlog loop.
- Explain the clean-worktree precondition, explicit `commit allowed: yes` gate, allowed-path validation, and why `git push` remains outside the loop.
- Include exact local commands for dry-run, non-dry commit mode, status inspection, and post-run verification without deploy, publish, Terraform, scheduler install, external account, paid API, cleanup, revert, or secret operations.
- Keep product-code work out of scope.

Required verification:
- `git diff --check`
- `powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun`

Forbidden scope:
- No source code changes.
- No cleanup, revert, push, test, SDK package, deployment, Terraform, secret, scheduler install, external account, paid service, or production data changes.

## 15. Document Guarded Autopilot Planner Fallback Handling

Status: Done.

Allowed files/directories:
- `docs/operations/`
- `AGENT_STATE.md`
- `BACKLOG.md`

Acceptance criteria:
- Add a concise local-operations note for interpreting planner fallback from `pi` to `codex`.
- Document that a `pi` authentication failure is a local tooling issue, not permission to inspect or print API keys.
- Include exact read-only commands to inspect `.autopilot/logs/`, `NEXT_TASK.md`, `allowed-paths.txt`, and `BLOCKED.md` after a fallback or planner failure.
- Allow local `scripts/autopilot.ps1 -Commit` self-commit only through the explicit `commit allowed: yes` gate; keep deploy, publish, Terraform, secret, scheduler install, external account, paid API, cleanup, revert, push, and product-code work out of scope.

Required verification:
- `git diff --check`
- `powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun`

Forbidden scope:
- No source code changes.
- No cleanup, revert, push, test, SDK package, deployment, Terraform, secret, scheduler install, external account, paid service, or production data changes.

## 16. Document Guarded Autopilot Push Boundary

Status: Done.

Allowed files/directories:
- `docs/operations/`
- `AGENT_STATE.md`
- `BACKLOG.md`

Acceptance criteria:
- Add a concise local-operations note that separates local autopilot commits from any remote push operation.
- Include exact read-only commands to inspect ahead/behind state, recent local commits, and changed files without pushing, force-pushing, fetching secrets, deploying, publishing, or changing remotes.
- Explain when to stop and ask for an explicit operator decision before `git push`.
- Keep deploy, publish, Terraform, secret, scheduler install, external account, paid API, cleanup, revert, and product-code work out of scope.

Required verification:
- `git diff --check`
- `powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun`

Forbidden scope:
- No source code changes.
- No cleanup, revert, push, test, SDK package, deployment, Terraform, secret, scheduler install, external account, paid service, or production data changes.

## 17. Document Guarded Autopilot Scheduler Opt-In Boundary

Status: Done.

Allowed files/directories:
- `docs/operations/`
- `AGENT_STATE.md`
- `BACKLOG.md`

Acceptance criteria:
- Add a concise local-operations note explaining that continuous unattended autopilot requires an explicit scheduler opt-in.
- Include exact read-only commands to inspect whether the scheduled task exists and how to preview `scripts/install-autopilot-task.ps1` without installing it.
- Explain that scheduler install, credentials, secrets, external accounts, deploy, publish, Terraform, cleanup, revert, push, and product-code work require a separate explicit operator task.
- Allow local `scripts/autopilot.ps1 -Commit` self-commit only through the explicit `commit allowed: yes` gate.
- Keep scheduler installation itself out of scope.

Required verification:
- `git diff --check`
- `powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun`

Forbidden scope:
- No source code changes.
- No cleanup, revert, push, test, SDK package, deployment, Terraform, secret, scheduler install, external account, paid service, or production data changes.

## 18. Prepare AWS OIDC Terraform Apply Readiness Handoff

Status: Ready.

Allowed files/directories:
- `docs/operations/`
- `docs/release-readiness.md`
- `AGENT_STATE.md`
- `BACKLOG.md`

Acceptance criteria:
- Summarize the current AWS OIDC Terraform apply blockers from `docs/release-readiness.md` and `docs/codex-tasks/2026-05-01/T32-post-release-external-gates.md`: `AWS_REGION` exists, `AWS_TERRAFORM_ROLE_ARN` is missing, terraform apply jobs remain disabled, real environment tfvars are absent, and this workstation has no AWS credentials.
- Create or update a bounded operator handoff that lists the external inputs required before a real Terraform apply can be enabled.
- If the external AWS role ARN, tfvars, and operator approval are still absent, mark this item blocked in `BACKLOG.md` and `AGENT_STATE.md` instead of enabling apply.
- Keep the handoff limited to documentation and backlog/state updates.

Required verification:
- `git status --short --branch`
- `git diff --check`
- `powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun`

Forbidden scope:
- No Terraform init, plan, apply, workflow enablement, AWS CLI, AWS account, secret, credential, deploy, publish, scheduler install, push, paid service, production data, or product-code changes.

## 19. Record Production CDC Source Onboarding Decision Handoff

Status: Pending.

Allowed files/directories:
- `docs/operations/cdc-production-onboarding.md`
- `docs/release-readiness.md`
- `AGENT_STATE.md`
- `BACKLOG.md`

Acceptance criteria:
- Check the production CDC onboarding decision record for source owner, secret owner, table scope, private network path, monitoring owner, and rollback owner.
- If those external decisions are not provided in the task prompt, record the missing inputs and mark this item blocked in `BACKLOG.md` and `AGENT_STATE.md`.
- If the decisions are provided, capture them in the existing onboarding handoff format without enabling production CDC.
- Preserve the current local/demo and Kubernetes-shaped CDC state as documentation only.

Required verification:
- `git status --short --branch`
- `git diff --check`
- `powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun`

Forbidden scope:
- No production CDC enablement, connector registration, network changes, secret creation, credential access, external account work, deploy, publish, Terraform, scheduler install, push, paid service, production data, or product-code changes.

## 20. Prepare Phase 1 PMF Outreach And Pricing Evidence Handoff

Status: Pending.

Allowed files/directories:
- `docs/customer-discovery-tracker.md`
- `docs/pricing-validation-plan.md`
- `docs/customer-discovery-questions.md`
- `docs/release-readiness.md`
- `AGENT_STATE.md`
- `BACKLOG.md`

Acceptance criteria:
- Summarize the open Phase 1 PMF evidence gaps: actual outreach sends, replies, scheduled calls, completed interviews, PMF scoring, pricing/WTP evidence, and first paying-customer signals.
- If no founder-provided outreach or interview evidence is present in the task prompt, mark this item blocked on external founder/customer input rather than inventing evidence.
- If evidence is provided, append it to the existing tracker/pricing evidence format and update the next review step.
- Keep the handoff focused on evidence capture and state updates.

Required verification:
- `git status --short --branch`
- `git diff --check`
- `powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun`

Forbidden scope:
- No customer outreach, email sending, scraping, CRM changes, external account access, paid API usage, payment collection, deploy, publish, Terraform, scheduler install, push, production data, or product-code changes.

## 21. Define Public Benchmark Production-Hardware Plan

Status: Pending.

Allowed files/directories:
- `docs/perf/`
- `docs/operations/`
- `docs/release-readiness.md`
- `AGENT_STATE.md`
- `BACKLOG.md`

Acceptance criteria:
- Define the public benchmark plan for production hardware, including the target `c8g.4xlarge+` class, prerequisites, benchmark commands, result artifacts, and publication evidence expected after an operator-run benchmark.
- State that the checked-in single-node baseline remains the only release evidence until production hardware results are provided.
- If no approved production-hardware access, budget, and operator-run evidence are provided, mark this item blocked in `BACKLOG.md` and `AGENT_STATE.md`.
- Keep the plan reproducible from local documentation without provisioning infrastructure.

Required verification:
- `git status --short --branch`
- `git diff --check`
- `powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun`

Forbidden scope:
- No cloud provisioning, paid hardware use, live load testing, benchmark publication, external account access, deploy, publish, Terraform, scheduler install, push, production data, or product-code changes.

## 22. Prepare External Pen-Test Attestation Handoff

Status: Pending.

Allowed files/directories:
- `docs/security-audit.md`
- `docs/operations/`
- `docs/release-readiness.md`
- `AGENT_STATE.md`
- `BACKLOG.md`

Acceptance criteria:
- Summarize the external pen-test attestation gap from `docs/release-readiness.md` and `docs/audit-history.md`.
- Create or update a handoff checklist for tester identity, test scope, report date, severity summary, remediation mapping, retest status, and attestation artifact location.
- If no external pen-test report or attestation is provided, mark this item blocked in `BACKLOG.md` and `AGENT_STATE.md` rather than claiming completion.
- Preserve the existing internal security audit evidence as distinct from third-party attestation.

Required verification:
- `git status --short --branch`
- `git diff --check`
- `powershell -ExecutionPolicy Bypass -File scripts/autopilot.ps1 -DryRun`

Forbidden scope:
- No external scanning, penetration testing, vulnerability exploitation, credential access, paid service use, external account work, deploy, publish, Terraform, scheduler install, push, production data, or product-code changes.
