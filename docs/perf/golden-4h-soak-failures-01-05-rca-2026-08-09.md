# Golden 4h soak failures `-01`…`-05` — cross-run causal analysis

- **Captured:** 2026-08-09
- **Scope:** read-only comparison of the five consumed soak attempts
  `golden-4h-soak-rv-20260807-01` through `-05`
- **Acceptance result:** no soak PASS; no `dual_mean_90` PASS JSON; corrected
  Helm rollback not started
- **Production state:** `candidate`; combined soak/rollback gate remains open
- **`-05` diagnostic classification:**
  `UNRESOLVED_FLINK_TERMINAL_FAILURE` (documentation only; not a runtime emit)

## Executive conclusion

The five attempts do not have one proven application-level exception. The
evidence shows three interacting failure layers:

1. **Shared upstream instability in the Colima/kind VM.** Every failure window
   contains guest-clock backward jumps. Runs `-01`, `-02`, and especially
   `-04` also contain Kubernetes API/control-plane disruption. Run `-04`
   includes a directly observed container filesystem stall and component
   exits, making infrastructure failure proven for that attempt. The same VM
   instability is a strong common explanation for `-01`/`-02` and a likely
   contributor to `-05`, but it does not prove the exact Flink exception.
2. **Acceptance harness gaps.** Early observer thresholds converted two API
   observation failures into `pods_unhealthy 0/0`. The `-03` launch path
   admitted a job with `0/2` running tasks because its final preflight did not
   require task readiness and checkpoint growth. In `-05`, the preserved
   `pods_unhealthy 1/1` text won a threshold race after Flink was already
   terminal, so it is a secondary symptom rather than the cause.
3. **Recovery amplifiers.** The application forces Flink's `failure-rate`
   restart strategy even when the CR declares another strategy. Before `-05`,
   Kafka also lacked durable storage, so the `-04` infrastructure restart lost
   topics and made recovery fail. Kafka durability was fixed before `-05` and
   is not supported as the cause of `-05`.

The exact original JobManager/TaskManager exception for `-05` remains
**unresolved because the failure-window logs and exception history were not
retained**. This report must not be used to relabel that run as a fully proved
root cause.

## Confidence vocabulary

| Label | Meaning in this report |
| --- | --- |
| **Proven** | Directly present in surviving observer, pod-status, kernel, or application evidence |
| **High-confidence inference** | Multiple independent observations support the chain, but the original terminal exception is missing |
| **Unresolved** | Surviving evidence cannot distinguish the initiating exception |

## Run-by-run causal matrix

| Run | Primary observed failure | Observer / recovery effect | Classification |
| --- | --- | --- | --- |
| `-01` | Kubernetes API observations failed while Flink changed from `RUNNING 2/2` to `SUSPENDED 0/0` | Two-sample observer policy emitted `pods_unhealthy ... ready=0/0`; the same pods returned `2/2` with zero restarts, then Flink reported `no_jobs` | Shared VM/control-plane disruption is high confidence; exact Flink exception unresolved |
| `-02` | Same signature as `-01`: API timeout followed by Flink `SUSPENDED` | Second API timeout triggered `pods_unhealthy`; pods returned `2/2`, while Flink became `no_jobs` | Shared VM/control-plane disruption is high confidence; exact Flink exception unresolved |
| `-03` | From the first observer sample, the job was `RUNNING` with tasks `0/2` and no checkpoint progress | Five unhealthy Flink samples ended in REST `HTTPError`; launch preflight had not required `2/2` tasks or checkpoint growth | Failed gate caused by admitting an unhealthy job; `taskSlots=1` was a strong scheduling contributor, not a proved sole cause |
| `-04` | Colima/kind control plane and container runtime stalled; Flink went `SUSPENDED`/`no_jobs` and later `FAILED` | Kafka restarted without durable topic data; recovery then encountered missing topics and offsets and exhausted the application restart budget | Infrastructure failure proven; Kafka data loss proven as a recovery blocker; exact original Flink exception not retained |
| `-05` | Producer completed four hours, then Flink REST failed and the job became `FAILED 0/0` | TaskManager disappeared afterward; two `1/1` samples emitted `pods_unhealthy` before the five-sample Flink reason | Terminal Flink failure proven; immediate exception unresolved; shared VM instability is a likely contributor only |

## Decisive timelines

All timestamps are UTC.

### `-01`

- `12:58:43`: Flink still `RUNNING 2/2`; Kubernetes pod-list
  `TimeoutError` produced a synthetic `0/0` observation.
- `13:00:53`: Flink `SUSPENDED 0/0`; pod-list `URLError`; the second bad
  observer sample wrote ABORT.
- The next healthy Kubernetes observation returned the same `2/2` pods with
  total restart count `0`; Flink then reported `no_jobs`.

The ABORT's `0/0` topology was therefore not proof that the pods had actually
terminated. The simultaneous Flink suspension was real.

### `-02`

- `18:29:10`: pod-list `TimeoutError`; Flink still `RUNNING 2/2`.
- `18:30:23`: second pod-list timeout; Flink `SUSPENDED`; observer wrote
  ABORT.
- The following Kubernetes observation again returned `2/2`; Flink returned
  `no_jobs`.

This reproduces the `-01` API-observation/real-Flink-suspension combination.

### `-03`

- `19:42:05` onward: pods stayed `2/2`, but the Flink job remained
  `RUNNING 0/2` with zero completed checkpoints.
- `19:46:07`: the fifth unhealthy Flink sample ended in REST `HTTPError` and
  wrote ABORT.
- There was no Kubernetes API failure before the abort.

The immediate acceptance defect is proven: the traffic phase began without a
final task-readiness/checkpoint-growth gate. The live configuration then had
`taskmanager.numberOfTaskSlots: 1`; after it was changed to `2`, later recovery
reached and held `2/2`. This supports slot under-provisioning or reconciliation
racing as the scheduling cause, but does not isolate one sole mechanism.

A later diagnostic detour set TaskManager process memory to `1280m` and task
heap to `384m`. Flink rejected the derived JVM overhead (`448m`, outside the
configured `128m`–`256m` range). That error prolonged recovery but occurred
after the original `-03` abort and is not its cause.

### `-04`

- `21:09:53`: Flink changed to `SUSPENDED` while pods still reported `2/2`.
- `21:12:24`–`21:12:40`: the control-plane window contains a backward-clock
  jump; both CoreDNS containers exited, kube-apiserver exited `137`, and the
  Flink operator exited `143`.
- `21:12:30`: the kernel reported `containerd-shim` blocked for more than
  122 seconds in overlay filesystem sync/writeback.
- `21:16:09`: observer reached its five-sample Flink threshold with
  `no_jobs`; the next reconciliation produced `RUNNING 0/2`, then `FAILED`.
- The post-failure P0 snapshot showed only about `83 MiB` free-ish Mac memory,
  high control-plane restart counts, and a restarted Kafka pod. Only
  `__consumer_offsets` remained because the Kafka data directory was not
  persistent.

During P0 recovery, Flink reported `UnknownTopicOrPartitionException`; after
topics were recreated it reported `NoOffsetForPartitionException`. These
exceptions prove the post-collapse Kafka recovery blockers. They were captured
after the original `-04` terminal job and must not be presented as that
original job's exact exception.

### `-05`

- Producer PASS: `1,440,000/1,440,000`, delivery failures `0`, elapsed
  `14,400.030287 s`, delivered EPS `99.99979`.
- `02:44:33`: Flink `RUNNING 2/2`, checkpoint `1376`; one pod-list
  `TimeoutError`.
- `02:46:04`: Flink REST `HTTPError`; pods still `2/2`.
- `02:47:08`: Flink already `FAILED 0/0`; pods still `2/2`.
- `02:48:10`: TaskManager gone, topology `1/1` for the first time.
- `02:49:11`: second `1/1` sample preserved
  `pods_unhealthy ok=True ready=1/1 error=None`.

Kafka's pod existed before the run and retained restart count `0`. The
kube-apiserver and Flink operator also had no restart in this failure window.
No surviving evidence proves Kafka failure, OOM, verifier load, or the
`pods_unhealthy` condition as the initiating cause.

## Common VM evidence

The control-plane kernel log contains
`systemd-journald: Time jumped backwards, rotating` during every failure
window:

| Run | Backward-jump messages around the failure |
| --- | --- |
| `-01` | `12:51:14`, `12:57:25`, `12:58:55`, `13:03:34`, `13:05:05` |
| `-02` | `18:20:24`, `18:25:05`, `18:29:34`, `18:31:04` |
| `-03` | `19:40:14`, `19:41:45`, `19:44:55`, `19:47:54` |
| `-04` | `21:12:24`, followed by the `containerd-shim` stall at `21:12:30` |
| `-05` | `02:38:44`, `02:44:54`, `02:47:54`, `02:51:04`, `02:52:35` |

The same log also records journald memory-pressure flushes at `18:14:16`,
`19:12:48`, `19:49:11`, `20:30:01`, and `20:54:44`.

What this proves: guest realtime repeatedly moved backward in each failure
window, and `-04` combined it with a concrete container-runtime/control-plane
collapse. What it does **not** prove: that a clock jump alone threw the missing
Flink exception in `-01`, `-02`, or `-05`.

## Systemic amplifiers and misleading signals

### Observer precedence and thresholds

- Runs `-01`/`-02` used a two-consecutive-sample threshold for all health
  surfaces. Two API failures were enough to emit a pod-topology abort.
- Later observers increased API and Flink thresholds to five samples, but a
  real non-API pod-topology change still used two samples.
- In `-05`, that two-sample topology path emitted first even though Flink had
  already been `FAILED` for two samples. The first stored reason is therefore
  not necessarily the first causal event.

### Preflight evolution

- `-03` did not require final `tasks_running == tasks_total` or checkpoint
  growth after reconciliation.
- `-04` added a task-readiness check.
- `-05` added a 75-second checkpoint-growth hold and stayed healthy for the
  complete four-hour producer window.

### Restart policy conflict

`src/processing/flink_jobs/stream_processor.py` always configures
`restart-strategy.type=failure-rate`. Defaults are three failures per five
minutes with a ten-second delay, although environment variables can raise the
limits. This application configuration overrides a conflicting CR-level
`fixed-delay` strategy. It is a recovery-budget amplifier, not proof of the
initiating failure.

## Evidence map and retention warning

| Evidence | Location |
| --- | --- |
| Canonical `-05` tracked report | `docs/perf/golden-4h-soak-05-failure-2026-08-08.md` |
| Historical `-01`…`-04` handoff | `.codex-grok-tasks/session-close-20260807-soak-fail-fix-incomplete/NEXT_SESSION.md` |
| `-04` P0 recovery report | `.codex-grok-tasks/p0-stabilize-recover-20260807-05/runtime-result.md` |
| Kafka durability follow-up | `.codex-grok-tasks/kafka-durability-20260807-05/runtime-result.md` |
| Application restart policy | `src/processing/flink_jobs/stream_processor.py` |
| Mac runtime packs | `/tmp/agentflow-soak-runtime-20260807-01/` through `-05/` |
| kind-node observer logs | `/var/agentflow-task-state/golden-4h-soak-rv-20260807-01/` through `-05/` |

The `.codex-grok-tasks` and remote `/tmp` paths are local operational evidence,
not durable repository history. This tracked report preserves their decisive
conclusions, but not every raw log line.

## Claim boundaries for future sessions

- Identities `-01` through `-05` are consumed and must never be reused.
- Do not describe `-05` as producer failure, Kafka failure, OOM, verifier
  overload, or pod-topology failure without new primary evidence.
- Do not claim that all five attempts share one exact Flink exception.
- Do not treat the P0 `UnknownTopicOrPartitionException` as the original
  `-04` exception; it is post-failure recovery evidence.
- No investigation in this RCA restarted the stand, generated traffic,
  launched a soak, changed Kubernetes/Helm, or pushed commits.

## Exact next-session boundary

Before any new soak identity or runtime mutation:

1. Read this report and the canonical `-05` report; refresh `git status`.
2. Use the first separate implementation slice to retain JobManager and
   TaskManager current/previous logs, Flink exception history, pod termination
   state, namespace events, and observer chronology to a host-persistent path
   at failure time.
3. Separately diagnose and stabilize Colima guest time, memory headroom, and
   filesystem/container-runtime stalls. If this host cannot be made stable,
   move the acceptance run to a stable execution environment.
4. Align the effective Flink restart strategy and ensure observer output
   distinguishes API observation failure, terminal Flink state, and downstream
   pod topology.
5. Only after those prerequisites and explicit runtime authorization, use a
   new identity and rerun the gate.

This report does not authorize a rerun, live remediation, Helm rollback,
production elevation, push, or reuse of a consumed identity.
