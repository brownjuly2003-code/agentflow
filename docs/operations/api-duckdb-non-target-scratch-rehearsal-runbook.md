# API DuckDB non-target scratch rehearsal runbook

**Date:** 2026-08-11
**Status:** `READY_FOR_ONE_NON_TARGET_SCRATCH_RUN`; not executed
**Audience:** next-session Codex operator

## Purpose and current truth

This runbook preserves the exact next-session contract for E22 in
[the canonical recovery design](api-duckdb-persistence-recovery-design.md).
The harness and its seven probes are implemented at commit `26a468b`, but no
SSH or `--execute` invocation has run. Every observed capability remains
`NOT_RUN`; the authoritative runtime status is still
`CAPABILITY_REHEARSAL_REQUIRED` / `PRESERVATION_PARTIAL`.

This runbook is not authority to act. A latest user message must explicitly
continue or authorize the isolated non-target scratch run. It never authorizes
target Pod/volume access, DuckDB bytes, capture, repair, recovery, traffic,
production transition, or push.

## Fixed identity for the next run

| Field | Exact value |
| --- | --- |
| SSH host | `deproject-mac` |
| Run ID | `api-duckdb-scratch-e22-20260811-01` |
| Scratch root | `/tmp/agentflow-api-duckdb-capability-rehearsal/api-duckdb-scratch-e22-20260811-01` |
| Acknowledgement | `NON_TARGET_SCRATCH_REHEARSAL_ONLY` |
| Evidence directory | `.codex-grok-tasks/api-duckdb-scratch-rehearsal-e22-20260811-codex01/` |
| Expected script SHA-256 | `e44540da356644272c35e131939da0b2f1c9b00a68a42f0e8f30d01bb6d780b0` |
| Expected test SHA-256 | `734dbad7e14ac82b2cc1bea74105649710e007d66a4bc3031efb169b3d0da46e` |

The run ID is reserved and the local evidence directory was absent when this
runbook was written. The remote scratch root was not queried in this docs-only
slice. The harness rejects an existing exact root before its probe work; that
collision consumes no fallback identity. Stop and document it.

## Resume preflight

1. Read the top blocks of `AGENT_STATE.md` and `docs/SESSION_HANDOFF.md`, then
   this entire runbook. Lower `START HERE` blocks are historical.
2. Refresh `git status --short --branch` and `git log -2 --oneline`. Protect
   all unrelated untracked files. The tracked tree must be clean.
3. Verify the two SHA-256 values above. Do not rerun the already-green local
   test/lint gates unless the script or test hash changed.
4. Confirm the exact evidence directory is absent locally. Confirm no writer,
   yielded command, or previous E22 process is active.
5. Recheck the latest user message. Without explicit current authorization for
   this non-target scratch run, report `READY_FOR_ONE_NON_TARGET_SCRATCH_RUN`
   and wait.

Any failed preflight ends the slice before SSH.

## Single authorized invocation

Run this command once from `D:\DE_project`:

```powershell
python scripts/rehearse_api_duckdb_quiesce_capabilities.py `
  --execute `
  --acknowledge NON_TARGET_SCRATCH_REHEARSAL_ONLY `
  --run-id api-duckdb-scratch-e22-20260811-01 `
  --scratch-root /tmp/agentflow-api-duckdb-capability-rehearsal/api-duckdb-scratch-e22-20260811-01
```

Do not pipe or redirect stdout in Windows PowerShell 5.1; its encoding may
change the JSON bytes. Let the command tool capture stdout/stderr. After the
process exits, preserve the exact stdout as UTF-8/LF `result.json` through a
scoped file edit. Never reconstruct result fields from memory.

The invocation is single-attempt. A timeout, nonzero exit, malformed JSON,
schema rejection, transport loss, or any `BLOCKED` check ends the run. Do not
raw-retry and do not switch to a new run ID automatically.

## Required result contract

Successful command transport returns exactly:

- `status=NON_TARGET_SCRATCH_REHEARSAL_EXECUTED`;
- `execute=true`;
- seven exact `capability_checks` values, each `PASS`, `PARTIAL`, or
  `BLOCKED`—never `NOT_RUN`;
- seven matching `check_evidence` objects with
  `scope=non-target scratch only`;
- `PAUSED_TASK=ineligible` and `KUBELET_GAP=ineligible`.

Classify the observed result without changing the raw JSON:

| Condition | Session classification | Required response |
| --- | --- | --- |
| Seven `PASS` values | `SCRATCH_REHEARSAL_PASS_NON_TARGET_ONLY` | Preserve evidence; do not infer target eligibility |
| No `BLOCKED`, at least one `PARTIAL` | `SCRATCH_REHEARSAL_PARTIAL` | Preserve evidence and exact partial constraints; stop |
| Any `BLOCKED` | `SCRATCH_REHEARSAL_BLOCKED` | Preserve evidence and first decisive blocker; stop |
| Timeout, nonzero, malformed/missing output | `SCRATCH_REHEARSAL_TRANSPORT_BLOCKED` | Preserve bounded stdout/stderr/exit evidence; stop |

Even `SCRATCH_REHEARSAL_PASS_NON_TARGET_ONLY` does not prove containerd or
cgroup pause, cross-namespace target descriptors, target watchdog recovery,
`T_safe`, I04/I05/I09, a corrected runtime branch, capture, or DuckDB
recoverability.

## Cleanup verification

After the invocation returns, perform one read-only exact-path cleanup check:

```powershell
ssh deproject-mac "test ! -e /tmp/agentflow-api-duckdb-capability-rehearsal/api-duckdb-scratch-e22-20260811-01"
```

Exit `0` means the exact per-run root is absent. The fixed parent directory may
remain and is not a failure. Any other exit is `SCRATCH_CLEANUP_UNPROVED`.
Record it and stop; do not issue `rm`, `find -delete`, another cleanup helper,
or a second rehearsal automatically.

## Evidence pack

Only after the single invocation, create the reserved evidence directory with:

- `result.json`: exact captured JSON stdout when valid; otherwise a minimal
  fail-closed JSON record of exit/transport status with no invented probe data;
- `result.md`: run identity, classification, seven statuses, cleanup result,
  claim boundary, and next gate;
- `evidence.md`: UTC start/end, exact command shape, exit code, bounded safe
  stderr, hashes, schema checks, and explicit non-actions.

Validate unique JSON keys, UTF-8/LF, exact cross-artifact facts, secret
patterns, and SHA-256 for all three files. Record the result in the canonical
design and both top handoff blocks once. A docs commit is allowed only after
the evidence gate passes; push remains unauthorized.

## Prohibited fallback

Do not access or mutate the current Pod, its UID-derived `emptyDir`, DuckDB or
WAL files, kubelet, containerd target tasks, Kubernetes objects, dependencies,
traffic, or production state. Do not start Grok or another writer for the run.
Do not repeat E20, E21, E22 implementation, or their green validators without
changed code or a fresh failing diagnostic.
