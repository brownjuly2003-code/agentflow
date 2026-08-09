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
| Diagnostic process | latest hold: 15/15 exits `0`, 15/15 `status=complete`, all 17 checks PASS per snapshot |
| Host / Docker memory | 8 GiB host; 6.77 GiB Docker; host swap 1.45 GiB used |
| Guest memory | latest hold: `MemAvailable=2,170,584..2,256,396 kB` (~2.070..2.152 GiB); memory `full avg10=0` |
| Disk | latest hold: 60% used; 31 GiB free |
| I/O pressure | latest hold: `full avg10=0..0.23`, non-zero in 6/15 samples |
| containerd | active since 2026-08-02; `NRestarts=0` |
| Clock | latest precise offset `-2447.147103..+38.284756 ms`; spread `2485.431859 ms` |
| Recent journal | bounded 48-hour queries returned no new clock-jump, kernel-stall, or containerd-error lines |
| 15-minute idle hold | latest instrumented repeat **FAIL** on clock-offset spread and recurring I/O full PSI; traffic remains blocked |
| Diagnostic instrumentation | live-verified bracketed clock plus 19 stable cgroup v2 CRI I/O owners |

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

### Live diagnostic smoke — 2026-08-09

At `2026-08-09T15:03:55Z`, the committed runner from `088b8ae` completed one
read-only live smoke with exit `0` and `status=complete`. All `17/17` checks
passed. The bracketed clock sample reported `offset_ns=17625662`
(`+17.625662 ms`) and `round_trip_ns=122481000` (`122.481 ms`); the emitted
values satisfy the midpoint-offset and endpoint-difference equations.

`container_io_inventory` returned `19` non-empty, uniquely identified owner
rows. Every row included pod/container identity and numeric read/write byte and
operation counters from cgroup v2; no unavailable or unsupported row was
accepted. The private artifact is
`%TEMP%\deproject-colima-smoke-20260809T150346Z\diagnostics.json`, outside the
repository. This smoke closes the instrumentation check only: the earlier
15-minute hold remains failed and was not rerun.

## Instrumented idle hold outcome — 2026-08-09

The fresh read-only hold ran from `2026-08-09T15:16:26.755Z` through
`2026-08-09T15:33:40.931Z` for `1034.175` seconds. All 15 runner invocations
exited `0`, reported `status=complete`, and passed all 17 checks. Their captured
timestamps span `1016` seconds. The private snapshots are under
`%TEMP%\deproject-colima-idle-hold-20260809T151626Z`, outside the repository.

The fail-closed verdict is
**`HOLD_FAIL_CLOCK_OFFSET_SPREAD_AND_IO_FULL_PSI`**:

- Precise clock offsets ranged from `-2447.147103` to `+38.284756 ms`, a
  `2485.431859 ms` spread against the `<=1000 ms` gate. Fourteen samples stayed
  between `-2447.147103` and `-2404.103907 ms`; sample 03 moved to
  `+38.284756 ms`, then sample 04 returned to `-2444.009873 ms`. The sampled
  host and guest clocks remained monotonic, round trips were
  `115.997..176.793 ms`, and the clock-jump journal stayed empty.
- I/O `full avg10` ranged from `0` to `0.23` and was non-zero in samples 02,
  04, 06, 09, 12, and 14. Across the complete hold, etcd had the largest
  observed write delta (`34.988 MiB`, 13,017 writes); Kafka was second
  (`9.891 MiB` written plus `2.090 MiB` read, 6,495 writes). They were also the
  two largest write deltas on every non-zero-PSI interval. This is bounded
  ownership correlation, not proof that either workload caused the PSI.
- All 19 cgroup v2 owner identities remained stable and every cumulative
  counter stayed monotonic. Memory remained green at `2.070..2.152 GiB`
  available with memory `full avg10=0`; disk remained 60% used with 31 GiB
  free.
- containerd stayed active with `NRestarts=0`. Its seven historical matching
  lines were byte-identical in all snapshots, while clock-jump and kernel-stall
  outputs remained empty.

No remediation, retry, Flink process, watcher, traffic, restart, cleanup,
resize, production transition, or push followed the failed hold.

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
  Verify: the latest instrumented repeat collected 15/15 complete snapshots
  over 1034.175 seconds, but precise clock spread failed at 2485.431859 ms.
- [x] Apply the gate appropriate to the next runtime task.
  Verify: disk <=80% and >=15 GiB free; memory full PSI remains 0; I/O full
  PSI returns to 0 during the idle hold; `MemAvailable>=1.5 GiB` for a soak
  preflight or `>=1.9 GiB` for dual-Flink restore/replay. Disk and memory
  passed; recurring non-zero I/O full PSI failed the stability gate.
- [x] Implement precise clock and cgroup-aware I/O owner diagnostics.
  Verify: capability evidence identifies the PID-selection root cause; TDD RED
  fails both new contracts; focused tests, lint, format, compile, and help
  smoke pass after implementation.
- [x] If the hold fails, inventory only the failing surface before mutation.
  Verify: I/O failure has a bounded Docker/storage owner list; memory failure
  has a measured deficit; clock failure has timestamped host/guest samples.
  Do not prune, restart, resize, or stop protected workloads during inventory.
  The first bounded I/O sampler could not map the 19 CRI containers, but the
  corrected live smoke returned 19 unique cgroup v2 owner rows and a precise
  timestamped clock pair without mutation.
- [ ] Perform one authorized remediation, then repeat the same hold.
  Verify: the selected gate is green before traffic. A larger host is required
  when the 1.9 GiB restore threshold cannot be sustained safely; a controlled
  Colima restart requires a separate runtime gate and rollback record.
  The instrumented repeat still failed clock and I/O gates; no subsequent
  remediation was selected or performed.
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
2. Treat the instrumented hold above as the current runtime result. Preserve
   both raw temp bundles and do not repeat the smoke or hold without a narrowed
   hypothesis and a selected remediation.
3. In the next separate read-only diagnostic slice, inspect the host/guest time
   synchronization path around the sample-03 `+2.472 s` offset excursion. Do
   not restart or resize Colima and do not change time settings in that slice.
4. Keep the recurring I/O full PSI gate open. The current data bounds etcd and
   Kafka as the largest writers but does not prove causation; any remediation
   and subsequent hold require separate scoped decisions.
5. Keep the watcher, Flink process, traffic, and production acceptance blocked
   until a later complete hold is green.
