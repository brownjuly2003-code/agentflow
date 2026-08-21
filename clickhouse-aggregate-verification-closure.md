# ClickHouse aggregate verification closure

## Goal

Prove the open ClickHouse cutover verification contract at the current tracked
HEAD without touching the reserved r9 rehearsal, production, or protected
untracked artifacts.

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
- Live integration after the harness-only correction: `332 passed`, `12`
  expected optional skips; ClickHouse 25.3 and PostgreSQL 17 used isolated
  ports, and all disposable services were separate from r9/co-tenants.
- Affected unit/config checks: `7 passed`; Ruff lint and format clean; Compose
  rendered both default `9000/9001/8181` and remapped `19000/19001/18181`
  host ports.
- The touched Iceberg Compose file was normalized from its committed CRLF form
  to the workspace-required LF; ignoring EOL, its diff is only the three host-
  port substitutions.
- Full Ruff/mypy evidence at `2d71beb` remains applicable because the closing
  patch changes only tests and the Iceberg test Compose harness; affected
  Python files passed focused Ruff after the patch.
