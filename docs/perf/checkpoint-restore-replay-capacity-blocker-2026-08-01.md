# Checkpoint restore/replay — capacity blocker (2026-08-01)

**Date:** 2026-08-01
**Result:** **UNSAFE_CAPACITY** first attempt; capacity change
**BLOCKED_BEFORE_MUTATION**; alternate non-protected reclaim assessment
**INSUFFICIENT_NON_PROTECTED_RECLAIM** (gate not re-run; restore/replay
**not** accepted)
**Context / namespace:** `kind-agentflow-golden-36ed1ec` / `agentflow`
**SSH alias:** `deproject-mac`
**Evidence commit status:** recorded in local evidence commit
`3fb5eeec2fd35b2a66867f5c89370dc2a8bd8856` (`docs: record restore capacity blocker`;
local-only, unpushed). That SHA is evidence documentation only — **not** a
runtime or Operator-accepted SHA. Pre-evidence local base remains
`96b7a7a82bd800f0cdd94942577dc41f848fa88d` (local-only, unpushed; **not** current HEAD).
Pre-addendum local base before this capacity-change documentation:
`6fcfac424d7fe7f7beee85d050aee828d775916b` (local-only, unpushed, ahead 5).
Current local HEAD before this alternate-assessment documentation sync:
`d016ffd6f2de198ad986f571551bf981718cccde` (local-only, unpushed, ahead 6).
**Runtime source / Operator base:** `ed03fc47` / `36ed1ec`
**Task id:** `chk-restore-20260801-01`

Control artifacts (local only):
`.codex-grok-tasks/checkpoint-restore-replay-20260801/`
(`runtime-result.md`, `recovery-result.md`, `protected-recovery-result.md`,
`capacity-change-result.md`, `alternate-capacity-assessment.md`).

Plan pointer: `checkpoint-restore-replay-gate.md`.

## Claim boundary

This note records a **failed first attempt**, **task-only cleanup**,
**protected recovery**, **independent recovery verification**, a
**read-only first capacity preflight**, a later authorized
**capacity-change attempt stopped before mutation**
(`BLOCKED_BEFORE_MUTATION`), and a completed read-only
**alternate non-protected reclaim assessment**
(`INSUFFICIENT_NON_PROTECTED_RECLAIM`).

It is **not** checkpoint restore/replay acceptance. It does **not** prove
savepoint restore, Kafka dedup of `(tenant_id, event_id)`, or lake-to-serving
exactness after restore. E1/E2 counts remain **zero**; TTL **never started**.
Capacity preflight, protected recovery, alternate capacity assessment, and
later health snapshots are **not** acceptance PASS.

Repository-side `pending_acceptance` is unchanged:

1. `checkpoint restore and replay acceptance`
2. `4h soak and rollback rehearsal on the golden topology`

Exactly four production-acceptance gates remain overall (restore/replay,
fresh 4h soak+rollback, external pentest, npm approval). Product status
remains **`candidate`**. No score raised. No tracked code/product change.
No push.

## What was attempted

Isolated live gate for savepoint restore + no-duplicate
`(tenant_id, event_id)` on a task-owned FlinkDeployment beside the protected
`agentflow-stream-processor`:

| Item | Value |
| --- | --- |
| Task FlinkDeployment | `agentflow-chk-restore-20260801-01` |
| Input topic | `orders.raw.chk-restore-20260801-01` |
| Consumer group | `agentflow-chk-restore-20260801-01` |
| Planned E1/E2 | `...0001` / `...0002` (never produced) |
| Task JM/TM memory (final attempt) | `768m` + explicit Flink memory keys |
| Host path | `/var/agentflow-task-state/chk-restore-20260801-01` |

Sequence attempted: absence/baseline → topic → task Flink apply → (intended)
E1 → checkpoint/savepoint → replay E1+E2 → J2 restore assertions.

## What passed

| Step | Outcome |
| --- | --- |
| Fresh absence / dual-identity baseline | **PASS** — `baseline_all_zero=1` for both planned identities across Kafka validated/DLQ, Iceberg, CH pipeline/orders, API entity |
| Task isolation | Task CR/topic/hostPath created only under task names; protected CR/Helm/SA not intentionally patched during the gate attempt |
| Task-only cleanup | FlinkDeployment `agentflow-chk-restore-20260801-01` deleted; task JM/TM pods gone (`NotFound`) |
| Protected recovery | One operator-native merge patch: `spec.restartNonce` absent/null → `1` |
| Independent recovery verification | Protected CR STABLE / job RUNNING; JM+TM Ready restarts 0; REST 2/2; checkpoints progressed |

## What failed / was not run

| Assertion group | Status |
| --- | --- |
| Task J1 STABLE/RUNNING long enough for E1 | **FAIL** — job `1d32d11ecf7f0dc39b6a13304d497752` reached partial CREATED only |
| Produce E1 / E2 | **NOT RUN** — source topic end offset **0** |
| Checkpoint → savepoint suspend → replay → J2 | **NOT RUN** |
| REST restored evidence / source offset 3 / lag 0 | **NOT RUN** |
| Final dual-identity Kafka/Iceberg/CH/API exactness | **NOT RUN** |
| Dedup TTL window | **never started** (E1 never accepted) |

Root cause of the first attempt: Kind node memory exhaustion when scheduling a
second Flink application (task JM+TM) beside protected JM+TM and the existing
lake/serving stack on a ~5924 MB node.

## Unintended protected TM loss and exact recovery

### Incident (unintended side effect)

During the task Flink attempt the protected TaskManager was killed. Protected
FlinkDeployment transitioned to `lifecycleState=FAILED` /
`jobStatus.state=FAILED` for physical job
`0171cd969b5b300199c83dca620bd620` with operator error
`Job recovery is not needed.` No protected resource was intentionally patched
during the gate attempt itself.

### Task-only pressure relief

Authorized delete of task FlinkDeployment only. After deletion, available
memory rose modestly (~1191–1223 MB), but protected stayed FAILED/FAILED for
180 s with no Ready TM and no auto-resubmit (`resourceVersion` unchanged).

### Authorized recovery (exactly one mutation)

| Item | Value |
| --- | --- |
| Mutation | single merge patch `{"spec":{"restartNonce":1}}` |
| Before | `spec.restartNonce` absent/null; job `0171cd969b5b300199c83dca620bd620` FAILED |
| After | `spec.restartNonce=1`; new physical job `61e8042c8422974091cc3cad20f07380` |
| CR UID | unchanged `0622bd9c-3cec-410c-b778-78440a3c0ba9` |
| Helm release | revision **2** / deployed (unchanged) |
| ServiceAccount UID | unchanged `a8f4ebd8-53de-4680-b89d-83d0114db852` |
| Second nonce bump / Helm upgrade / CR delete | **not** performed |

Recovery hold (Grok): STABLE/RUNNING, Ready JM+TM restarts 0, REST RUNNING 2/2,
checkpoints completed progressed (failed 0) within budget + 60 s hold.

## Independent recovery verification (Codex after Grok)

Authoritative post-recovery snapshot (independent of the recovery executor):

| Field | Observed |
| --- | --- |
| Protected CR UID | `0622bd9c-3cec-410c-b778-78440a3c0ba9` |
| Generation | `2` |
| `spec.restartNonce` | `1` (live) |
| lifecycle / job status | `STABLE` / `RUNNING` |
| Physical job ID | `61e8042c8422974091cc3cad20f07380` |
| Protected JM / TM | both Ready, restarts `0` |
| REST job | RUNNING, tasks `2/2` |
| Checkpoints | completed `10`, failed `0`, latest `chk-10` |
| Helm | revision `2` / deployed |
| ServiceAccount UID | `a8f4ebd8-53de-4680-b89d-83d0114db852` |
| Task FlinkDeployment | **absent** |
| Task topic | `orders.raw.chk-restore-20260801-01` still exists; partition 0 end offset **0** |
| E1/E2 | **never produced** |

Physical job ID changed as required by the resubmit. Live `restartNonce=1`
remains. Helm revision stayed 2. This verifies protected health only — **not**
restore/replay.

## Measured capacity math and safe retry threshold

### First-attempt capacity preflight (earlier read-only; pre-capacity-change)

Read-only capacity preflight verdict: **`UNSAFE_CAPACITY`** for a second
concurrent task Flink with **768m JM + 768m TM** while protected Flink remains
live on the current ~5924 MB Kind node.

| Measure | Value |
| --- | ---: |
| Node total | ~5924 MB |
| Current available memory | ~710–742 MB |
| Clear task-owned reclaim (bridge + task API RSS) | ~168 MB |
| Optimistic total if ownership-ambiguous materializer included | ~259 MB |
| Conservative pre-apply available target | ~1.9–2.0 GiB |
| Measured best-case deficit vs target | ~0.9–1.0 GiB |

Implications recorded at that time:

- Protected can remain untouched **only if** the second Flink is **not**
  started under current capacity.
- Smallest preferred remediation: increase Kind/Docker capacity by **at least
  ~1.5 GiB**, then freshly remeasure available **≥ 1.9–2.0 GiB**.
- Alternatives that shrink protected footprint or suspend the protected runtime
  require **explicit owner authorization**.
- Capacity increase / protected suspension had **not** been performed at that
  measurement.

### Authorized capacity-change attempt — `BLOCKED_BEFORE_MUTATION`

Local control evidence (not acceptance):
`.codex-grok-tasks/checkpoint-restore-replay-20260801/capacity-change-result.md`.

**Verdict:** `BLOCKED_BEFORE_MUTATION`. No memory setting changed; no
Colima/Docker restart; no recovery, rollback, container start/stop, Flink
patch, Helm change, or data mutation.

| Item | Value |
| --- | --- |
| Physical Mac RAM (`sysctl hw.memsize`) | `8589934592` bytes = **exactly 8 GiB** |
| Docker runtime | **Colima 0.10.1** (not Docker Desktop; Docker.app absent) |
| Colima configured memory | `memory: 6` GiB (**unchanged**) |
| `docker info` Total Memory | `6212595712` bytes ≈ **5.786 GiB** (**unchanged**) |
| Host swap pressure (Grok preflight) | total ~5120 MiB, used ~4186 MiB; free pages ~70 MiB |

Separate Kind available-memory observations (volatile; **do not average**):

| Observation | Method | Value | vs ≥1.9 GiB target |
| --- | --- | ---: | --- |
| Grok capacity-change preflight | Kind node `stats/summary` `availableBytes` | `1825648640` (~**1.700 GiB**) | **fail** |
| Later independent Codex read | Kind node `/proc/meminfo` | `MemTotal=6066988 kB`; `MemAvailable=676900 kB` (~**0.646 GiB**) | **fail** |

Both observations fail the safety threshold independently.

Why preferred +≥1.5 GiB was rejected: authorized growth toward 8192 MiB would
set Colima to **7.5–8.0 GiB** of an **8 GiB** host, leaving **≤0.5 GiB** (or
**0 GiB**) for macOS under existing heavy swap pressure. Preferred memory
growth is **not clearly safe / impossible** on this host. **No mutation
performed.**

### Fresh independent post-task health (Codex after capacity preflight; health only)

Not acceptance. Restore/replay was **not** retried. E1/E2 remain unproduced;
TTL never started.

| Field | Value |
| --- | --- |
| Protected CR UID | `0622bd9c-3cec-410c-b778-78440a3c0ba9` |
| generation / `restartNonce` | `2` / `1` |
| lifecycle / job | `STABLE` / `RUNNING` |
| physical job ID | `61e8042c8422974091cc3cad20f07380` |
| JM / TM | both Ready, restarts `0` |
| REST | RUNNING, vertices `2/2` |
| Checkpoints | completed `85`, failed `0`, latest `chk-85` |
| Helm / SA UID | rev `2` deployed / `a8f4ebd8-53de-4680-b89d-83d0114db852` unchanged |
| Task FlinkDeployment | **absent** |
| Task topic end offset | partition 0 end offset **0** |
| Supporting services | Kafka, Redis, Flink operator, API, serving bridge, lake materializer, ClickHouse, Iceberg REST, MinIO healthy/running |

Earlier independent recovery verification recorded checkpoints completed `10` /
latest `chk-10`; the capacity-change baseline observed completed `76` /
latest `chk-76`; this post-task health snapshot records completed `85` /
latest `chk-85`. These are separate timed observations of a live progressing
job, not contradictions.

### Alternate non-protected reclaim assessment — `INSUFFICIENT_NON_PROTECTED_RECLAIM`

Local control evidence (not acceptance):
`.codex-grok-tasks/checkpoint-restore-replay-20260801/alternate-capacity-assessment.md`.

**Assessment time:** `2026-08-01T15:40:56Z` (Grok read-only investigation).
**Verdict:** `INSUFFICIENT_NON_PROTECTED_RECLAIM`.
**Mutations:** **zero** — no stop/start/scale/patch/delete/apply/produce/
consume/restart/cleanup; protected Flink untouched.

Fresh Grok Kind memory observations (volatile; **do not average**; use the
**lower defensible** value for conservative decisions):

| Method | Value | vs ≥1.9–2.0 GiB target |
| --- | ---: | --- |
| `/proc/meminfo` `MemAvailable` (**lowest fresh defensible**) | `546740 kB` ≈ **0.521 GiB** | **fail** |
| Node `stats/summary` `availableBytes` | `1865945088` ≈ **1.738 GiB** | **fail** |

Fresh Grok external Docker working sets:

| Container | Working set |
| --- | ---: |
| Kind control-plane | **4.026 GiB** |
| ClickHouse e2e | **581.1 MiB** |
| Iceberg REST | **157.5 MiB** |
| MinIO | **88.21 MiB** |

Candidate Sets A–D (task API / bridge / materializer / ClickHouse / Iceberg
REST / MinIO combinations; protected Flink + Kafka not reclaimable) **all fail**
the ≥1.9–2.0 GiB pre-apply threshold from the 0.521 GiB baseline:

| Set | Conservative reclaim (70% WS) | Projected available | ≥1.9 GiB? |
| --- | ---: | ---: | --- |
| A (API + bridge) | ~0.115 GiB | **0.636 GiB** | **no** |
| B (A + materializer) | ~0.172 GiB | **0.693 GiB** | **no** |
| C (B + ClickHouse) | ~0.568 GiB | **1.089 GiB** | **no** |
| D (C + Iceberg REST + MinIO) | ~**0.737 GiB** | **~1.258 GiB** | **no** |

Even maximum Set D **raw 100%** reclaim projects only
`0.521 + ~1.053 = ~1.574 GiB` — still **below 1.9 GiB**.

Dependency fact (does not create free memory): task J1/J2 itself needs Kafka +
Flink operator; downstream exactness requires materializer/bridge plus
Iceberg/MinIO, ClickHouse, and task API after they return. Phase ordering
cannot solve the missing peak dual-Flink memory.

Protected Flink during Grok assessment (health only; **not** acceptance):

| Field | Value |
| --- | --- |
| CR UID | `0622bd9c-3cec-410c-b778-78440a3c0ba9` |
| generation / `restartNonce` | `2` / `1` |
| lifecycle / job | `STABLE` / `RUNNING` |
| physical job ID | `61e8042c8422974091cc3cad20f07380` |
| JM / TM | Ready, restarts `0` |
| REST | RUNNING, vertices `2/2` |
| Checkpoints | completed `151`, failed `0`, latest `chk-151` |
| Helm / SA UID | rev `2` / `a8f4ebd8-53de-4680-b89d-83d0114db852` |
| Task FlinkDeployment | **absent** |
| Task topic end offset | partition 0 end offset **0** |

### Independent Codex follow-up (later fresh snapshot; sensitivity only)

Later independent Codex read (separate timed snapshot; **do not average** with
Grok assessment values; **not** a new executable plan):

| Item | Value |
| --- | ---: |
| Kind `/proc/meminfo` | `MemTotal=6066988 kB`; `MemAvailable=582628 kB` ≈ **0.556 GiB** |
| Docker Kind WS | **4.1 GiB** |
| Docker ClickHouse WS | **550.5 MiB** |
| Docker Iceberg REST WS | **159.7 MiB** |
| Docker MinIO WS | **87.41 MiB** |

Combining this later 0.556 GiB baseline with the fresh external containers plus
Grok-measured/derived eligible task API (~97.1 MiB), materializer (~83.1 MiB),
and bridge (~71 MiB) still gives only about **1.58 GiB** even with **100% raw**
reclaim — still **below 1.9 GiB**. Independent confirmation of insufficiency.

Protected CR/job identities **unchanged** in the later Codex snapshot; pods
Ready restarts `0`; REST RUNNING `2/2`; checkpoints completed `166` / failed
`0` / latest `chk-166`; Helm rev `2`; SA UID unchanged; task CR **absent**;
task topic end offset `0`. Health only — **not** restore/replay acceptance.

## Leftover task resources (safe cleanup candidates)

Left intentionally after task CR delete and protected recovery (evidence /
non-critical unless re-used):

| Resource | State |
| --- | --- |
| Task FlinkDeployment `agentflow-chk-restore-20260801-01` | **absent** |
| Topic `orders.raw.chk-restore-20260801-01` | present; end offset 0 |
| Baseline Job `agentflow-chk-restore-baseline-20260801-01` | retained (Completed; not memory-critical) |
| hostPath `/var/agentflow-task-state/chk-restore-20260801-01` | may remain on Kind node |
| Remote dir `/tmp/agentflow-chk-restore-20260801-01` | may remain on Mac |
| Local control dir `.codex-grok-tasks/checkpoint-restore-replay-20260801/` | present |

Do **not** delete protected CR/Helm/SA/Kafka/Redis/materializer or recreate the
Kind cluster as cleanup for this gate.

Bounded task-only cleanup (owner-timed; never touch protected):

```text
ssh deproject-mac "/usr/local/bin/kubectl --context kind-agentflow-golden-36ed1ec -n agentflow delete job agentflow-chk-restore-baseline-20260801-01 --ignore-not-found"
ssh deproject-mac "/usr/local/bin/kubectl --context kind-agentflow-golden-36ed1ec -n agentflow delete job agentflow-chk-restore-producer-first-20260801-01 --ignore-not-found"
ssh deproject-mac "/usr/local/bin/kubectl --context kind-agentflow-golden-36ed1ec -n agentflow delete job agentflow-chk-restore-producer-replay-20260801-01 --ignore-not-found"
ssh deproject-mac "/usr/local/bin/kubectl --context kind-agentflow-golden-36ed1ec -n agentflow delete job agentflow-chk-restore-verify-20260801-01 --ignore-not-found"
ssh deproject-mac "/usr/local/bin/kubectl --context kind-agentflow-golden-36ed1ec -n agentflow delete job agentflow-chk-restore-e1-accept-20260801-01 --ignore-not-found"
ssh deproject-mac "/usr/local/bin/kubectl --context kind-agentflow-golden-36ed1ec -n agentflow exec deploy/kafka -- /usr/bin/kafka-topics --bootstrap-server kafka:9092 --delete --topic orders.raw.chk-restore-20260801-01"
ssh deproject-mac "/usr/local/bin/docker exec agentflow-golden-36ed1ec-control-plane rm -rf /var/agentflow-task-state/chk-restore-20260801-01"
ssh deproject-mac "rm -rf /tmp/agentflow-chk-restore-20260801-01"
```

## Exact next decision

**Preferred Docker/Colima memory growth is impossible on this 8 GiB host.**
Non-protected choreography alone is now **decisively insufficient**
(`INSUFFICIENT_NON_PROTECTED_RECLAIM`). Gate remains **open** and
capacity-blocked. Do **not** raw-retry J1. Do **not** execute Sets A–D as a
capacity fix.

1. Restore/replay needs either a **larger host** (reopen preferred +≥1.5 GiB
   Colima growth with safe macOS headroom) **or** explicit **owner
   authorization** for a protected shrink/suspend/single-Flink strategy with
   written rollback.
2. Next **independent safe audit item** (while restore/replay stays blocked
   awaiting owner/capacity decision): **fresh golden-topology 4h soak +
   rollback preflight/execution**.
3. Optionally clean leftover task topic/Jobs/hostPath (task-only; never
   protected).
4. Before any future restore re-run: re-confirm protected STABLE/RUNNING,
   `restartNonce=1`, job `61e8042c8422974091cc3cad20f07380` (or a later
   authorized job id), Helm rev 2, SA/CR UIDs unchanged, and proven available
   memory ≥1.9–2.0 GiB.
5. Only then re-run the isolated restore/replay gate under proven capacity.

Until capacity is remediated and restore/replay assertions actually PASS,
the gate remains **open** and blocked. Repository-side `pending_acceptance`
stays exactly unchanged. Exactly four production-acceptance gates remain.
