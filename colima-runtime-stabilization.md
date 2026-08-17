# Colima runtime stabilization

Last updated: 2026-08-17.

## Goal

Prove a stable Colima/kind baseline before any new traffic, then use the
smallest evidence-backed remediation if the hold fails.

## Latest authorized workload CrashLoop RCA - 2026-08-17

One authorized immutable read-only CrashLoop RCA capture ran exactly once
through `.grok-prompts/workload-crashloop-rca-20260817-grok01.py` (route
`local_grok_cli`; requested model `grok-4.5`; actual model not claimed).
Evidence directory:
`.codex-grok-tasks/workload-crashloop-rca-20260817-grok01/`.
UTC bounds `2026-08-17T17:23:30Z` → `2026-08-17T17:23:40Z`. Process exit `0`,
`overall_status=complete`, `retries=0`, `runtime_mutation_performed=false`.
All 12 remote checks passed; no truncation, redaction, withheld payload, or
failed check.

| Signal | Result |
| --- | --- |
| Capture completeness | **`complete`** (not readiness / stability / soak / production) |
| Overall RCA class | **`ROOT_CAUSE_PROVEN`** |
| API | CrashLoopBackOff restarts `1610` (Δ`+19`); **PROVEN** DuckDB WAL replay InternalException on `/data/agentflow_fresh_20260807.duckdb.wal` |
| Bridge | CrashLoopBackOff restarts `113` (Δ`+19`); **PROVEN** ClickHouse connection refused; host CH `exited` exit `255` |
| Lake materializer | CrashLoopBackOff restarts `140` (Δ`+19`); **PROVEN** Iceberg REST `:8181` refused; host Iceberg REST `exited` exit `255` |
| Redis / Kafka | Ready; restart Δ `0`; logs skipped as not necessary |
| ClickHouse / Iceberg REST / MinIO | Host containers exited exit `255` ~`14:59:43Z` (lifecycle only; stop-reason beyond exit code not proved) |
| MinIO-init | exited exit `0` (historical successful init) |
| Remediation / production | **not authorized** / **not ready** |

Capture completeness must not be read as workload ready, clock stable,
idle-I/O stable, soak passed, or production ready. No second invocation,
mutation, recovery, traffic, Flink, watcher, hold, deployment, production
transition, commit, or push occurred. Any remediation requires fresh exact
authorization. Analysis artifacts: `result.json`, `result.md`, `evidence.md`
beside runner-owned `capture.json` / `capture-result.json`.

## Follow-up external exit-255 forensics - 2026-08-17

Local saved-evidence forensics, with no new Mac access, classifies the shared
dependency failure as **`STRONGLY_CORROBORATED_OPERATIONAL_CAUSE`**. The target
Colima profile and Docker socket were already unavailable at `14:51Z` and
again at `14:58:08Z`, before the one authorized start began at `14:58:26Z`.

During the subsequent boot, Docker recorded ClickHouse, Iceberg REST, and
MinIO as exit `255` within 19 ms at approximately `14:59:43Z`. Moby's restore
path uses exit `255` when a container persisted as running has no surviving
task or retained exit status; without an exit timestamp, `FinishedAt` is set
to reconciliation time. Therefore `14:59:43Z` is not the original stop time
and `255` is not an application exit from the three services.

Their non-recovery is **proved**: all three had effective restart policy `no`
and restart count `0`. Docker therefore recovered neither service after the
VM/daemon returned, while kind/Kubernetes performed their own reconciliation.

The initiating event remains **not proved**. Saved evidence cannot distinguish
manual Colima stop, macOS reboot/shutdown, power loss, VM crash, or another
host-level event before `14:51Z`. Docker records `OOMKilled=false`, but the
lost task/exit status does not exclude an unrecorded event or host/VM-level
pressure. Determining that trigger requires a separately authorized read-only
collection of retained Lima/serial, macOS unified, and prior-boot Docker logs.
No restart, recovery, runtime mutation, or production transition was
authorized or performed. Evidence:
`.codex-grok-tasks/external-exit255-forensics-20260817-codex01/`.

## Latest authorized post-start read-only snapshot - 2026-08-17

One authorized bounded read-only post-start status/diagnostic/workload snapshot
ran exactly once through the immutable local runner
`.grok-prompts/mac-readonly-poststart-20260817-grok01.py` (local Grok CLI;
requested model `grok-4.5`). Evidence directory:
`.codex-grok-tasks/mac-readonly-poststart-20260817-grok01/`.
UTC bounds `2026-08-17T15:45:23Z` → `2026-08-17T15:45:51Z`. Process exit `0`,
`overall_status=complete`, `retries=0`, `runtime_mutation_performed=false`.

| Signal | Result |
| --- | --- |
| Capture completeness | **`complete`** (not readiness/stability/soak/production) |
| Diagnostic | **`complete`**, `returncode=0`, `timed_out=false`, `24951 ms` |
| Colima profile | running: `agentflow-fc5-7113966` |
| kind node | `agentflow-reverify-ed03fc47-control-plane` `Ready` |
| docker_info | PASS (was timeout in the ~15:05Z post-start partial) |
| Clock sample | `offset_ns=26122525` (single sample only; 12-sample gate not run) |
| Guest PSI sample | `some avg10=8.58`, `full avg10=7.98` |
| API / bridge / lake | `CrashLoopBackOff` restarts `1591` / `94` / `121`; not Ready |
| Redis | `1/1 Running` Ready; endpoint `10.244.0.13:6379` |
| Kafka | `1/1 Running` Ready; endpoints `10.244.0.9:9092,10.244.0.9:29093` |
| API endpoints | empty |

Compared with the prior same-day post-start snapshot (~15:05Z), diagnostic
capture moved from `partial` to `complete`, Kafka became Ready with endpoints,
and API/bridge/lake remained not Ready with higher restart counts. No causality
is claimed. No second invocation, mutation, recovery, traffic, Flink, watcher,
clock gate, hold, deployment, production transition, or push occurred.

Artifact SHA-256 from `result.json`: `diagnostics.json`
`14AA0ABADC375292D5123B265EC4528338FCE0E903780E5CBBF764A1E008A580`;
`diagnostics.raw.json`
`C88CDB17C64C0DB33BA944237FC0009D2AADA3343B35E7EBE0696844B42D1141`;
`workload-snapshot.json`
`DB9908BE9B971D68A2B12BDD53621DB87DB5E56727A019B6B64E19997E8DE8EF`.
`result.json` self-hash is independently verified by Codex later.

## Latest read-only Mac snapshot - 2026-08-17

A fresh bounded read-only diagnostic snapshot was captured through SSH alias
`deproject-mac` at `2026-08-17T14:51:19Z` and written locally to
`.codex-grok-tasks/mac-readonly-baseline-20260817-codex01/diagnostics.json`.
It did not start Colima, query target DuckDB bytes, mutate Kubernetes, launch
traffic, arm the watcher, run a hold, or push.

| Signal | Result |
| --- | --- |
| Overall diagnostic status | **`partial`** |
| Host reachability | PASS; host time query returned `2026-08-17T14:51:11Z` |
| Host memory | PASS; host RAM `8589934592` bytes; swap `844 MiB` used |
| Colima profile | **not running**: `colima [profile=agentflow-fc5-7113966] is not running` |
| Docker socket | unavailable: `/Users/julia/.colima/agentflow-fc5-7113966/docker.sock` missing |
| kind node / guest checks | no node name returned; guest checks were not run |

This supersedes only live availability assumptions. It does not invalidate the
historical 2026-08-09 RCA or mark any clock, I/O, workload, watcher, Flink,
traffic, soak, rollback, or production gate green. Before any future Mac
runtime slice, Colima availability is now a separate fail-closed prerequisite.

## Authorized Colima start - 2026-08-17

After the user authorized launches, one bounded start of the existing Mac
profile was attempted through SSH alias `deproject-mac`. Evidence is stored
locally under `.codex-grok-tasks/mac-colima-start-20260817-codex01/`.

Pre-start evidence at `2026-08-17T14:58:08Z` showed no matching Colima/Lima
process, `colima [profile=agentflow-fc5-7113966] is not running`, and both the
current profile config and rollback backup at SHA-256
`e1abf039d7a563038d28bff9c6124b0344a9b90c1a2ac4b3e7e708351e9599af`. This
means the live config matched the historical rollback/original config, not the
previously documented option-A applied config hash.

The single `colima --profile agentflow-fc5-7113966 start` began at
`2026-08-17T14:58:26Z` and reached `start_rc=0` at
`2026-08-17T15:03:10Z`. Post-start status reported the profile running under
macOS Virtualization.Framework with Docker socket
`/Users/julia/.colima/agentflow-fc5-7113966/docker.sock`. The local wrapper
process exited `255` only because the final Bash `exit` consumed a CRLF-tainted
`0`; the transcript's Colima result and immediate status are authoritative.

The post-start diagnostic snapshot at `2026-08-17T15:05:14Z` remained
`partial`, not complete: host time, host memory, Colima status, kind node,
guest clock, guest memory, guest disk, containerd active state, and log scans
were captured, but `docker_info` timed out and the guest I/O pressure sample was
already saturated (`some avg10=99.60`, `full avg10=91.80`). The kind node was
`agentflow-reverify-ed03fc47-control-plane`; single-sample clock offset was
`151670054 ns`, but the required 12-sample clock gate was not run.

A read-only Kubernetes snapshot at `2026-08-17T15:05:46Z` showed the node
`Ready`, but the AgentFlow workload was not recovered: API was
`CrashLoopBackOff` with restart count `1581`, bridge was `Error` at restart
count `85`, lake materializer was `CrashLoopBackOff` at restart count `111`,
Redis was `Running` and Ready, and Kafka was `Running` but `0/1` Ready. API and
Kafka service endpoints were empty.

No restart, config edit, rollback, workload/dependency recovery command, pod
exec, traffic, Flink launch, watcher, hold, production transition, or push
occurred in this slice. Treat Colima availability as restored but runtime
stability and workload readiness as still blocked by follow-up diagnostics.

## Current evidence

Historical baseline captured read-only on 2026-08-09 after runner commit `895e660`;
remediation measurements were added after the scoped Kafka rollout:

| Signal | Current result |
| --- | --- |
| Diagnostic process | latest hold: 15/15 exits `0`, 15/15 `status=complete`, all 17 checks PASS per snapshot |
| Host / Docker memory | 8 GiB host; 6.77 GiB Docker; host swap 1.45 GiB used |
| Guest memory | latest hold: `MemAvailable=2,170,584..2,256,396 kB` (~2.070..2.152 GiB); memory `full avg10=0` |
| Disk | latest hold: 60% used; 31 GiB free |
| I/O pressure | latest hold: `full avg10=0..0.23`, non-zero in 6/15 samples |
| containerd | active since 2026-08-02; `NRestarts=0` |
| Clock | option A selected: Lima/macOS host authority; current host/NTP precheck FAIL at `-2.470866 +/- 0.006419 s`; no remediation applied |
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

## Clock synchronization root cause — 2026-08-09

A bounded read-only follow-up isolated the clock failure without changing time
settings or restarting Colima:

- The Colima VM and kind node have the same boot ID
  (`2b4f1010-adc0-4eb3-8318-d37d57ada761`), the same time namespace
  (`time:[4026531834]`), zero time-namespace offsets, and the same `hpet`
  clocksource. The kind node therefore has no independent clock to remediate.
- Colima `0.10.1` is using Lima `2.1.1`. During the exact hold window,
  `lima-guestagent` logged a successful host-time adjustment about every ten
  seconds, almost always from a guest-minus-host drift near `-2.45 s`.
  Both services stayed active; `systemd-timesyncd` reported `NRestarts=0`.
- `systemd-timesyncd` was also active, NTP-synchronized to
  `185.125.190.58 (ntp.ubuntu.com)`, and reported `Offset=-2.465089 s`,
  `Delay=7.130 ms`, `Jitter=6.401 ms`, and `PacketCount=56908`. Its service
  lifetime makes that packet count approximately one request per 11 seconds,
  consistent with the external ten-second clock-change cadence rather than
  the displayed 32-second normal poll interval alone.
- The Lima `2.1.1` host agent calls `SyncTime` every ten seconds with
  `time.Now()`; the guest agent measures `guest_now - host_time` and, outside
  a 100 ms threshold, calls `SetSystemTime(host_time)`. The systemd `v255`
  implementation watches for an external clock change and immediately sends
  a new NTP request. Its displayed offset is the signed NTP correction and is
  passed to `clock_adjtime`; a negative value therefore moves the local guest
  clock backward toward NTP.
- No matching macOS sleep/wake, `timed`, or `powerd` event and no
  info-level timesyncd event occurred in the hold window. Their absence does
  not contradict the loop: the normal external-change resync path is logged
  only at debug level in systemd.

The bounded root-cause verdict is **`DUAL_TIME_AUTHORITY_OSCILLATION`**: Lima
periodically advances the guest to the macOS host clock, while
`systemd-timesyncd` observes that external step, immediately queries NTP, and
returns the guest roughly 2.45 seconds backward. This explains both stable
states in the hold: sample 03 caught the post-Lima state near the host
(`+38.284756 ms`), while the other 14 samples caught the post-NTP state around
`-2.4 s`. Official implementation references are Lima
[`timesync.go`](https://github.com/lima-vm/lima/blob/v2.1.1/pkg/hostagent/timesync.go)
and
[`server.go`](https://github.com/lima-vm/lima/blob/v2.1.1/pkg/guestagent/api/server/server.go),
plus systemd
[`timesyncd-manager.c`](https://github.com/systemd/systemd/blob/v255/src/timesync/timesyncd-manager.c)
and
[`timedatectl.c`](https://github.com/systemd/systemd/blob/v255/src/timedate/timedatectl.c).

No remediation or hold retry followed. The next separate slice must choose
one authoritative clock path and specify an explicit rollback before any live
change. The independent recurring I/O full-PSI gate remains open.

## Single-authority clock remediation design — option A selected

The owner selected **option A** on 2026-08-09: retain Lima host-to-guest time
sync and disable guest NTP. This section is a design and runbook only. It does
not authorize a macOS clock change, a Colima restart, or a guest service
change.

### Persistence surfaces and decision

| Criterion | Option A: Lima/macOS host | Option B: guest NTP |
| --- | --- | --- |
| Supported persistence | Per-profile Colima `colima.yaml` supports `mode: system` provisions; Lima runs them on every VM boot | Lima `2.1.1` exposes no narrow time-sync switch; `plain: true` disables the entire guest agent, mounts, and port forwarding |
| Rollback | Remove the provision, run `timedatectl set-ntp true`, and restart the same profile | Remove a systemd capability drop-in and restart `lima-guestagent`; Lima would still issue `SyncTime` every ten seconds |
| Time correctness | Aligns macOS, Colima, kind, and host-side producers, but inherits macOS absolute clock error | Follows external NTP, but blocking `CAP_SYS_TIME` is not a native Lima control |
| Runtime impact | Leaves `lima-guestagent` unchanged and creates no recurring error log | Failed `SyncTime` calls would warn every ten seconds and add log I/O while the I/O PSI gate is already open |

Option A is the smaller supported and reversible change. Its hard precondition
is that the macOS host already agrees with external NTP. A read-only
`/usr/bin/sntp 185.125.190.58` query returned
`-2.470866 +/- 0.006419 s`; option A therefore **cannot be applied yet**.
Correcting and validating the host clock is a separate authorized runtime
slice.

Version-specific sources:

- Colima `0.10.1` stores a named profile at
  `$HOME/.colima/<profile>/colima.yaml` and passes `system` provisions to
  Lima: [profile configuration](https://github.com/abiosoft/colima/blob/v0.10.1/docs/FAQ.md#can-config-file-be-used-instead-of-cli-flags)
  and [provision schema](https://github.com/abiosoft/colima/blob/v0.10.1/embedded/defaults/colima.yaml#L207-L234).
- Lima `2.1.1` runs idempotent provisions on every boot and starts host time
  synchronization without a configuration guard:
  [provision lifecycle](https://github.com/lima-vm/lima/blob/v2.1.1/templates/default.yaml#L183-L286)
  and [host sync](https://raw.githubusercontent.com/lima-vm/lima/v2.1.1/pkg/hostagent/timesync.go).
- systemd `v255` defines `timedatectl set-ntp false` as disabling and stopping
  known NTP services, with `true` as the inverse:
  [timedatectl](https://raw.githubusercontent.com/systemd/systemd/v255/man/timedatectl.xml).

### Fail-closed prechecks

Run these only in the separately authorized runtime slice, from a shell on the
Mac host. Do not continue if any command or assertion fails:

```bash
profile='agentflow-fc5-7113966'
config="/Users/julia/.colima/${profile}/colima.yaml"
backup="${config}.pre-single-clock-authority"
export PATH='/Users/julia/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin'

/bin/test -f "$config"
/bin/test "$(/usr/bin/grep -c '^provision: null$' "$config")" -eq 1
/bin/test ! -e "$backup"
colima --profile "$profile" status
sudo /usr/sbin/systemsetup -getusingnetworktime
sudo /usr/sbin/systemsetup -getnetworktimeserver
for sample in 1 2 3; do
  /usr/bin/sntp 185.125.190.58
  /bin/sleep 10
done
```

`systemsetup` must report network time `On` and a non-empty server. For all
three query-only `sntp` samples, the absolute first field must be at most
`0.100 s`, and the maximum-minus-minimum offset must be at most `0.050 s`.
The already observed `-2.470866 s` fails this gate. Stop before copying or
editing the config until a separate host-clock remediation has made this
precheck green.

Also require no active producer, soak, failure watcher, or Flink process and a
recorded inventory of the currently running kind workloads. Do not combine
clock work with the independent I/O PSI investigation.

### Host-clock remediation outcome — 2026-08-09

The separately authorized host-only slice corrected the macOS prerequisite.
A fresh entry query reproduced the failure at `-2.474351 +/- 0.008335 s`.
The privileged pre-change getters then proved the narrower root cause:
Network Time was `Off`, while its configured server was already
`time.apple.com`.

One native macOS Authorization Services action enabled Network Time and ran
`sntp -sS time.apple.com`; no credential was requested or handled by the
automation. `systemsetup` emitted its internal `Error:-99` diagnostic before
reporting `setUsingNetworkTime: On`, and the final privileged getters confirmed
Network Time `On` with server `time.apple.com`.

Three subsequent query-only samples against `185.125.190.58`, ten seconds
apart, returned `+0.004907`, `+0.005006`, and `+0.004896 s`. Maximum absolute
offset was `0.005006 s` and spread was `0.000110 s`, so both the `0.100 s`
absolute-offset and `0.050 s` spread gates passed. The temporary applet,
source, and result paths were removed after the result was captured.

This establishes only the macOS host-clock prerequisite at capture time. No
Colima config, VM, kind workload, guest service, watcher, Flink process, or
traffic was changed. A later separately authorized option-A application must
rerun every fail-closed precheck above; any regression stops it before the
profile config is copied or edited.

### Exact planned change

After every precheck is green, copy the current profile configuration once:

```bash
/bin/cp -p "$config" "$backup"
/usr/bin/shasum -a 256 "$config" "$backup"
```

The two hashes must match. Replace the single current `provision: null` line in
`/Users/julia/.colima/agentflow-fc5-7113966/colima.yaml` with exactly:

```yaml
provision:
  - mode: system
    script: |
      #!/bin/sh
      set -eu
      timedatectl set-ntp false
      active_state="$(systemctl show systemd-timesyncd.service --property=ActiveState --value)"
      unit_state="$(systemctl show systemd-timesyncd.service --property=UnitFileState --value)"
      test "$active_state" = inactive
      test "$unit_state" = disabled
```

`mode: system` is deliberate: Lima's built-in boot scripts may start
`systemd-timesyncd` earlier, while this root provision runs afterward on every
boot and fails the boot probe if the service remains active or enabled. Do not
edit Colima's generated `_lima` instance files.

The runtime change is then exactly one controlled restart of the named
profile:

```bash
colima --profile "$profile" restart
```

That restart affects the entire VM and kind cluster and therefore requires a
separate latest-user authorization. It is not authorized by this design.

### Focused verification and stop condition

After the restart, require all of the following before considering another
idle hold:

1. `colima --profile "$profile" status` reports running.
2. `colima --profile "$profile" ssh -- timedatectl show --property=NTP --value`
   reports `no`.
3. `colima --profile "$profile" ssh -- systemctl show
   systemd-timesyncd.service --property=UnitFileState
   --property=ActiveState --value` reports `disabled` and `inactive`.
4. `colima --profile "$profile" ssh -- systemctl is-active
   lima-guestagent.service` reports `active`.
5. The kind node is `Ready`, and the pre-change workload inventory recovers
   without launching Flink, traffic, or a watcher.
6. Capture 12 fresh private `scripts/diagnose_colima_runtime.py` snapshots ten
   seconds apart. Every invocation must exit `0`, report `status=complete`,
   and pass all checks. Host and guest clocks must remain monotonic; every
   absolute `offset_ns` must be at most `250,000,000`, and the 12-sample
   offset spread must be at most `250,000,000 ns`.
7. Three post-change `sntp` queries must still satisfy the precheck thresholds.

Any failure stops the slice and triggers rollback. Do not raw-retry the
restart, clock samples, or a failed service assertion. Do not run the
15-minute hold in the same slice; that is a separate gate after focused clock
verification is green.

### Option-A application outcome — focused verification deferred

The owner authorized option A on 2026-08-09. The provision is applied and the
single allowed Colima restart completed remotely, but focused verification is
**incomplete**, not PASS. The owner explicitly deferred the remaining
read-only checks to the next session and authorized a longer client timeout.

| Item | Captured evidence and current status |
| --- | --- |
| Latest pre-change host clock | Network Time `On`, server `time.apple.com`; three NTP offsets `+0.003245`, `+0.003216`, and `+0.003180 s`; maximum absolute offset `0.003245 s`; spread `0.000065 s` — PASS |
| Pre-change runtime | Colima running; kind node `Ready`; five workload pods `Running/Ready`; no Jobs or matching producer, soak, watcher, or Flink host process |
| Rollback backup | `/Users/julia/.colima/agentflow-fc5-7113966/colima.yaml.pre-single-clock-authority`, SHA-256 `e1abf039d7a563038d28bff9c6124b0344a9b90c1a2ac4b3e7e708351e9599af`; byte-identical to the original config |
| Applied config | `/Users/julia/.colima/agentflow-fc5-7113966/colima.yaml`, SHA-256 `6bc948c1c8b000e11f889af20b3dca1f8718a0cb327853ea687f424bf51ac31e`; YAML contract matched the exact provision above |
| Restart ledger | `colima --profile agentflow-fc5-7113966 restart` was launched exactly once. The client timed out after `184.1 s`, while remote PID `22315` continued and later exited. Do not start another restart merely because of the client timeout |
| Verified after remote exit | Colima `running`; guest `NTP=no`; `systemd-timesyncd.service` `inactive/disabled`; `lima-guestagent.service` `active`; kind node `Ready` |
| Still missing | Post-restart five-pod recovery comparison, 12 diagnostic snapshots, and three post-change NTP samples. The aggregate observation command timed out after `60.9 s` after printing the green service states and `Ready` node, before returning pod evidence |
| Temporary files | The remote helper and config candidate were removed. The local helper is removed in the documentation handoff; only the intentional rollback backup remains |

The first config-apply attempt created the backup but stopped before replacing
the config because expected `diff -u` exit `1` met `set -e`. A corrected helper
was transferred with SHA-256
`a4222f27d955ef09e14517d0150fd7ca65db9d4fe760a33dec0b105a55d75d3a`,
reused the backup only after an exact hash match, accepted only diff exit `1`,
and applied the validated candidate. No second restart, rollback, hold, Flink
process, watcher, traffic, or production transition followed.

#### Exact next-session resume sequence

1. Check the latest user message, local `git status`, and `HEAD`. Preserve the
   protected untracked paths and the rollback backup. Do not edit the config,
   restart Colima, or repeat host-time remediation during resume discovery.
2. Read-only confirm no `colima ... restart` process remains, config hash is
   `6bc948c1...31e`, backup hash is `e1abf039...9599af`, Colima is running,
   guest NTP is `no`, timesyncd is `inactive/disabled`, and guestagent is
   `active`. Any contradiction is a real failure and enters exact rollback.
3. Confirm the kind node is `Ready` and recover the same five pod identities:
   API `...-kk8tf`, bridge `...-htrwj`, Redis `...-9j9mn`, materializer
   `...-l8q89`, and Kafka `...-8mkq8`. Require all `Running/Ready` and no
   restart increase above `0`, `0`, `1`, `6`, and `0`, respectively.
4. Capture 12 fresh private `scripts/diagnose_colima_runtime.py` snapshots ten
   seconds apart. Set the overall client command timeout to at least `600 s`.
   If the tool yields before completion, continue waiting on the **same**
   process in intervals no longer than `50 s`; never launch a duplicate.
5. Require all 12 exits `0`, `status=complete`, and every diagnostic check
   PASS. Host and guest clocks must stay monotonic; every absolute `offset_ns`
   must be at most `250,000,000`, and offset spread must be at most
   `250,000,000 ns`.
6. Run three query-only `/usr/bin/sntp 185.125.190.58` samples ten seconds
   apart. Require maximum absolute offset `<=0.100 s` and spread `<=0.050 s`.
7. Any actual assertion failure, unreachable required surface, or incomplete
   run after the extended timeout triggers the exact rollback below without a
   raw retry. If all checks pass, preserve the backup and stop; the 15-minute
   hold is a separate later slice.
8. Do not investigate I/O PSI, arm the watcher, launch Flink or traffic,
   accept production, or push in this focused-verification resume slice.

### Exact rollback

If the VM remains reachable, restore the profile config, re-enable guest NTP,
and restart once:

```bash
/bin/cp -p "$backup" "$config"
colima --profile "$profile" ssh -- sudo timedatectl set-ntp true
colima --profile "$profile" restart
colima --profile "$profile" ssh -- timedatectl show --property=NTP --value
```

The final command must report `yes`, and `systemd-timesyncd.service` must be
`enabled` and `active`. If the changed config prevents the VM from starting,
restore the backup first, start the profile with
`colima --profile "$profile" start`, then run `timedatectl set-ntp true` and
verify the same states. Preserve the backup until a later full stabilization
hold is green.

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
- [x] Isolate the clock-offset-spread mechanism without changing runtime time
  settings. Verify: VM and kind share one clock; Lima adjusts it to the host
  every ten seconds; active systemd-timesyncd detects the external step and
  resynchronizes it to NTP. The observed states and source semantics identify
  `DUAL_TIME_AUTHORITY_OSCILLATION`.
- [x] Design one reversible single-authority remediation. Verify: both
  persistence surfaces are compared; the owner selected Lima/macOS host
  authority; exact prechecks, profile change, focused verification, stop
  condition, and rollback are recorded above. No live change was made, and
  the current `-2.470866 s` host/NTP offset blocks application.
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

Across the stabilization work recorded here, the only cluster mutation was the
scoped Kafka heap rollout. The clock RCA was read-only. No slice started
traffic or the Flink runtime, restarted Colima, cleaned Docker storage,
accepted production, or pushed commits.

## Next-session operator snapshot — 2026-08-09

This is the compact, authoritative starting point for the next session. Older
sections remain evidence history, but they must not be interpreted as pending
instructions when they conflict with this snapshot.

### Repository and artifact state

| Item | State at handoff |
| --- | --- |
| Entry branch / HEAD | `main` at `84ffda2`; 36 commits ahead of `origin/main` before this documentation-only update |
| Handoff commit | the commit containing this snapshot; confirm its exact hash with `git log -1 --oneline` |
| Tracked worktree at entry | clean after the clock-RCA commit |
| Push | not authorized; not performed |
| Live diagnostic smoke | `%TEMP%\deproject-colima-smoke-20260809T150346Z\diagnostics.json` |
| First hold bundle | `%TEMP%\deproject-colima-idle-hold-20260809T134556Z` |
| Instrumented hold bundle | `%TEMP%\deproject-colima-idle-hold-20260809T151626Z` |
| Runtime mutation in clock RCA | none |

The following untracked paths were already present and are outside this work;
preserve them unless the user explicitly changes their ownership:
`.codex-grok-tasks/`, `.grok-prompts/`, `AGENTS.md`,
`checkpoint-restore-replay-gate.md`,
`corrected-rollback-pair-local-design.md`, `docs/operations/cycle-guard.md`,
`fresh-zero-failure-job-lifetime.md`, `golden-4h-soak-rollback-gate.md`,
`plan_sol_23_07_26`, `production-gates-reverification-2026-08-01.md`, and
`tests/unit/test_golden_4h_soak_verify.py`.

### Current gate matrix

| Gate | State | Decisive evidence / implication |
| --- | --- | --- |
| Diagnostic runner | PASS | latest smoke and all 15 hold samples completed with all `17/17` checks passing |
| Clock stability | FAIL | `2485.431859 ms` spread; `DUAL_TIME_AUTHORITY_OSCILLATION` isolated |
| Idle I/O full PSI | FAIL | non-zero in 6/15 samples, maximum `0.23`; cause not proved |
| Memory | PASS | `MemAvailable=2,170,584..2,256,396 kB`; memory full PSI stayed zero |
| Disk | PASS | 60% used, 31 GiB free |
| Docker / containerd | PASS | containerd active, `NRestarts=0`, no new matching error line |
| Failure-evidence watcher | BLOCKED | do not arm before a complete green stabilization hold |
| Flink / traffic | BLOCKED | do not launch before watcher and stabilization prerequisites are green |
| Production | `candidate` only | no production acceptance and no push |

### What is observed, inferred, and still unknown

**Observed:** VM and kind share one clock; Lima logs a successful host-time
adjustment about every ten seconds from roughly `-2.45 s`; active timesyncd
reports a `-2.465089 s` NTP correction; the hold contains one near-host sample
and 14 samples near `-2.4 s`; the relevant Lima and systemd source paths have
the matching ten-second set-time and external-change resync behavior.

**Bounded inference:** those independent facts identify two active time
authorities oscillating the same VM clock. They explain the measured clock
spread without requiring a separate kind or container clock fault.

**Newly established:** a direct query from macOS to the guest's NTP IP measured
`-2.470866 +/- 0.006419 s`. The owner selected Lima/macOS host authority, and
the supported persistent surface is a per-profile Colima `mode: system`
provision that disables guest NTP. The exact rollback is documented above.

**Not established:** the macOS clock has not been corrected, the selected
change and rollback have not been executed, no post-remediation clock sample
or hold exists, and the etcd/Kafka write correlation does not establish the
cause of I/O PSI.

### Diagnostic retry ledger

| Attempt | Result | Reuse guidance |
| --- | --- | --- |
| Individual read-only host/VM/kind and root-journal probes | succeeded and produced the RCA evidence above | evidence is durable; do not rerun without a new hypothesis |
| Piped remote shell probe | quoting ended with `unexpected EOF`; no live action occurred | do not retry this wrapper |
| Base64/LF wrapper probe | quoting stripped Python literals and raised `NameError`; no live action occurred | do not retry this wrapper |
| Two non-interactive Colima version wrappers | stopped on missing SSH `PATH`, then missing Lima dependency lookup; neither reached the VM | use an explicit proven argv/PATH method only if a future design question truly requires it |

### Selected remediation and next runtime boundary

The **single-authority clock remediation design** is complete and selected
option A. No runtime change has occurred. The current host/NTP offset fails the
new `<=0.100 s` precheck, so the next separate slice may only correct and
validate macOS host time with explicit runtime authorization. It must stop
without editing Colima if the three-sample host/NTP gate remains red.

Only a later separately authorized slice may apply the profile provision and
controlled Colima restart. A 15-minute hold remains a third separate slice
after focused clock verification is green. The I/O PSI gate stays independent
and open throughout.

## Next-session resume

1. Check the latest user message for a hard stop, then refresh `git status` and
   `HEAD`; if they differ from this snapshot, trust the newer repository state.
2. Read the latest blocks in `AGENT_STATE.md` and `docs/SESSION_HANDOFF.md`,
   then use the operator snapshot above as the current detailed contract.
3. Preserve the listed untracked paths and all three private evidence paths.
   Do not repeat the passing smoke, either failed hold, or failed wrappers.
4. Treat the design above as complete. Do not apply it while the macOS/NTP
   precheck remains red.
5. The next separate slice requires explicit authorization for macOS host-time
   correction and validation. Do not edit Colima or mix in I/O work there.
6. Keep watcher, Flink, traffic, production acceptance, and push blocked.

## Focused verification failed; option A rolled back — 2026-08-09

This section supersedes the pending focused-verification instructions above.
Option A is **not accepted**. The exact documented rollback completed, but the
same five workloads did not recover to their pre-change readiness/restart
contract.

### Focused verification outcome

- Entry HEAD was `d3029db`. The repaired PowerShell 5.1 helper self-test passed
  all three gates: 200,000-byte async stdout drain, collection JSON roundtrip,
  and missing-field classification as `INCOMPLETE`.
- The read-only run from `2026-08-09T20:16:21Z` through `20:16:26Z` confirmed
  no active restart process, the applied config and backup hashes, Colima
  running, guest NTP `no`, timesyncd `inactive/disabled`, guestagent `active`,
  and the kind node `Ready`.
- Pod recovery failed on the exact identities. API, bridge, Redis,
  materializer, and Kafka had restart counts `31`, `31`, `2`, `37`, and `2`;
  API, bridge, and materializer were not Ready. This exceeded the required
  baselines `0`, `0`, `1`, `6`, and `0`.
- The fail-closed stop occurred before any of the 12 diagnostic snapshots or
  three post-change NTP samples. Raw evidence is under
  `%TEMP%\colima-clock-focused-verify-v2-20260809T201621Z-f8ce608d`.

### Exact rollback and post-rollback state

- The original profile config was restored from the preserved backup. Both
  files now have SHA-256
  `e1abf039d7a563038d28bff9c6124b0344a9b90c1a2ac4b3e7e708351e9599af`.
- Guest NTP was enabled and exactly one rollback restart ran to exit `0` in
  `228.6 s`. Post-restart checks showed Colima running, guest NTP `yes`,
  timesyncd `active/enabled`, and the kind node `Ready`.
- One bounded 300-second wait for all five exact pods timed out. The final
  projection showed API, bridge, and materializer in `CrashLoopBackOff` with
  restart counts `34`, `35`, and `41`; Redis and Kafka were Ready with restart
  counts `3` and `3`.
- No cause is assigned from the projection alone. No further restart, pod
  mutation, traffic, Flink process, watcher, 15-minute hold, production
  transition, or push occurred. The rollback backup remains preserved.

### Current boundary and next slice

The profile is back on its pre-option-A guest-NTP configuration. No
post-rollback clock sample was taken, so clock stability is not reclassified;
the prior failed clock and I/O full-PSI gates remain open. Production remains
`candidate`.

The next separate atomic slice is bounded read-only workload recovery RCA for
API, bridge, and materializer `CrashLoopBackOff` plus the Redis/Kafka restart
deltas. Capture current/previous logs and termination/dependency evidence
without another restart or workload mutation. Do not resume clock remediation,
run a hold, arm the watcher, launch Flink/traffic, accept production, or push.

## Next-session transparent operator snapshot — post-rollback

This is the current navigation entry and supersedes every earlier
`Next-session resume`, option-A application, and deferred-verification
instruction. Earlier sections remain evidence history only.

### Repository truth at snapshot entry

| Field | Value |
| --- | --- |
| Branch / entry HEAD | `main` / `77d1e9f` (`docs(ops): record failed clock verification rollback`) |
| Ahead of `origin/main` | `41` before the commit containing this snapshot |
| Tracked worktree | clean at entry |
| Canonical tracked outcome | this file; the snapshot commit is current HEAD after the docs-only slice |
| Ignored durable state | `AGENT_STATE.md`, `docs/SESSION_HANDOFF.md` |
| Push | not authorized; not performed |
| Production | `candidate` |

The two existing untracked control/evidence directories and nine protected
untracked files remain owner data. The last local validator confirmed all nine
file SHA-256 values unchanged. Do not clean, stage, rewrite, or move them.

### Evidence authority and reading order

| Order | Artifact | Meaning |
| --- | --- | --- |
| 1 | `.codex-grok-tasks/clock-focused-verification-20260809-grok01/rollback-result.json` | final machine-readable truth after rollback |
| 2 | `.codex-grok-tasks/clock-focused-verification-20260809-grok01/result.md` | concise human summary and boundaries |
| 3 | this section and the preceding rollback section | canonical tracked operator record |
| 4 | `verification-result.json` / `helper-result-v2.json` | immutable **pre-rollback** failure snapshot; `rollback_executed=false` is correct only at that capture time |
| 5 | `progress.json` and the first raw temp bundle | superseded helper-attempt evidence; its empty guest-NTP value was a helper transport defect, not a runtime assertion |

The valid focused-run raw evidence is
`%TEMP%\colima-clock-focused-verify-v2-20260809T201621Z-f8ce608d`.
The earlier incomplete helper bundle is
`%TEMP%\colima-clock-focused-verify-20260809T195815Z-0102b8d3`.

### Execution and retry ledger

| Executor / attempt | Outcome | Reuse rule |
| --- | --- | --- |
| Grok `deproject-clock-focused-20260809-grok01`, `grok-4.5-build` | cancelled after an stdin-consuming remote wrapper, redirected-output deadlock, and PowerShell 5.1 serialization error; no valid focused run | do not reuse the helper or its false rollback classification |
| Grok `deproject-clock-focused-20260809-grok02`, `grok-4.5-build` | cancelled after the corrected helper self-test still nested `ArrayList` values; no live run | do not relaunch; current self-test artifact was later replaced by the verified Codex result |
| Codex takeover | replaced nested arrays with direct `.ToArray()`, passed self-test `3/3`, ran one focused verification, detected the real pod failure, and completed the exact rollback | outcome is final for option A; do not rerun the helper or rollback |

No Grok process, local helper, yielded command cell, producer, watcher, or
other write-capable background process is known active at handoff.

### Last observed runtime truth

| Surface | Last observed state |
| --- | --- |
| Colima profile | running |
| Config / backup SHA-256 | both `e1abf039d7a563038d28bff9c6124b0344a9b90c1a2ac4b3e7e708351e9599af` |
| Guest clock service | NTP `yes`; timesyncd `active/enabled` |
| kind node | `agentflow-reverify-ed03fc47-control-plane` Ready |
| API | exact pod `...-kk8tf`; `CrashLoopBackOff`, Ready false, restarts `34`, last reason `Error` |
| Bridge | exact pod `...-htrwj`; `CrashLoopBackOff`, Ready false, restarts `35`, last reason `Error` |
| Redis | exact pod `...-9j9mn`; Ready true, restarts `3`, last reason `Unknown` |
| Materializer | exact pod `...-l8q89`; `CrashLoopBackOff`, Ready false, restarts `41`, last reason `Error` |
| Kafka | exact pod `...-8mkq8`; Ready true, restarts `3`, last reason `Unknown` |

These are last observations after the single 301.3-second post-rollback wait,
not a promise that live state will remain unchanged. If identities or counts
differ next session, record the new observation and do not overwrite this
historical evidence.

### Current gate matrix and claim boundary

| Gate | State | Boundary |
| --- | --- | --- |
| Option A | **FAIL / rolled back** | do not reapply without a new owner-approved design |
| Workload recovery | **FAIL** | three pods were in `CrashLoopBackOff`; cause unresolved |
| Clock stability | **FAIL remains** | no post-rollback clock sample; do not infer stability from service state |
| Idle I/O full PSI | **FAIL remains** | independent gate; no cause proved |
| Historical memory/disk/containerd checks | prior PASS only | not refreshed after rollback |
| 12-snapshot focused clock run | not started | pod fail-closed gate stopped it |
| 15-minute hold | not started | blocked by workload, clock, and I/O gates |
| Watcher / Flink / traffic | blocked | do not launch |
| Production / push | `candidate` / unauthorized | do not accept or push |

Do not claim that rollback recovered the workloads, that option A passed, or
that the clock/I/O gates are green. Do not assign a root cause from restart
counts or `CrashLoopBackOff` alone.

### Exact next-session resume sequence

1. Check the latest user message for a hard stop, then run fresh
   `git status --short --branch` and `git log -3 --oneline`. Trust disk over
   chat memory and preserve every unrelated untracked path.
2. Read `rollback-result.json`, `result.md`, and this snapshot before any
   remote query. Treat `verification-result.json` as pre-rollback evidence.
3. Confirm no writer is active. Do **not** rerun the helper, rollback, Colima
   restart, option-A application, 12-snapshot run, or 15-minute hold.
4. Perform one bounded read-only workload recovery RCA. Capture pod identity,
   current and previous logs, termination state, relevant events, and direct
   dependency evidence for API, bridge, and materializer; include Redis and
   Kafka restart deltas. If pods recovered meanwhile, preserve their previous
   termination evidence instead of declaring the issue resolved.
5. Stop after evidence and causal classification. Any restart, config edit,
   pod mutation, cleanup, clock redesign/application, watcher, Flink, traffic,
   production transition, or push is a separate authorization boundary.

## Workload recovery RCA — 2026-08-09

Read-only RCA after option-A rollback. Executor: local Grok CLI (launcher
`grok-4.5`, actual `grok-4.5-build`). Observation UTC:
`2026-08-09T22:46:11Z`. Context `kind-agentflow-reverify-ed03fc47` / namespace
`agentflow`. No remediation, restart, traffic, Flink, watcher, hold,
production transition, or push. Grok wrote the artifacts, then stopped
`cancelled` at a disallowed acceptance command; Codex owns the independent
gate and scoped local documentation commit.

### Evidence

Same five pod identities as the post-rollback snapshot
(`…-kk8tf`, `…-htrwj`, `…-l8q89`, `…-9j9mn`, `…-8mkq8`). Live restart counts
advanced for the crashloopers; Redis/Kafka stayed Ready at baseline `3/3`
(delta `0`).

| Role | Ready | Restarts (Δ vs post-rollback 34/35/41/3/3) | Last term | Decisive log fact |
| --- | --- | --- | --- | --- |
| API | false | 61 (+27) | Error / exit 3 | DuckDB WAL replay InternalException on `/data/agentflow_fresh_20260807.duckdb.wal` during lifespan `db_pool.initialize()` |
| Bridge | false | 62 (+27) | Error / exit 1 | configured ClickHouse HTTP endpoint refused connection in `ClickHouseSink.ensure_schema` |
| Materializer | false | 68 (+27) | Error / exit 1 | Iceberg REST `172.18.0.1:8181` connection refused at `load_catalog` |
| Redis | true | 3 (+0) | Unknown / 255 @ 20:20:19Z | Ready; previous SIGTERM 20:18:19Z (rollback Colima residue) |
| Kafka | true | 3 (+0) | Unknown / 255 @ 20:20:19Z | Ready; previous SIGTERM 20:18:19Z (rollback Colima residue) |

Redis endpoint `10.244.0.5:6379` and Kafka endpoint `10.244.0.9:9092` are
ready. API Service has no ready endpoints. Continuous `BackOff` events after
~20:24Z are restart residue, not root cause.

The independent Codex gate confirmed the same identities, exit codes, and
three error chains. By `2026-08-09T22:51:25Z`, restart counts had advanced to
API/bridge/materializer `62/63/69`, while Redis/Kafka remained `3/3`.

Execution transparency: one read-only PATH-discovery query and bounded remote
log-filter pipelines exceeded the prompt's Kubernetes-only/single-command
shape. They performed no mutation, secret read, restart, or traffic action.
No inline pod-spec environment values are retained in the final artifacts.

Artifacts:
`.codex-grok-tasks/workload-recovery-rca-20260809-grok01/{evidence.md,result.json,result.md}`.

### Classification

**`ROOT_CAUSE_PROVEN`**. Three distinct primary application startup failures,
each cited from container logs and matching exit codes:

1. API dies on local emptyDir DuckDB WAL replay failure (not Redis).
2. Bridge dies on its configured ClickHouse endpoint refusing the connection (not Kafka).
3. Materializer dies on host-gateway Iceberg REST connection refused (not Kafka).

`CrashLoopBackOff` and elevated restart counts are downstream residue of those
primary errors. Gaps that remain (host process state for the ClickHouse and
Iceberg REST endpoints, WAL origin without exec) do not leave the CrashLoop
causes unresolved.

### Claim boundary

- Workload recovery remains **FAIL**.
- Option A remains **FAIL / rolled back**.
- No clock stability or idle I/O green claim from this slice.
- No unsupported fix claim; no secrets; no production acceptance.

### Exact next safe boundary

Any remediation (WAL cleanup, host ClickHouse/Iceberg recovery, pod or
deployment mutation, restart, redesign, traffic, Flink, watcher, hold,
production transition, or push) requires a **separate authorized
slice**. This RCA stops at evidence and classification.

## Host dependency lifecycle RCA — 2026-08-09

One bounded read-only host-side investigation identified the exact owners and
lifecycle state behind the ClickHouse and Iceberg REST connection refusals.
Observation UTC: `2026-08-09T23:09:37Z`. No container, Compose, Colima, or
Kubernetes mutation was performed.

### Ownership and live state

| Dependency | Compose owner | State | Finished UTC | OOM / error | Restart policy / count |
| --- | --- | --- | --- | --- | --- |
| ClickHouse | `agentflow-ch-rv-20260802-01` | exited `137` | `17:52:49.269Z` | false / empty | `no` / `0` |
| Iceberg REST | `agentflow-iceberg-rv-20260802-01` | exited `137` | `17:52:48.723Z` | false / empty | `no` / `0` |
| MinIO | same Iceberg project | exited `0` | `17:52:40.782Z` | false / empty | `no` / `0` |

Compose labels map ClickHouse to
`/tmp/agentflow-chk-restore-rv-20260802-01/clickhouse-compose.yml` and Iceberg
REST to `/tmp/agentflow-iceberg-ed03fc47-20260801-01/docker-compose.iceberg.yml`.
The ClickHouse task manifest explicitly sets `restart: "no"`; the Iceberg
manifest's omitted policy resolves to Docker policy `no`.

Docker network `kind` maps `172.18.0.0/16` to gateway `172.18.0.1`, so the
failed workload addresses map directly to these owners. The only running
Docker container at observation was the kind control-plane, which restarted
at `20:21:47.642Z` under policy `on-failure`; no dependency port publisher was
running.

### Causal evidence

- Iceberg REST was serving normal metadata activity through `17:51:44.106Z`.
- MinIO logged `Exiting on signal: TERMINATED` at `17:52:38.393Z` and exited
  cleanly two seconds later.
- MinIO, Iceberg REST, and ClickHouse all finished within nine seconds;
  neither exit-137 container was OOM-killed and Docker recorded no state
  error.
- The option-A application slice records exactly one Colima restart. Its
  handoff commit followed at `18:17:03Z`; no other intended runtime mutation
  was recorded in that slice.
- All dependency restart counts remain zero. The later rollback recovered the
  kind control-plane but did not relaunch the external Compose projects.

### Classification and claim boundary

**`ROOT_CAUSE_PROVEN`** for the missing endpoints. Operational root cause:
**`COLIMA_RESTART_DEPENDENCY_LIFECYCLE_GAP`**. Required external Compose
services stopped with the Colima restart and remained stopped because their
restart policies were `no`; the restart workflow lacked a dependency restore
or fail-closed post-restart health gate.

The direct Docker daemon event line naming the `17:52Z` VM shutdown was not
retained, but the synchronized termination signal/state, absence of OOM or
Docker errors, single documented restart, and zero restart counts establish
the trigger at high confidence. No dependency was started and no recovery
claim is made. Restoring these services would not fix the independent API
DuckDB WAL failure. Clock and idle-I/O gates remain failed/open; production
remains `candidate`.

Artifacts:
`.codex-grok-tasks/host-dependency-lifecycle-rca-20260809-codex01/{evidence.md,result.json,result.md}`.

### Exact next safe boundary

In a separate slice, design and test a fail-closed external-dependency
recovery gate before any live Compose start. It must preserve the named
ClickHouse volume and MinIO/Iceberg data, distinguish one-shot `minio-init`
from long-running services, require health before workload verification, and
define rollback/stop conditions. API WAL, clock, idle-I/O, traffic, Flink,
watcher, hold, production transition, and push remain separate boundaries.

## External dependency recovery gate — 2026-08-09

The local design/test boundary is complete. The implementation is
`scripts/recover_external_dependencies.py`; the operator contract is
`docs/operations/external-dependency-recovery-gate.md`.

The CLI defaults to a read-only remote preflight. Live recovery requires both
`--execute` and the exact acknowledgement
`COLIMA_RESTART_DEPENDENCY_LIFECYCLE_GAP`. Before starting anything, the gate
requires the recorded Compose services and labels, the existing ClickHouse
named volume and mount, the existing MinIO container layer, the successful
exited `minio-init`, and the running kind control-plane.

The live path, which was not run in this slice, uses only scoped
`docker compose start` operations. It waits for ClickHouse and MinIO health,
runs `minio-init` as a one-shot to `exited (0)`, starts Iceberg REST, and then
probes all three endpoints from the kind control-plane. A failure stops only
services started by that invocation in reverse order, without container or
volume removal. Pre-existing healthy services remain running.

Focused local tests cover ordering, preflight failure before mutation,
one-shot failure, scoped rollback, preservation of pre-existing services, and
the ban on create/recreate/delete command shapes. No SSH, Docker, Compose,
Colima, or Kubernetes command was executed during implementation or testing.

### Exact next safe boundary

Run the default read-only preflight in a separate slice and preserve its JSON
result. A live `--execute` run remains a later explicit runtime mutation.
Workload recovery, the API WAL failure, clock and idle-I/O gates, traffic,
Flink, watcher, hold, production transition, and push remain separate.

## External dependency recovery preflight — 2026-08-09

The default recovery-gate preflight ran once against the recorded remote
Colima Docker socket from `23:38:16.610Z` through `23:38:22.032Z`. It exited
`0` with `status: preflight_passed`, `execute: false`, and
`ready_for_workload_verification: false`.

The fail-closed checks accepted the exact Compose service sets, container
ownership/images/restart policies, ClickHouse named volume and mount, MinIO
container layer, successful exited `minio-init`, and running kind
control-plane. Observed dependency state remained unchanged:

| Service | State | Exit | Recorded health |
| --- | --- | ---: | --- |
| ClickHouse | exited | 137 | unhealthy |
| Iceberg REST | exited | 137 | n/a |
| MinIO | exited | 0 | unhealthy |
| `minio-init` | exited | 0 | n/a |

The `unhealthy` values are stale Docker health state on exited containers,
not live endpoint results. The command performed Compose config and Docker
inspection only: no `--execute`, start/stop, Docker exec, Colima/Kubernetes
mutation, workload verification, traffic, secret read, production transition,
or push occurred.

Exact JSON evidence:
`.codex-grok-tasks/external-dependency-recovery-preflight-20260809-codex01/{preflight-output.json,result.json}`.

### Exact next safe boundary

A live `--execute` dependency recovery is now locally designed and its
preconditions are verified, but it remains a separate runtime-mutation slice.
It must not be combined with workload verification, API WAL remediation,
clock or idle-I/O work, traffic, Flink, watcher, hold, production transition,
or push.

### Next-session transparency pointer

The self-contained operator snapshot is the `Next-session transparent
resume` section in
`docs/operations/external-dependency-recovery-gate.md`. It records the exact
remote identities and invocation, the eight read-only Docker calls, local
evidence hashes, the absence of a raw per-command SSH transcript, data
ownership, unchanged failure gates, rollback expectations, and the next
decision boundary.

Do not repeat the already-green standalone preflight merely to refresh its
timestamp. A later acknowledged `--execute` invocation runs the same
fail-closed preflight internally before any mutation. Dependency recovery
success would authorize only a separate workload-verification decision; it
would not resolve or waive the API WAL, clock, idle-I/O, traffic, soak, or
production gates.

## Workload recovery verification — 2026-08-10

One bounded read-only workload verification observed the existing pods at
`2026-08-10T00:30:13.1767165Z`. Eight separate Kubernetes metadata, endpoint,
event, and bounded-log queries all exited `0`; none was retried. No workload,
dependency, Kubernetes object, Colima profile, or application source code was
mutated, and no pod `exec` or traffic was performed.

| Workload | Ready | Restarts (prior / current) | Decisive current evidence |
| --- | --- | ---: | --- |
| API | no | 62 / 80 | exit `3`; DuckDB WAL replay internal error |
| Bridge | yes | 63 / 82 | `bridge_started`, backend `clickhouse` |
| Materializer | yes | 69 / 88 | successful 256-record materialization batches |
| Redis | yes | 3 / 3 | endpoint `10.244.0.5:6379` |
| Kafka | yes | 3 / 3 | endpoints on `9092` and `29093` |

The pod names and UIDs were unchanged from the prior RCA. Bridge and
materializer recovered after external dependency recovery; Redis and Kafka
remained stable. API alone stayed in `CrashLoopBackOff`, with its last startup
failing while replaying `/data/agentflow_fresh_20260807.duckdb.wal`:
`Calling DatabaseManager::GetDefaultDatabase with no default database set`.
Its empty service endpoint is a downstream readiness consequence.

Classification: **`WORKLOAD_RECOVERY_PARTIAL`**, **`ROOT_CAUSE_PROVEN`**;
remaining primary failure: **`API_DUCKDB_WAL_REPLAY_FAILURE`**. External
dependency recovery is consumed and must not be repeated merely to retest the
independent API failure. Clock stability, idle-I/O, traffic, soak, and
production gates remain failed/open; production remains `candidate`.

Artifacts:
`.codex-grok-tasks/workload-recovery-verification-20260810-codex01/{evidence.md,result.json,result.md}`.

### Exact next safe boundary

In a separate slice, perform a local/read-only ownership and design diagnosis
of the API DuckDB persistence and WAL recovery contract before any cleanup,
pod `exec`, restart, or runtime mutation is considered. Define data ownership,
preservation, rollback, and acceptance criteria; do not infer authorization to
delete or replace the database or WAL.
