# API DuckDB non-target scratch rehearsal runbook

**Updated:** 2026-08-27

**Status:** `READY_NOT_AUTHORIZED`; no run identity is reserved

**Audience:** operator preparing one separately authorized non-target rehearsal

## Purpose and authority boundary

This is the current procedure for exercising the API DuckDB capability harness
on a fresh directory below
`/tmp/agentflow-api-duckdb-capability-rehearsal/`. The rehearsal is limited to
seven non-target scratch checks. It cannot prove target Pod or volume behavior,
DuckDB or WAL recoverability, I04/I05/I09, branch eligibility, capture safety,
or production readiness.

The procedure has two phases. Preparing a fresh identity is local and does not
use SSH. Executing the harness requires a later user message that explicitly
authorizes that exact identity and host.
**A prepared identity is not authorization.** A generic request to continue
documentation work does not authorize the execution phase.

The consumed E22, E24, and E26 contracts are preserved in the
[operational archive](../archive/operations/README.md). Never copy a run ID,
scratch root, command, or evidence directory from those records.

## Preconditions

- Read the current top blocks of `AGENT_STATE.md` and
  `docs/SESSION_HANDOFF.md`, this guide, and the
  [canonical recovery design](api-duckdb-persistence-recovery-design.md).
- Keep the tracked worktree and Git index clean. Preserve unrelated untracked
  files and confirm no rehearsal writer or yielded command is active.
- Use the tracked
  `scripts/rehearse_api_duckdb_quiesce_capabilities.py` harness and
  `tests/unit/test_api_duckdb_quiesce_capability_rehearsal.py` contract.
- Use SSH host `deproject-mac`. Do not start WSL, Docker, kind, or equivalent
  infrastructure on Windows.
- Stop before SSH unless the latest user message authorizes the exact prepared
  host, run ID, and scratch root.

## Phase 1: prepare a fresh identity without SSH

From `D:\DE_project` in Windows PowerShell 5.1, generate one candidate:

```powershell
$utcStamp = (Get-Date).ToUniversalTime().ToString("yyyyMMdd-HHmmss")
$runId = "api-duckdb-scratch-$utcStamp"
$scratchRoot = "/tmp/agentflow-api-duckdb-capability-rehearsal/$runId"
$evidenceDirectory = ".codex-grok-tasks/$runId/"
$sourceCommit = git rev-parse HEAD
$scriptHash = (Get-FileHash -LiteralPath "scripts/rehearse_api_duckdb_quiesce_capabilities.py" -Algorithm SHA256).Hash.ToLowerInvariant()
$testHash = (Get-FileHash -LiteralPath "tests/unit/test_api_duckdb_quiesce_capability_rehearsal.py" -Algorithm SHA256).Hash.ToLowerInvariant()

Write-Output $sourceCommit
Write-Output $runId
Write-Output $scratchRoot
Write-Output $evidenceDirectory
Write-Output $scriptHash
Write-Output $testHash
Test-Path -LiteralPath $evidenceDirectory
```

`Test-Path` must return `False`. Record the six exact values in the proposed
execution packet and request explicit authorization for that packet. Stop. Do
not create the evidence directory, query or reserve the remote path, invoke
SSH, or regenerate the identity after authorization.

## Phase 2: preflight the authorized identity

After explicit authorization, restore the exact recorded values; do not derive
a new timestamp. Then verify all of the following:

1. The authorized host is `deproject-mac`, and the run ID and scratch root
   exactly match the prepared packet.
2. `git rev-parse HEAD` and both SHA-256 values still match the packet. A
   mismatch invalidates the authorization and requires a new preparation
   phase, not an execution attempt.
3. `git diff --quiet` and `git diff --cached --quiet` both exit `0`. Existing
   unrelated untracked files remain protected.
4. The local evidence directory is still absent, and no process or writer owns
   this identity.
5. The latest user message still explicitly authorizes this exact non-target
   rehearsal. Push, deployment, target access, and production changes remain
   outside that authority.

Do not pre-query the remote scratch root. The harness validates the run ID,
requires the exact fixed prefix, rejects an existing exact root, uses a
sentinel, and performs bounded cleanup. Any failed preflight ends the slice
before SSH.

## One authorized invocation

Run at most once, using the unchanged authorized variables:

```powershell
python scripts/rehearse_api_duckdb_quiesce_capabilities.py `
  --ssh-host deproject-mac `
  --execute `
  --acknowledge NON_TARGET_SCRATCH_REHEARSAL_ONLY `
  --run-id $runId `
  --scratch-root $scratchRoot
```

Capture UTC immediately before and after the command. Let the command tool
capture stdout and stderr directly; do not pipe or redirect them through
Windows PowerShell. On exit `0`, parse stdout as strict unique-key JSON and
preserve those exact UTF-8/LF bytes as `result.json`. Never reconstruct probe
fields from memory or logs.

A timeout, nonzero exit, malformed output, path collision, schema failure, or
any `BLOCKED` result consumes the identity. Stop without retrying, changing the
identity, or continuing an individual probe manually.

## Result classification

The executed schema must contain the seven exact `capability_checks`, matching
`check_evidence`, and both ineligible branch values.

| Condition | Classification |
| --- | --- |
| Seven `PASS` values | `SCRATCH_REHEARSAL_PASS_NON_TARGET_ONLY` |
| No `BLOCKED`, at least one `PARTIAL` | `SCRATCH_REHEARSAL_PARTIAL` |
| Any `BLOCKED` | `SCRATCH_REHEARSAL_BLOCKED` |
| Timeout, nonzero, malformed or missing output | `SCRATCH_REHEARSAL_TRANSPORT_BLOCKED` |

Even a non-target PASS does not upgrade the recovery design or either runtime
branch.

## One cleanup verification

After the invocation ends, perform exactly one read-only absence check with the
authorized value:

```powershell
ssh deproject-mac "test ! -e '$scratchRoot'"
```

Exit `0` proves only that this exact scratch root is absent. Any other result is
`SCRATCH_CLEANUP_UNPROVED`; record bounded stderr and stop. Do not run `rm`, a
cleanup helper, a second check, or another rehearsal automatically.

## Evidence pack

Only after the invocation, create the authorized local evidence directory and
write:

- `result.json`: exact valid stdout, or a minimal fail-closed transport record
  with no invented probe data;
- `result.md`: identity, classification, seven statuses, cleanup result, claim
  boundary, and next gate;
- `evidence.md`: UTC start/end, exact command shape, exit code, bounded safe
  stderr, source commit and hashes, schema checks, and explicit non-actions.

Validate unique JSON keys, UTF-8/LF, cross-artifact facts, secret patterns, and
SHA-256 for all three files. Record the outcome once in the canonical design
and durable handoff. Evidence remains local and untracked unless a later
explicit instruction changes that boundary.

## Archived variants

| Identity | Preserved record | Final boundary |
| --- | --- | --- |
| E22 | [transport-blocked variant](../archive/operations/api-duckdb-non-target-scratch-rehearsal-e22-2026-08-11.md) | Attempt ended before probe execution |
| E24 | [scratch-blocked variant](../archive/operations/api-duckdb-non-target-scratch-rehearsal-e24-2026-08-11.md) | Five checks passed; two were blocked |
| E26 | [scratch-blocked variant](../archive/operations/api-duckdb-non-target-scratch-rehearsal-e26-2026-08-11.md) | Six checks passed; metadata capability was blocked |

## Prohibited fallback

Do not access or mutate the current Pod, its UID-derived `emptyDir`, DuckDB or
WAL files, kubelet, containerd target tasks, Kubernetes objects, dependencies,
traffic, or production state. Do not reuse a consumed identity, invent a
fallback identity after failure, start another writer, push, deploy, or claim
that scratch evidence approves a target recovery branch.
