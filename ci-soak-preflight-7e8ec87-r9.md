# CI-soak exact-HEAD r9 preflight plan

## Goal

Prove, without starting the controller or stopping any co-tenant, that a fresh
snapshot of exact source HEAD `7e8ec87c25bbdc8f8aa58c116ded9914470789cb`
is ready for a later separately authorized rehearsal on the active Mac Colima
runtime.

## Fixed identities

- Attempt: `ci-soak-7e8ec87-r9-preflight`
- Snapshot: `/Users/julia/agentflow-fc5-7113966/ci-soak-rehearsal-7e8ec87-r9`
- Compose project: `agentflow-ci-soak-7e8ec87-r9`
- Output: `.artifacts/soak-rehearsal-2000-7e8ec87-r9` under the snapshot
- Docker socket: `unix:///Users/julia/.colima/agentflow-fc5-7113966/docker.sock`

## Contract

- [x] Run the complete local architecture gate once at the exact source HEAD.
- [x] Build a fresh Git archive, wrapper, snapshot, project, output, probe, and
      evidence identity; validate their hashes and shell syntax before upload.
- [x] Execute the preflight-only wrapper under the terminal rule below. It may
      create the fresh snapshot,
      evidence directory, empty output directory, short-lived read-only probe
      containers, and owner lock; its trap must remove probes and release the
      lock.
- [x] Require the four protected running co-tenants by exact ID, name, labels,
      restart count, ports, and health where defined. Require the stopped old
      ClickHouse rollback ID to remain exited cleanly and disconnected.
- [x] Prove ClickHouse from container health, macOS loopback, and the exact Kind
      workload route. Require zero candidate project resources, zero probes,
      empty output, and an unchanged Mac checkout before and after.
- [x] Perform one independent postflight, record immutable evidence hashes, and
      update durable local handoff material.

## Exclusions

No controller, stop command, traffic, rehearsal, soak, rollback execution,
co-tenant mutation, repository fetch/push, or reuse of any r8 identity is
authorized by this slice.

## Terminal rule

Any identity, route, hash, cleanup, or ownership mismatch fails closed. One
narrowed diagnostic correction and re-run is the maximum allowed after a
failed or timed-out verification; otherwise record the blocker and yield.

## Outcome

The exact-HEAD gate returned
`ARCHITECTURE_READY=PASS blockers=0 head=7e8ec87c25bbdc8f8aa58c116ded9914470789cb`.
The first wrapper invocation failed before extraction, evidence creation,
Docker access, or probe creation because its archive path retained the r8
basename. The trap reported `archive_missing` and lock release PASS. One
one-line path correction was validated locally and on macOS; the single
allowed rerun then returned `PREFLIGHT_RESULT=PASS`.

The exact archive and final wrapper SHA-256 values are
`f52f4587f8db5a2d53876caf0c847c6a8093edff9da0b46f1d3d2d42e43df1a1`
and `0bc8edda7a2e933a690c32bb3956353668e417cfea396301c163f30daca0a68e`.
All three ClickHouse viewpoints returned PASS. Independent postflight found
project resources `0/0/0`, zero probes, empty output, no owner lock, unchanged
protected identities, and the unchanged Mac checkout. This is preflight
evidence only; it does not authorize or establish a rehearsal.

## Next-session resume contract

### Identity map

| Role | Exact identity |
| --- | --- |
| Tracked r9 evidence commit | `74915e7ccc85176b6bd004ad79b21b1ce5eb0db3` |
| Executed source and architecture-gate HEAD | `7e8ec87c25bbdc8f8aa58c116ded9914470789cb` |
| Unchanged Mac checkout | `ae9fb69db7de737b469f868f218e8d623c206959` |
| Successful preflight attempt | `ci-soak-7e8ec87-r9-preflight` |
| Reserved snapshot/project | `/Users/julia/agentflow-fc5-7113966/ci-soak-rehearsal-7e8ec87-r9` / `agentflow-ci-soak-7e8ec87-r9` |

A later docs-only commit may move the local checkout beyond `74915e7`. Never
substitute that newer documentation HEAD for the executed source/gate HEAD or
rebuild the already verified r9 snapshot from it.

### State classification

Completed: exact-HEAD local gate, archive transfer, corrected preflight, three
ClickHouse viewpoints, independent postflight, evidence capture, and cleanup.
The reserved project still has zero containers/networks/volumes, the reserved
output is empty, and no owner lock remains.

Not executed: co-tenant stop, controller, `--count 2000` rehearsal, traffic
beyond read-only probes, soak, rollback, production action, fetch, or push.
The preflight authorization and its one corrective rerun are consumed; they
must not be treated as standing permission for a later runtime action.

### Required start in the next session

1. Read only: run `git status --short --branch` and `git rev-parse HEAD`, then
   read the first `AGENT_STATE.md` block and this section.
2. Require a clean tracked tree/index and preserve every established untracked
   path. Do not fetch, clean, rebuild, or touch the Mac runtime during recovery.
3. Treat a generic continuation request as permission to recover context, not
   as permission to start the controller or stop co-tenants. There is no
   remaining independent local implementation item in this r9 slice.
4. Before a rehearsal, obtain fresh explicit authorization naming the r9
   snapshot/project/output and covering one `--count 2000` controller run plus
   temporary identity-bound stop and restoration of the four running
   co-tenants.

The four running identities that must be revalidated and restored by exact ID
are MinIO `f51db9e3ee0715bbfc91c2a715a4fc114f80fdbe82e156e89db74626b729aa42`,
Iceberg REST `1e80588ca8fb0859934ada5635731027ca6692d9db597105504b1f7c2d761211`,
ClickHouse `f0f0b82817bb87ec522f16426795df021e8d249fdc0c07a9474ac34717488c61`,
and Kind `0545702c4bc4ffdb5402b324af5dd51af71bed57ca7078707c931eae8aee365b`.
Old ClickHouse `a8cc630eedb5d116d605449771ea080c400ced742dc0540c44225897330c15b9`
must remain stopped, clean-exited, disconnected, and preserved for rollback.

Even with rehearsal authorization, full soak, rollback execution, deletion of
the old ClickHouse/backup/evidence, production work, and push remain separate
boundaries.
