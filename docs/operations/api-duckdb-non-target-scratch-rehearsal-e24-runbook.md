# API DuckDB E24 non-target scratch rehearsal runbook

**Date:** 2026-08-11
**Status:** `CONSUMED_SCRATCH_REHEARSAL_BLOCKED`; do not execute or reuse
**Audience:** historical evidence and future compatibility-fix author

## Purpose and current truth

This runbook preserves the consumed E24 non-target scratch rehearsal after E23
fixed Windows LF transport in
[`rehearse_api_duckdb_quiesce_capabilities.py`](../../scripts/rehearse_api_duckdb_quiesce_capabilities.py).
The one E24 invocation returned five `PASS` and two `BLOCKED` results. The
exact root was absent in the single cleanup check. Both runtime branches remain
ineligible, and status remains `CAPABILITY_REHEARSAL_REQUIRED` /
`PRESERVATION_PARTIAL`.

This identity, command, root, and evidence directory must not be reused. A
future attempt requires a local compatibility fix, a new runbook, a new
identity, and fresh explicit authorization. This document never authorizes
target Pod/volume access, DuckDB/WAL access, capture, repair, recovery,
traffic, production transition, or push.

## Consumed E24 identity — historical only

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

## Consumed outcome

The single invocation ran from `2026-08-11T13:32:12.1197300Z` through
`2026-08-11T13:32:29.3139985Z`, exited `0`, and returned the exact executed
schema. Timing, scratch pause/resume, watchdog, same-directory rename, and
file/directory sync passed. Descriptor visibility and metadata capability
were blocked before their operations because the remote `Path.write_text`
API rejected the `newline` keyword with `TypeError`.

The one read-only cleanup check exited `0`, proving the exact per-run root
absent. Local evidence:
[`result.json`](../../.codex-grok-tasks/api-duckdb-scratch-rehearsal-e24-20260811-codex01/result.json),
[`result.md`](../../.codex-grok-tasks/api-duckdb-scratch-rehearsal-e24-20260811-codex01/result.md),
and
[`evidence.md`](../../.codex-grok-tasks/api-duckdb-scratch-rehearsal-e24-20260811-codex01/evidence.md).
SHA-256: JSON
`389c779bd0948e41ecdd50208ca913a8dc08e48dad0e8057f3fe84755a4f1068`,
summary `b915db6a8240cb7e1484fea3b836efd2eb6648a711a3e597be5eac7c5471acea`,
ledger `6f0893ab2f78a132d9ae9d71f1a1d504546a9c83b17c2559e8446fa96e3cfb71`.

The next separate candidate is a local TDD compatibility fix for the two
embedded `Path.write_text(..., newline="\n")` calls. It must not run SSH. A
later rehearsal requires a new identity and separate authorization.

## Historical preflight — do not reuse

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

## Consumed invocation — do not rerun

The consumed contract captured UTC around and ran the following command once
from `D:\DE_project`:

```powershell
python scripts/rehearse_api_duckdb_quiesce_capabilities.py `
  --execute `
  --acknowledge NON_TARGET_SCRATCH_REHEARSAL_ONLY `
  --run-id api-duckdb-scratch-e24-20260811-01 `
  --scratch-root /tmp/agentflow-api-duckdb-capability-rehearsal/api-duckdb-scratch-e24-20260811-01
```

The command tool captured stdout/stderr directly without a PowerShell pipe or
redirect. Exact valid stdout became UTF-8/LF `result.json`; no probe field was
reconstructed from memory.

E24 remains single-attempt and consumed. Its `BLOCKED` results ended the run;
no retry or identity switch occurred.

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

## Recorded cleanup verification

The consumed contract performed exactly one read-only check:

```powershell
ssh deproject-mac "test ! -e /tmp/agentflow-api-duckdb-capability-rehearsal/api-duckdb-scratch-e24-20260811-01"
```

It exited `0`, proving the per-run root absent. No `rm`, cleanup helper,
second check, or another rehearsal ran.

## Recorded evidence pack

The reserved local directory contains:

- `result.json`: exact valid stdout, or a minimal fail-closed transport record
  with no invented probe data;
- `result.md`: identity, classification, seven statuses, cleanup, boundary,
  and next gate;
- `evidence.md`: UTC start/end, command shape, exit code, bounded stderr,
  protected hashes, schema checks, and explicit non-actions.

The pack passed duplicate-key strict JSON, UTF-8/LF, cross-artifact, secret,
and SHA-256 checks. The outcome is recorded in the canonical design and both
top handoff blocks. Local evidence remains untracked and push unauthorized.

## Prohibited fallback

Do not access or mutate the current Pod, its UID-derived `emptyDir`, DuckDB or
WAL files, kubelet, containerd target tasks, Kubernetes objects, dependencies,
traffic, or production state. Do not start Grok or another writer for the
run. Do not reuse E22, repeat E23 implementation/gates, or manufacture an E25
identity after an E24 failure.
