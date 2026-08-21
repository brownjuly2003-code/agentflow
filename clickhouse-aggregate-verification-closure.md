# ClickHouse aggregate verification closure

## Goal

Prove the open ClickHouse cutover verification contract at the current tracked
HEAD without touching the reserved r9 rehearsal, production, or protected
untracked artifacts.

## Repository and evidence map

- Closing implementation/evidence commit:
  `dc40321f291a992830111faceb4b9ecd3cb364f5`
  (`test(integration): harden shared-host aggregate gate`).
- Exact source baseline for the full unit/property, Ruff, and mypy lanes:
  `2d71bebb792096576a3afeada46728bf88d1e05b`.
- The live integration result applies to that baseline plus the harness-only
  changes contained in `dc40321`. A later documentation-only HEAD does not
  imply that the aggregate was rerun at that docs commit.
- The independent r9 preflight remains tied to executed source/gate HEAD
  `7e8ec87c25bbdc8f8aa58c116ded9914470789cb`; neither local commit above
  replaces that runtime identity.

## Tasks

- [x] Confirm the tracked baseline, protected paths, CI commands, and mutation
  target policy.
- [x] Ask Grok for one bounded read-only audit of the exact aggregate contract
  and likely local blockers.
- [x] Run the unit/property and live ClickHouse integration lanes in an isolated
  verification environment, then run Ruff and mypy once.
- [x] Record exact evidence in `docs/clickhouse-cutover-plan.md` only if every
  required lane is green.
- [x] Verify scoped diff/encoding and prepare an explicit-pathspec local commit.

## Done when

- [x] Unit/property tests, live ClickHouse integration, Ruff, mypy, and mutation
  target-policy checks are green against the exact baseline plus the scoped
  harness-only closing patch, with the evidence boundary mapped below.
- [x] No r9 controller, co-tenant stop, production action, push, or protected
  untracked-file mutation occurred.

## Evidence

- Exact tracked baseline: `2d71bebb792096576a3afeada46728bf88d1e05b`;
  local and Mac archive SHA-256 matched at
  `5e3f66618a92ae6234a3ada72747e6c9ec7ad6815d4d654bab7afa058045e724`.
- Unit/property: `2401 passed`, branch coverage `78.00%` (60% required).
- The first unit attempt used stale shared-environment identities (`docker` in
  the interpreter path and installed SDK metadata `1.5.0`). The same exact
  source then passed in an isolated current-SDK environment; this was an
  environment correction, not an application change.
- Live integration after the harness-only correction: `332 passed`, `12`
  expected optional skips, one deprecation warning, `190.83s`; ClickHouse
  25.3 and PostgreSQL 17 used isolated ports, and all disposable services were
  separate from r9/co-tenants.
- The disclosed first integration attempt ended `325 passed, 12 skipped, 7
  errors`. Every error was fixture/environmental: protected MinIO already
  owned host port `9000`, and Kafka exceeded Testcontainers' 30-second cold-
  start timeout. One batched harness correction and the single permitted
  rerun produced the green result above.
- Affected unit/config checks: `7 passed`; Ruff lint and format clean; Compose
  rendered both default `9000/9001/8181` and remapped `19000/19001/18181`
  host ports.
- The touched Iceberg Compose file was normalized from its committed CRLF form
  to the workspace-required LF; ignoring EOL, its diff is only the three host-
  port substitutions.
- Full Ruff/mypy evidence at `2d71beb` remains applicable because the closing
  patch changes only tests and the Iceberg test Compose harness; affected
  Python files passed focused Ruff after the patch.
- Mutation retargeting was not required: the deleted app-side PII modules are
  absent from both declared and executed mutation targets, and the mutation-
  policy test passed in the full unit lane.

## Postflight and retained state

- The four protected Mac containers remained `running` with restart count `0`:
  MinIO `f51db9e3ee0715bbfc91c2a715a4fc114f80fdbe82e156e89db74626b729aa42`,
  Iceberg REST
  `1e80588ca8fb0859934ada5635731027ca6692d9db597105504b1f7c2d761211`,
  ClickHouse
  `f0f0b82817bb87ec522f16426795df021e8d249fdc0c07a9474ac34717488c61`,
  and Kind
  `0545702c4bc4ffdb5402b324af5dd51af71bed57ca7078707c931eae8aee365b`.
- Disposable ClickHouse/PostgreSQL and failed Iceberg/Kafka resources were
  removed. No background writer remains.
- Recursive cleanup was rejected before execution. Leave these harmless
  artifacts to system cleanup; do not raw-retry the rejected operation:
  `/private/tmp/deproject-aggregate-2d71beb-20260821-01` on the Mac and
  `%LOCALAPPDATA%\Temp\deproject-aggregate-2d71beb-20260821-01.tar` on
  Windows.

## Next-session resume boundary

1. Start read-only with `git status --short --branch`, `git rev-parse HEAD`,
   the first block in `AGENT_STATE.md`, and this tracked closure record.
2. If `dc40321f291a992830111faceb4b9ecd3cb364f5` is an ancestor and the tracked
   tree is clean, treat the aggregate gate as closed. Do not rerun it merely
   to refresh evidence.
3. Preserve every established untracked/ignored path and never bulk-stage.
   Do not retry the rejected temporary-artifact cleanup.
4. The only open ClickHouse checklist item is the GraceKelly shipped-deployment
   reachability product/configuration choice; it is not a local code defect.
5. Do not start the r9 controller, stop co-tenants, use its reserved identities,
   run a full soak or rollback, clean runtime evidence, touch production, fetch,
   push, or infer authorization from earlier continuation messages. Each such
   boundary requires fresh explicit authorization.
