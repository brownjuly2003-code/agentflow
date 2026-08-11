# API DuckDB E24 non-target scratch rehearsal runbook

**Date:** 2026-08-11
**Status:** `READY_FOR_ONE_NON_TARGET_SCRATCH_RUN_E24`; not executed
**Audience:** next-session Codex operator

## Purpose and current truth

This runbook defines one replacement non-target scratch rehearsal after E23
fixed Windows LF transport in
[`rehearse_api_duckdb_quiesce_capabilities.py`](../../scripts/rehearse_api_duckdb_quiesce_capabilities.py).
The earlier E22 identity is consumed and must not be retried. No E24 SSH or
`--execute` invocation has run; all seven authoritative capability results
remain `NOT_RUN`, both runtime branches remain ineligible, and status remains
`CAPABILITY_REHEARSAL_REQUIRED` / `PRESERVATION_PARTIAL`.

This document is not execution authority. A latest user message must
explicitly authorize the isolated E24 non-target scratch run. It never
authorizes target Pod/volume access, DuckDB/WAL access, capture, repair,
recovery, traffic, production transition, or push.

## Fixed E24 identity

| Field | Exact value |
| --- | --- |
| Protected implementation commit | `ad81131c041aa93e7913715dff2ed07b4d8e2b96` |
| SSH host | `deproject-mac` |
| Run ID | `api-duckdb-scratch-e24-20260811-01` |
| Scratch root | `/tmp/agentflow-api-duckdb-capability-rehearsal/api-duckdb-scratch-e24-20260811-01` |
| Acknowledgement | `NON_TARGET_SCRATCH_REHEARSAL_ONLY` |
| Evidence directory | `.codex-grok-tasks/api-duckdb-scratch-rehearsal-e24-20260811-codex01/` |
| Expected script SHA-256 | `d2a8fd8715d4182cc0def0d5283c045a66eb197d979faaecfab2c1e7781faa7f` |
| Expected test SHA-256 | `74e347553e2416eb5ec5bd8cca107b097dbac06cf318c4b89cc2dcaab2ccc0bc` |

The local evidence directory was absent when this runbook was written. The
remote scratch root was deliberately not queried; the harness rejects an
existing exact root before probe work. A collision consumes E24 without a
fallback identity.

## Preflight

1. Read the authoritative top blocks of `AGENT_STATE.md` and
   `docs/SESSION_HANDOFF.md`, then this entire runbook.
2. Refresh `git status --short --branch` and `git log -2 --oneline`. Protect
   unrelated untracked files; the tracked tree must be clean.
3. Verify the protected commit and both SHA-256 values above. Do not rerun the
   green E23 test/lint gates when those inputs are unchanged.
4. Confirm the exact evidence directory is absent locally and no E24 writer,
   yielded command, or previous process is active.
5. Recheck the latest user message. Without explicit current authorization
   for the E24 non-target run, report
   `READY_FOR_ONE_NON_TARGET_SCRATCH_RUN_E24` and wait.

Any failed preflight ends the slice before SSH. Do not query or reserve a
fallback remote identity.

## Single authorized invocation

Capture UTC immediately before the command. Run the following once from
`D:\DE_project`, allowing the command tool at least 120 seconds:

```powershell
python scripts/rehearse_api_duckdb_quiesce_capabilities.py `
  --execute `
  --acknowledge NON_TARGET_SCRATCH_REHEARSAL_ONLY `
  --run-id api-duckdb-scratch-e24-20260811-01 `
  --scratch-root /tmp/agentflow-api-duckdb-capability-rehearsal/api-duckdb-scratch-e24-20260811-01
```

Do not pipe or redirect stdout in Windows PowerShell 5.1. Let the command tool
capture stdout/stderr, then capture UTC immediately after exit. Preserve valid
stdout byte-for-byte as UTF-8/LF `result.json`; never reconstruct probe fields
from memory.

The invocation is single-attempt. Timeout, nonzero exit, malformed JSON,
schema rejection, transport loss, identity collision, or any `BLOCKED` check
ends the run. Do not retry or switch identity automatically.

## Result contract

Successful transport returns exactly:

- `status=NON_TARGET_SCRATCH_REHEARSAL_EXECUTED` and `execute=true`;
- seven exact `capability_checks`, each `PASS`, `PARTIAL`, or `BLOCKED`;
- seven matching `check_evidence` objects with
  `scope=non-target scratch only`;
- `PAUSED_TASK=ineligible` and `KUBELET_GAP=ineligible`.

Classify without changing raw JSON:

| Condition | Classification |
| --- | --- |
| Seven `PASS` values | `SCRATCH_REHEARSAL_PASS_NON_TARGET_ONLY` |
| No `BLOCKED`, at least one `PARTIAL` | `SCRATCH_REHEARSAL_PARTIAL` |
| Any `BLOCKED` | `SCRATCH_REHEARSAL_BLOCKED` |
| Timeout, nonzero, malformed/missing output | `SCRATCH_REHEARSAL_TRANSPORT_BLOCKED` |

Even seven `PASS` values do not prove target containerd/cgroup behavior,
cross-namespace descriptors, target watchdog recovery, `T_safe`, I04/I05/I09,
branch eligibility, capture, or DuckDB recoverability.

## Cleanup verification

After the invocation returns, perform exactly one read-only check:

```powershell
ssh deproject-mac "test ! -e /tmp/agentflow-api-duckdb-capability-rehearsal/api-duckdb-scratch-e24-20260811-01"
```

Exit `0` proves the per-run root absent. Any other result is
`SCRATCH_CLEANUP_UNPROVED`; record it and stop. Do not run `rm`, a cleanup
helper, a second check, or another rehearsal.

## Evidence pack

Only after the invocation, create the reserved directory with:

- `result.json`: exact valid stdout, or a minimal fail-closed transport record
  with no invented probe data;
- `result.md`: identity, classification, seven statuses, cleanup, boundary,
  and next gate;
- `evidence.md`: UTC start/end, command shape, exit code, bounded stderr,
  protected hashes, schema checks, and explicit non-actions.

Validate duplicate-key strict JSON, UTF-8/LF, cross-artifact facts, secret
patterns, local links, and SHA-256 for all three files. Record the outcome in
the canonical design and both top handoff blocks once. Commit only verified
tracked docs with explicit pathspec; keep local evidence untracked. Push
remains unauthorized.

## Prohibited fallback

Do not access or mutate the current Pod, its UID-derived `emptyDir`, DuckDB or
WAL files, kubelet, containerd target tasks, Kubernetes objects, dependencies,
traffic, or production state. Do not start Grok or another writer for the
run. Do not reuse E22, repeat E23 implementation/gates, or manufacture an E25
identity after an E24 failure.
