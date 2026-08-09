# Colima runtime stabilization

Last updated: 2026-08-09.

## Goal

Prove a stable Colima/kind baseline before any new traffic, then use the
smallest evidence-backed remediation if the hold fails.

## Current evidence

Baseline captured read-only on 2026-08-09 after runner commit `895e660`;
remediation measurements were added after the scoped Kafka rollout:

| Signal | Current result |
| --- | --- |
| Diagnostic process | `RUNNER_EXIT=0`, `status=complete`, all 16 checks PASS |
| Host / Docker memory | 8 GiB host; 6.77 GiB Docker; host swap 1.45 GiB used |
| Guest memory | Before: `MemAvailable=1,603,104 kB` (~1.53 GiB); after Kafka cap: `2,393,824 kB` (~2.28 GiB) |
| Disk | 59% used; 31 GiB free |
| I/O pressure | `some avg10=8.37`, `full avg10=1.73` |
| containerd | active since 2026-08-02; `NRestarts=0` |
| Clock | five samples held guest-host delta at exactly -2 seconds |
| Recent journal | bounded 48-hour queries returned no new clock-jump, kernel-stall, or containerd-error lines |

The empty recent-journal queries do not invalidate the historical soak RCA;
older failure evidence remains authoritative. The memory gate is green after
the heap cap; idle I/O full pressure still needs the 15-minute hold. There is
no current containerd exit signal.

## Memory ownership and remediation

The active project stack owned the pressure; there was no unrelated service
that could be stopped without removing part of the golden path. Before the
change, Kafka was the largest tunable workload at ~1.095 GB and had no JVM
heap setting in the kind scaffold. The Flink JobManager and TaskManager were
not running yet and are configured for 896 MiB each.

The kind Kafka heap now matches the existing Docker E2E setting:
`-Xms256m -Xmx512m`. The scoped rollout on context
`kind-agentflow-reverify-ed03fc47` preserved `/var/agentflow-kafka-kraft`, the
four project topics, and `__consumer_offsets`. Kafka working memory fell to
462.6 MB, reclaiming about 632 MB, and the guest memory gate rose above
1.9 GiB. All five project pods returned to `Running`; the lake materializer
recovered after one Kafka-induced restart.

## Tasks

- [x] Run `scripts/diagnose_colima_runtime.py --timeout-seconds 30` once.
  Verify: exit `0`, `status=complete`, every check PASS.
- [x] Sample five host/guest clock pairs over ten seconds.
  Verify: no backward step; delta stayed at `-2` for all five samples.
- [x] Cap the kind Kafka JVM heap at 512 MiB and perform one scoped rollout.
  Verify: contract test first failed on the missing setting, then all eight
  Kafka scaffold tests passed; Deployment became available; Kafka used
  462.6 MB; all previously present topics remained present.
- [ ] Run a 15-minute idle hold with one private JSON snapshot per minute
  outside the repository.
  Verify: all 15 runs exit `0`; no new clock/stall/error lines; clock-delta
  spread <=1 second.
- [ ] Apply the gate appropriate to the next runtime task.
  Verify: disk <=80% and >=15 GiB free; memory full PSI remains 0; I/O full
  PSI returns to 0 during the idle hold; `MemAvailable>=1.5 GiB` for a soak
  preflight or `>=1.9 GiB` for dual-Flink restore/replay.
- [ ] If the hold fails, inventory only the failing surface before mutation.
  Verify: I/O failure has a bounded Docker/storage owner list; memory failure
  has a measured deficit; clock failure has timestamped host/guest samples.
  Do not prune, restart, resize, or stop protected workloads during inventory.
- [ ] Perform one authorized remediation, then repeat the same hold.
  Verify: the selected gate is green before traffic. A larger host is required
  when the 1.9 GiB restore threshold cannot be sustained safely; a controlled
  Colima restart requires a separate runtime gate and rollback record.
- [ ] Before any future soak, launch the Flink failure-evidence watcher to a
  new host-persistent directory and wait for `state=armed`.
  Verify: watcher armed, task readiness/checkpoints green, and no consumed
  identity `-01` through `-05` is reused.

## Done When

- [ ] A 15-minute idle hold passes the clock, memory, I/O, disk, Docker, and
  containerd conditions for the named runtime task.
- [x] Any remediation is recorded with before/after evidence and rollback.
- [ ] Traffic remains blocked until both the stabilization gate and the
  failure-evidence watcher prerequisite are green.

## Boundary

This slice starts no traffic or Flink runtime. Its only cluster mutation was
the scoped Kafka heap rollout; it performs no Colima restart, Docker cleanup,
production transition, or push.

## Next-session resume

1. Read the latest authoritative sections at the end of `AGENT_STATE.md` and
   `docs/SESSION_HANDOFF.md`; they supersede older capacity-blocked summaries.
2. Treat `e9f76f9` as the implementation baseline. The following docs-only
   handoff commit does not change the runtime or product code.
3. Run the pending 15-minute idle hold. Do not start Flink traffic until the
   complete hold and the failure-evidence watcher prerequisites are green.
4. If the hold is green, arm the watcher in a new host-persistent directory;
   only then resume the named full-process launch with a fresh identity.
