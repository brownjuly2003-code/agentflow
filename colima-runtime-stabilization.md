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
| 15-minute idle hold | **FAIL** on clock-delta spread and recurring I/O full PSI; traffic remained blocked |
| Diagnostic instrumentation | bracketed nanosecond clock plus cgroup v1/v2 CRI I/O ownership implemented and locally verified |

The empty recent-journal queries do not invalidate the historical soak RCA;
older failure evidence remains authoritative. The memory gate is green after
the heap cap. The idle hold below supersedes the prior pending-hold state and
did not clear the clock or I/O gates. There is no current containerd exit
signal.

## Idle hold outcome — 2026-08-09

The single scheduled hold ran from `2026-08-09T13:45:56Z` through
`2026-08-09T14:01:44Z` for `948.105` seconds. All 15 per-minute diagnostic
runs exited `0`, reported `status=complete`, and wrote separate JSON snapshots
under the private Windows temp directory
`%TEMP%\deproject-colima-idle-hold-20260809T134556Z`. The snapshots are outside
the repository and were not staged.

The stabilization verdict is
**`HOLD_FAIL_CLOCK_SPREAD_AND_IO_FULL_PSI`**:

- Guest-host clock deltas ranged from `-3` to `0` seconds, a `3`-second spread
  against the required maximum of `1` second. Neither clock moved backwards,
  and the bounded clock-jump journal query stayed empty.
- Memory remained green: `MemAvailable` ranged from `2.16` to `2.25 GiB` and
  memory `full avg10` remained `0` in all 15 snapshots.
- Disk remained green at `60%` used with `31G` available.
- I/O `full avg10` ranged from `0` to `4.89`. It first reached `0` in samples
  6 and 7, then became non-zero again in samples 8, 11, 13, and 14 before
  ending at `0`; the idle-I/O gate therefore was not stable for the hold.
- containerd stayed active with `NRestarts=0`. Clock and kernel journal
  outputs remained empty. The same seven containerd journal lines, with the
  same SHA-256
  `f7bf4531111ea8f7842ff64f46a944694ab1fcc8389b414d035358467c608f90`,
  appeared in every snapshot, so no new matching line appeared during the
  hold.
- A bounded follow-up enumerated 19 running CRI containers, but the attempted
  PID/cgroup `io.stat` mapping returned `0/19` usable samples. No raw retry or
  runtime mutation followed; I/O ownership remains unresolved.

No Flink process, watcher, traffic, restart, cleanup, Colima resize, production
transition, or push was started. The next separate slice must make the
clock-pair and cgroup-mode-aware I/O owner diagnostics reliable before another
hold is attempted.

## Diagnostic instrumentation follow-up — 2026-08-09

One owner-authorized, read-only capability probe established the runtime
interfaces before implementation:

- macOS host `python3 time.time_ns()` and guest `date +%s%N` both returned
  nanosecond timestamps; the bracketed sample round trip was `259,220,000 ns`.
- The guest uses `cgroup2fs`; PID 1 belongs to `/init.scope`.
- `crictl inspect` supports `go-template`. Its JSON contained a nested PID `1`
  before the actual runtime PID `84724`, proving why the earlier first-match
  `sed` parser selected the wrong process and returned `0/19` owners.

`scripts/diagnose_colima_runtime.py` now brackets the guest timestamp with
host nanosecond samples and emits `offset_ns` plus `round_trip_ns`. Its new
`container_io_inventory` check reads the exact `.info.pid`, pod, and container
name through `go-template`, then reports cumulative read/write bytes and I/O
counts from cgroup v2 `io.stat` or cgroup v1 `blkio` counters. Missing or
unsupported evidence fails the check instead of producing a false complete
inventory.

TDD RED was `2 failed, 4 passed`; focused GREEN was `6 passed in 0.82s`.
Ruff check, Ruff format check, Python compilation, CLI help smoke, and diff
checks passed. This implementation slice did not run the updated runner against
the live stand and did not repeat the 15-minute hold.

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
- [x] Run a 15-minute idle hold with one private JSON snapshot per minute
  outside the repository.
  Verify: all 15 runs exit `0`; no new clock/stall/error lines; clock-delta
  spread <=1 second. All runs exited `0`, but the clock spread failed at
  `3` seconds.
- [x] Apply the gate appropriate to the next runtime task.
  Verify: disk <=80% and >=15 GiB free; memory full PSI remains 0; I/O full
  PSI returns to 0 during the idle hold; `MemAvailable>=1.5 GiB` for a soak
  preflight or `>=1.9 GiB` for dual-Flink restore/replay. Disk and memory
  passed; recurring non-zero I/O full PSI failed the stability gate.
- [x] Implement precise clock and cgroup-aware I/O owner diagnostics.
  Verify: capability evidence identifies the PID-selection root cause; TDD RED
  fails both new contracts; focused tests, lint, format, compile, and help
  smoke pass after implementation.
- [ ] If the hold fails, inventory only the failing surface before mutation.
  Verify: I/O failure has a bounded Docker/storage owner list; memory failure
  has a measured deficit; clock failure has timestamped host/guest samples.
  Do not prune, restart, resize, or stop protected workloads during inventory.
  The clock samples are preserved, but the first bounded I/O sampler could
  not map the 19 CRI containers to usable cgroup statistics. Corrected
  instrumentation is locally verified; fresh live owner output remains
  pending.
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
3. Treat the `2026-08-09` hold as failed; do not raw-retry it. Run one fresh
   read-only smoke of the updated diagnostic runner to a new private temp path.
   Require `status=complete`, precise clock fields, and non-empty CRI I/O rows.
4. In a later runtime slice, run one fresh complete hold and evaluate clock
   offset spread plus per-owner I/O deltas. Only after that hold is green, arm
   the watcher in a new host-persistent directory and resume the named process
   with a fresh identity.
