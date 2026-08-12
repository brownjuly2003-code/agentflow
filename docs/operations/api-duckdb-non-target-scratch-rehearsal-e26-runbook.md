# API DuckDB E26 non-target scratch rehearsal runbook

**Date:** 2026-08-11
**Status:** `READY_NOT_AUTHORIZED`; documentation only, no rehearsal started
**Audience:** operator for one separately authorized non-target rehearsal

## Purpose and authority boundary

E26 defines a fresh one-shot identity after E25 fixed both remote text-file
compatibility paths locally. E24 remains consumed with five `PASS`, two
historical `BLOCKED`, and exact cleanup proved. E25 added no live evidence,
so both runtime branches remain ineligible and status remains
`CAPABILITY_REHEARSAL_REQUIRED` / `PRESERVATION_PARTIAL`.

This runbook does not authorize execution. A later session may run the one
documented invocation only after a new user message explicitly authorizes the
E26 non-target scratch rehearsal. Target Pod/volume access, DuckDB/WAL access,
capture, repair, recovery, traffic, production transition, and push remain
unauthorized.

## Reserved E26 identity

| Field | Exact value |
| --- | --- |
| Protected implementation commit | `82a00622aa6f21b7c87a72edeafc979d1d213093` |
| SSH host | `deproject-mac` |
| Run ID | `api-duckdb-scratch-e26-20260811-01` |
| Scratch root | `/tmp/agentflow-api-duckdb-capability-rehearsal/api-duckdb-scratch-e26-20260811-01` |
| Acknowledgement | `NON_TARGET_SCRATCH_REHEARSAL_ONLY` |
| Evidence directory | `.codex-grok-tasks/api-duckdb-scratch-rehearsal-e26-20260811-codex01/` |
| Expected script SHA-256 | `d7bf34f28369b51565cf8125c62b949532b95e867f2b4c120f8472da0cc5f273` |
| Expected test SHA-256 | `a6b8f66e2e7af42b0ee2107bc57608f495baaaf22d711f7b2515c863cf7e051d` |

At authoring time the run ID was unused in the tracked workspace and the
local evidence directory was absent. No remote scratch query was made. A
local or remote collision consumes E26; do not select a fallback identity.

## Mandatory preflight for a later session

1. Read the authoritative top blocks in `AGENT_STATE.md` and
   `docs/SESSION_HANDOFF.md`, then read this entire runbook.
2. Recheck the latest user message. Without fresh explicit authorization for
   the exact E26 non-target run, report
   `READY_FOR_ONE_NON_TARGET_SCRATCH_RUN_E26` and stop before SSH.
3. Refresh `git status --short --branch` and protect unrelated files. The
   tracked tree and index must be clean. Commit
   `82a00622aa6f21b7c87a72edeafc979d1d213093` must be an ancestor of `HEAD`.
4. Recompute both protected hashes above. A mismatch blocks execution. Do not
   rerun E25 tests merely to refresh evidence when the hashes are unchanged.
5. Confirm the exact local evidence directory is absent and no E26 writer,
   yielded command, or previous process is active.
6. Do not pre-query or reserve the remote path. The harness rejects an
   existing exact root before probe work.

Any failed preflight consumes no alternate identity and ends the slice before
SSH.

## One authorized invocation

Run at most once from `D:\DE_project`:

```powershell
python scripts/rehearse_api_duckdb_quiesce_capabilities.py `
  --execute `
  --acknowledge NON_TARGET_SCRATCH_REHEARSAL_ONLY `
  --run-id api-duckdb-scratch-e26-20260811-01 `
  --scratch-root /tmp/agentflow-api-duckdb-capability-rehearsal/api-duckdb-scratch-e26-20260811-01
```

Capture UTC immediately before and after the command. Capture stdout and
stderr directly from the command tool without a PowerShell pipe or redirect.
On exit `0`, stdout must parse as strict JSON with no duplicate keys. Preserve
exact stdout as UTF-8/LF `result.json`; never reconstruct probe fields from
memory or logs.

Timeout, nonzero exit, malformed output, a path collision, or any schema
failure consumes E26 and ends the run. Do not retry, change the identity, or
manually continue individual probes.

## Result classification

The executed schema must contain seven exact `capability_checks`, matching
`check_evidence`, and both branch values. Classify the untouched JSON as:

| Condition | Classification |
| --- | --- |
| Seven `PASS` values | `SCRATCH_REHEARSAL_PASS_NON_TARGET_ONLY` |
| No `BLOCKED`, at least one `PARTIAL` | `SCRATCH_REHEARSAL_PARTIAL` |
| Any `BLOCKED` | `SCRATCH_REHEARSAL_BLOCKED` |
| Timeout, nonzero, malformed/missing output | `SCRATCH_REHEARSAL_TRANSPORT_BLOCKED` |

Even seven `PASS` values do not prove target containerd/cgroup behavior,
cross-namespace descriptors, target watchdog recovery, `T_safe`, I04/I05/I09,
branch eligibility, capture safety, or DuckDB recoverability.

## One cleanup verification

After the invocation ends, perform exactly one read-only check:

```powershell
ssh deproject-mac "test ! -e /tmp/agentflow-api-duckdb-capability-rehearsal/api-duckdb-scratch-e26-20260811-01"
```

Exit `0` proves only that the exact E26 root is absent. Any other result is
`CLEANUP_NOT_PROVED`; record bounded stderr and stop. Do not run `rm`, a
cleanup helper, a second check, or another rehearsal without a new explicit
authorization.

## Evidence pack

Create the reserved evidence directory only as part of the authorized run and
write:

- `result.json`: exact valid stdout, or a minimal fail-closed transport record
  that invents no probe data;
- `result.md`: identity, classification, seven statuses, cleanup result,
  claim boundary, and next gate;
- `evidence.md`: UTC start/end, exact command shape, exit code, bounded
  stderr, protected hashes, schema checks, and explicit non-actions.

Validate duplicate-key strict JSON, UTF-8/LF, cross-artifact identity and
status consistency, SHA-256 values, local links, and absence of secrets.
Update the canonical design and both top handoff blocks once. Evidence remains
local and untracked unless a later explicit instruction changes that boundary.

## Prohibited fallback

Do not reuse E22 or E24, rerun E25 implementation tests without changed
inputs, manufacture E27 after a failure, or launch Grok/another writer for the
run. Do not access or mutate the current Pod, its UID-derived `emptyDir`,
DuckDB/WAL files, kubelet, containerd target tasks, Kubernetes objects,
dependencies, traffic, or production state.
