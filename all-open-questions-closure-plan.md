# All Open Questions Closure Plan

Last updated: 2026-05-31
Status: active plan

## Goal

Close every locally closeable project question with verified commits, and keep
every external/admin/Docker-gated question as an explicit evidence gate instead
of treating it as done.

## Non-Secret Mac Execution Rule

- This Windows workstation is a no-Docker host.
- Docker-heavy validation must run on Mac/CI, not on this Windows machine.
- The current Mac Docker host routing is not secret: `julia@192.168.1.133`,
  Lima Docker, checkout `/Users/julia/agentflow-docker-check`, Python venv
  `/Users/julia/agentflow-docker-check/.venv-mac-docker`.
- Credentials, recovery codes, tokens, account secrets, and `.env` material
  remain secret and must not be printed, committed, or copied into docs.

Canonical supporting docs:

- `docs/operations/local-verification-matrix.md`
- `docs/SESSION_HANDOFF.md`
- `AGENT_STATE.md`
- `next-session-autonomous-local-plan.md`

## Work Plan

- [x] Stabilize latest code HEAD evidence through `271b82c`.
  Verify: `git status --short --branch --untracked-files=no`; six workflows
  checked on HEAD; Load Test run IDs recorded when runner variance appears.
  Evidence: CI, Contract Tests, E2E Tests, Load Test, Security Scan, and
  Staging Deploy all succeeded on `271b82c`. Prior Load Test variance on
  `44df329` is recorded in `AGENT_STATE.md`.

- [ ] Finish `src/serving/api` strict mypy coverage by bounded slices.
  Verify each slice with policy-test red->green, `python -m mypy src
  --config-file pyproject.toml`, focused tests, broad no-Docker unit tests,
  OpenAPI check, ruff, `git diff --check`, commit, push, and six workflows.
  Latest slices: `src.serving.api.rate_limiter` reached strict mypy coverage in
  `b0c784f`, and `src.serving.api.security` reached strict mypy coverage in
  `44df329`; `src.serving.api.versioning` reached strict mypy coverage in
  `eb5919e`; `src.serving.api.analytics` reached strict mypy coverage in
  `271b82c`.

- [ ] Use Claude as second opinion for risky slices.
  Required for `src/serving/api/main.py`, `routers/admin.py`,
  `alerts/dispatcher.py`, `webhook_dispatcher.py`, Load Test interpretation,
  auth/hash-format changes, branch-protection changes, and any migration-like
  work.

- [ ] Treat Load Test failures as evidence, not noise.
  Verify with `docs/runbooks/load-test-regression.md`: compare failed/green
  runs, check functional failure rate, rerun only within the runbook limit, and
  do not raise thresholds without a documented baseline decision.

- [ ] Run Docker-heavy checks only on Mac/CI.
  Verify by recording command, commit SHA, host (`julia@192.168.1.133` or CI),
  and result. Windows evidence must be reported as no-Docker unless Mac/CI
  evidence is attached.

- [ ] Resolve or explicitly block `src/processing/flink_jobs`.
  Verify whether any prep is safe without Docker/Flink runtime. Otherwise keep
  it gated on PR #23 / Flink 2.x Kafka connector / Mac-Docker evidence.

- [ ] Close admin/external boundaries honestly.
  Branch protection, deploy, release, publish, Terraform, scheduler/env,
  secret/account work, customer evidence, production CDC, production hardware,
  and external pen-test items require real artifacts or explicit authority.

## Done When

- [ ] All local code/test/docs questions are either committed and verified, or
  are explicitly marked blocked with the missing evidence.
- [ ] Every Docker-heavy claim has Mac/CI evidence.
- [ ] Every external/admin question has an owner, required artifact, and next
  action.
- [ ] Claude review/second-opinion notes exist for risky local changes.
- [ ] No item is closed using generated, assumed, or placeholder evidence.
