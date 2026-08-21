# CI-soak next-session runbook

**Updated:** 2026-08-21

**Purpose:** one unambiguous entry point for resuming the CI-soak work without
repeating completed local work or reusing consumed runtime evidence.

Live repository facts from the commands below override copied chat context and
older status sections. This runbook records the operational boundary; it does
not authorize an external action.

## Status at a glance

| Surface | Exact state |
| --- | --- |
| Closing implementation commit | `726d171322dc8933d8788e7388f1bcd5d0d8e32e` — `fix(ops): reconcile ci soak verifier contract` |
| Required ancestry | The current `HEAD` must contain the closing implementation commit before any post-fix validation |
| Local architecture gate | `ARCHITECTURE_READY=PASS blockers=0 head=726d171322dc8933d8788e7388f1bcd5d0d8e32e` |
| Local verification | Focused gate: `129 passed`; Ruff check/format, `py_compile`, `git diff --check`, strict UTF-8/LF/no-BOM/no-NUL, and the clean-HEAD architecture gate passed |
| Post-fix external rehearsal | **Not run** |
| Last external evidence | Retained r9 attempt: **FAIL** against older source `7e8ec87c25bbdc8f8aa58c116ded9914470789cb` |
| Push/fetch | Neither was performed for the closing slice; push remains unauthorized |

The local correction is closed. Counts below `1_440_000` use
`canary` / `kind_residual_20`; the exact full-soak count uses
`soak` / `dual_mean_90`. The controller starts and identity-checks a named
verifier before producer traffic, waits for stable producer-final evidence,
and then delegates to the byte-pinned verifier. The same exact verifier ID,
labels, name, restart count, terminal state, exit code, logs, phase-specific
JSON, and cleanup/no-replacement state are checked fail-closed.

This is local contract evidence only. It does not prove current
Docker/Colima, Kind, Flink, ClickHouse, Iceberg, or MinIO behavior.

## Source-of-truth order

Use this order when sources disagree:

1. Current `git status`, `git rev-parse HEAD`, and commit ancestry.
2. The first handoff block in local `AGENT_STATE.md`, when that ignored file is
   present.
3. This tracked runbook for the resume sequence and authorization boundary.
4. [`ci-soak-runtime-harness.md`](../../ci-soak-runtime-harness.md) for the
   accumulated harness history and detailed contracts.
5. The immutable
   [r9 rehearsal report](../../ci-soak-r9-rehearsal-20260821-01.md) and
   [r1-r7 architecture audit](../../ci-soak-r1-r7-architecture-audit.md) for
   historical evidence.

`docs/SESSION_HANDOFF.md` is an ignored local mirror. It is useful on this
machine, but it must not override current Git facts or this tracked boundary.

## Cold-start sequence

Run only these read-only checks before selecting work:

```powershell
git status --short --branch
git rev-parse HEAD
git merge-base --is-ancestor 726d171322dc8933d8788e7388f1bcd5d0d8e32e HEAD
```

The ancestry command must exit `0`. Then:

1. Read the first block of `AGENT_STATE.md`, if present, and this runbook.
2. Treat every pre-existing untracked or ignored path as protected user state.
   Never bulk-stage with `git add .` or `git add -A`.
3. If tracked files are unexpectedly dirty, stop before editing overlapping
   files and identify their owner and scope.
4. Do not rerun the 129-test focused gate, the architecture gate, or an
   external rehearsal merely to refresh timestamps. Repeat a gate only for a
   new relevant change, a fresh failure, or a newly authorized exact-HEAD
   attempt.
5. The next actionable runtime slice is at most one fresh post-fix
   `--count 2000` rehearsal, and only after fresh explicit authorization.

If a new local change legitimately requires the architecture gate, run it from
a clean tracked checkout:

```powershell
python scripts/golden_soak/architecture_gate.py
```

Require one exact terminal line with the current 40-character `HEAD`. A PASS
does not authorize runtime work.

## Consumed r9 evidence — never reuse or clean

| Identity | Consumed value |
| --- | --- |
| Attempt | `ci-soak-7e8ec87-r9-rehearsal-20260821-01` |
| Source/gate HEAD | `7e8ec87c25bbdc8f8aa58c116ded9914470789cb` |
| Snapshot | `/Users/julia/agentflow-fc5-7113966/ci-soak-rehearsal-7e8ec87-r9` |
| Compose project | `agentflow-ci-soak-7e8ec87-r9` |
| Output | `.artifacts/soak-rehearsal-2000-7e8ec87-r9` under the snapshot |
| Result | `FAIL`: producer delivered `2000/2000`; the old sequential `dual_mean_90` verification failed closed |

The snapshot, project, output, wrapper, and attempt names are immutable failure
evidence. Do not rerun the controller from them, overwrite them, or remove
them. Do not weaken the `90 eps` full-soak floor to make a short rehearsal
pass.

## Historical runtime safety snapshot

These identities were healthy after the r9 postflight, but they are historical
observations, not standing authority for a later mutation:

| Surface | Last recorded identity/state |
| --- | --- |
| MinIO | `f51db9e3ee0715bbfc91c2a715a4fc114f80fdbe82e156e89db74626b729aa42` |
| Iceberg REST | `1e80588ca8fb0859934ada5635731027ca6692d9db597105504b1f7c2d761211` |
| Current ClickHouse | `f0f0b82817bb87ec522f16426795df021e8d249fdc0c07a9474ac34717488c61` |
| Kind | `0545702c4bc4ffdb5402b324af5dd51af71bed57ca7078707c931eae8aee365b` |
| Old rollback ClickHouse | `a8cc630eedb5d116d605449771ea080c400ced742dc0540c44225897330c15b9`; exited and disconnected |
| Mac checkout | `ae9fb69db7de737b469f868f218e8d623c206959` |

Revalidate every identity, restart count, readiness endpoint, network
attachment, owner lock, and Mac checkout state in a fresh preflight before any
authorized stop or mutation. A mismatch is new input and closes the mutation
gate; do not silently substitute a new container.

## Authorization boundary

| Action | Current boundary |
| --- | --- |
| Read local status and tracked docs | Allowed as read-only inspection |
| Run local checks after a relevant local change | Allowed within that scoped change; avoid evidence-refresh repeats |
| SSH, Docker/Colima inspection, or creation of a fresh Mac snapshot | Requires explicit authorization for the new external slice |
| Stop or restore protected co-tenants; run `--count 2000` traffic | Requires the same fresh, bounded rehearsal authorization and a green preflight |
| Reuse, rerun, overwrite, or clean r9 evidence | Forbidden |
| Full soak, rollback exercise, retained-evidence cleanup, production action | Separate future authorization required |
| Fetch or push | Not authorized |

Authorization for one item does not imply authorization for the next row.
Project-scoped fail-closed cleanup and exact protected-co-tenant restoration are
mandatory parts of any newly authorized rehearsal; cleanup of retained r9 or
unrelated resources is outside that scope.

## Requirements for one future post-fix rehearsal

Before the first mutation, require and preserve:

1. A clean tracked checkout whose exact `HEAD` contains
   `726d171322dc8933d8788e7388f1bcd5d0d8e32e`, plus an exact-HEAD
   architecture-gate PASS.
2. A new archive whose source and critical-file hashes match that exact HEAD.
3. Fresh snapshot, Compose project, output, wrapper, and attempt identities;
   prove all are absent before creation.
4. Current Docker context, capacity, bind visibility, ports, and Compose config.
5. Current exact protected-container IDs, restart counts, network attachments,
   health/API checks, Mac checkout identity, and an exclusive owner lock.
6. One controller invocation with `--count 2000`; no raw retry after a failure.
7. Terminal wrapper/controller results, runtime state, component logs,
   phase-specific JSON, exact verifier identity/exit evidence, and hashes.
8. Zero candidate containers, networks, volumes, runtime directories, or owner
   locks after exit, plus exact restoration and readiness of every protected
   co-tenant.

Classify the result exactly as emitted. A failed rehearsal remains useful
evidence; preserve it and stop. A passing short rehearsal closes only the
capacity-independent rehearsal gate, not the full soak, rollback, production,
or push gates.

## Detailed references

- [Golden-soak source-pack README](../../scripts/golden_soak/README.md)
- [Runtime harness history](../../ci-soak-runtime-harness.md)
- [Immutable r9 failure report](../../ci-soak-r9-rehearsal-20260821-01.md)
- [Architecture audit and readiness contract](../../ci-soak-r1-r7-architecture-audit.md)
- [Compose foundation context](ci-soak-compose-foundation.md)
