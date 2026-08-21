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
