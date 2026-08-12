# Golden 4h soak + rollback — resource-capacity blocker (2026-08-01)

**Date:** 2026-08-01<br>
**Result:** read-only preflight **`BLOCKED_RESOURCE_CAPACITY`**<br>
**Canary / 4h soak / rollback:** **NOT STARTED** (blocked; not PASS)<br>
**Context / namespace:** `kind-agentflow-golden-36ed1ec` / `agentflow`<br>
**SSH alias:** `deproject-mac`<br>
**Local HEAD before this documentation:**
`cf28069aad167355240e2b3d58464e9ce848512a` (local-only, unpushed, ahead 7;
**not** a runtime or Operator-accepted SHA). Runtime source / `origin/main`
remains `ed03fc47fa5f411016e588774d61a5b5eef21213`. Operator acceptance base
remains exact `36ed1ec`.<br>
**Runtime source / Operator base:** `ed03fc47` / `36ed1ec`<br>
**Task id:** `golden-4h-soak-rollback-20260801`

Control artifacts (local only):
`.codex-grok-tasks/golden-4h-soak-rollback-20260801/preflight-result.md`.

Plan pointer: `golden-4h-soak-rollback-gate.md`.

## Claim boundary

This note records a **completed read-only preflight** that blocked starting
the canary, four-hour soak, and Helm rollback rehearsal for resource capacity.

It is **not** soak PASS, **not** rollback PASS, **not** production acceptance,
and **not** checkpoint restore/replay acceptance. Autonomous protected Flink
recovery observed during the preflight is **health evidence only**.

Repository-side `pending_acceptance` is **unchanged**:

1. `checkpoint restore and replay acceptance`
2. `4h soak and rollback rehearsal on the golden topology`

Exactly four production-acceptance gates remain overall (restore/replay,
fresh 4h soak+rollback, external pentest, npm approval). Product status
remains **`candidate`**. No score raised. No tracked code/product change.
No runtime mutation. No push.

## What was run

Read-only investigation and planning only: contract derivation, traffic-path
design, live readiness/capacity/disk facts, rollback rehearsal design, and a
canary recommendation. No produce, scale, restart, Helm upgrade/rollback, or
other runtime mutation by Grok or Codex in this preflight.

| Item | Value |
| --- | --- |
| Protected FlinkDeployment | `agentflow-stream-processor` |
| Protected CR UID | `0622bd9c-3cec-410c-b778-78440a3c0ba9` |
| `spec.restartNonce` | `1` |
| Physical job ID (observed) | `61e8042c8422974091cc3cad20f07380` |
| Helm release | `agentflow` revision **2** / deployed |
| ServiceAccount UID | `a8f4ebd8-53de-4680-b89d-83d0114db852` |
| Task restore CR | **absent** throughout |
| Restore topic | `orders.raw.chk-restore-20260801-01` end offset **0** (untouched) |

## Acceptance contract (post-Iceberg; not weakened)

A fresh four-hour soak on the **same golden topology** must exercise the full
post-Iceberg path continuously:

```text
orders.raw
  → protected PyFlink stream_processor (existing job only)
  → events.validated
  → lake materializer → Iceberg agentflow.validated_events
  → serving bridge → ClickHouse (pipeline_events / orders_v2)
  → task API entity (+ timeline sample)
```

| Metric | Criterion |
| --- | --- |
| Produce pace | **100 delivered events/s** (delivery-guarded, not fire-and-forget) |
| Duration | **14_400 s** wall clock |
| Planned volume | **1_440_000** delivered events |
| Lake / serving | exact unique counts for soak namespace = delivered (once) |
| DLQ / duplicates / apply failures | **0** / **0** / **0** |
| End lag | ≤100 |
| Checkpoints / Flink | completed grow; failed **0**; no unhealthy flap under load |
| Disk pre-start | Kind/Colima volume used **≤80%** |
| In-run abort | disk ≥90% or free unsafe; MemAvailable collapse; job not RUNNING |

The 2026-07-19 paced 4h soak
(`docs/perf/throughput-realpath-paced100-4h-r4-2026-07-19.md`) predates the
lake materializer and remains **advisory only** for the current golden gate.
Do **not** lower the 100 delivered eps / exactness contract to host capacity.

## Decisive capacity evidence

### Disk (primary blocker)

| Surface | Observation |
| --- | --- |
| Kind node / shared Colima volume | **`df` ~59G total, ~53G used, ~3.6–3.7 GiB free, 94%** |
| ClickHouse / MinIO data paths | same **94%** shared filesystem |
| Host macOS Data volume | ample free — **not** the binding constraint |

Order-of-magnitude growth estimate for **1.44M** full-path events (not a
measured run result): **roughly 3–8+ GiB** across Kafka, Iceberg/MinIO,
ClickHouse, and Flink checkpoints/logs. Free headroom is **below** that
estimate; no safe margin for log/checkpoint spikes.

### Memory

| Metric | Value |
| --- | --- |
| Host RAM | **exactly 8 GiB** |
| Docker/Colima MemTotal | ≈ **5.786 GiB** |
| Available memory during preflight | about **0.54–0.69 GiB** class |
| Kind working set | ~4 GiB class under observation |

Acute memory pressure; no room for 4h load growth. Preferred Colima memory
growth remains impossible/not clearly safe on this 8 GiB host (see restore
capacity blocker).

### Protected Flink flap then autonomous recovery (health only)

During **read-only** observation the protected deployment briefly flapped
(Job Not Found → RECONCILING/CREATED, TM recreate, transient API EOF), then
**autonomously recovered** with:

| Field | Observed after recovery |
| --- | --- |
| CR UID | unchanged `0622bd9c-3cec-410c-b778-78440a3c0ba9` |
| SA UID | unchanged `a8f4ebd8-53de-4680-b89d-83d0114db852` |
| Job ID | same `61e8042c8422974091cc3cad20f07380` |
| Checkpoints | restore from **`chk-212`**, then completed **`chk-213`** and **`chk-214`**, failed **0** |
| Helm | still revision **2** |

That recovery proves identities and checkpoint machinery can self-heal. It is
**not** soak readiness and **not** acceptance evidence. Baseline was not
hold-stable enough to authorize canary or 4h load.

## Rollback design (not executed)

| Revision | Safety for this gate |
| --- | --- |
| Helm rev **1** | **Unsafe** — lacks the protected `flinkJob` block; must **never** be the rollback target |
| Helm rev **2** | Current deployed golden enablement; freeze as rollback target |
| Future rehearsal | create a **benign revision 3** (no-data-loss), then `helm rollback` → **rev 2** only |

`docs/runbooks/release-rollback.md` is PyPI/npm yank, not this Helm path.

## Verdict

# **`BLOCKED_RESOURCE_CAPACITY`**

Decisive reasons:

1. Shared Kind/Colima disk **94% used**, only **~3.6–3.7 GiB free** vs multi-GiB
   estimated growth for 1.44M full-path events.
2. **Acute memory pressure** (MemAvailable ~0.54–0.69 GiB class).
3. Transient API unavailability and **autonomous protected Flink recovery**
   during read-only observation — baseline not hold-stable for load.

**Not selected:** `READY_FOR_BOUNDED_CANARY`, `BLOCKED_ACCEPTANCE_CONTRACT`,
`BLOCKED_ROLLBACK_SAFETY` (rollback design is clear but secondary),
`INCONCLUSIVE_READ_ONLY`.

Canary, soak, and rollback were **not started**. Do not claim PASS.

## Preconditions before any canary

All required:

1. **Authorized capacity remediation** (inventory + owner gate; no blind prune
   of protected/restore paths).
2. Disk used **≤80%** on Kind/Colima volume; preferably **≥12–15 GiB free**
   (must cover estimated growth + ≥20% margin).
3. MemAvailable **≥1.5–2.0 GiB** before load without killing protected Flink.
4. **Stable 10–15 min hold:** STABLE+RUNNING, REST 2/2, checkpoints advancing,
   failed CP 0, no TM churn / API EOF, UIDs/nonce stable.
5. Reliable Kafka offsets; restore topic still 0; task restore CR still absent.
6. Task-local traffic/evidence tooling ready (canary producer + observer).
7. Rollback frozen to **revision 2** (never rev 1; benign rev3 first if needed).

Smallest post-unblock canary: **N = 500–2000** delivered events @ **100 eps**
on the protected job only, full post-Iceberg exactness, DLQ/dup/fail 0, no
Flink flap, disk still ≤85%.

## Exact next decision

Both restore/replay and fresh 4h soak+rollback remain **open and
capacity-blocked** on this stand. Do **not** start canary/soak/rollback until
the preconditions above are green. Do **not** weaken the acceptance contract.

1. **Authorized capacity remediation** is required before either capacity-bound
   gate can run on this host class.
2. Next **independent safe audit item** (no runtime mutation, no capacity
   change): read-only check of GitHub **`npm` Environment approval evidence**.
3. External pentest remains a separate owner-scheduled gate.
4. Restore/replay still awaits larger host or explicit owner-authorized
   protected strategy (see
   `docs/perf/checkpoint-restore-replay-capacity-blocker-2026-08-01.md`).

Until capacity is remediated and the soak+rollback assertions actually PASS,
the golden 4h gate remains **open** and blocked. Repository-side
`pending_acceptance` stays exactly unchanged. Exactly four
production-acceptance gates remain.
