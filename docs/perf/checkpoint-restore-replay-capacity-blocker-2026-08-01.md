# Checkpoint restore/replay — capacity blocker (2026-08-01)

**Date:** 2026-08-01
**Result:** **UNSAFE_CAPACITY** (gate not re-run; restore/replay **not** accepted)
**Context / namespace:** `kind-agentflow-golden-36ed1ec` / `agentflow`
**SSH alias:** `deproject-mac`
**Evidence commit status:** recorded in local evidence commit
`3fb5eeec2fd35b2a66867f5c89370dc2a8bd8856` (`docs: record restore capacity blocker`;
local-only, unpushed). That SHA is evidence documentation only — **not** a
runtime or Operator-accepted SHA. Pre-evidence local base remains
`96b7a7a82bd800f0cdd94942577dc41f848fa88d` (local-only, unpushed; **not** current HEAD).
**Runtime source / Operator base:** `ed03fc47` / `36ed1ec`
**Task id:** `chk-restore-20260801-01`

Control artifacts (local only):
`.codex-grok-tasks/checkpoint-restore-replay-20260801/`
(`runtime-result.md`, `recovery-result.md`, `protected-recovery-result.md`).

Plan pointer: `checkpoint-restore-replay-gate.md`.

## Claim boundary

This note records a **failed first attempt**, **task-only cleanup**,
**protected recovery**, **independent recovery verification**, and a
**read-only capacity preflight**.

It is **not** checkpoint restore/replay acceptance. It does **not** prove
savepoint restore, Kafka dedup of `(tenant_id, event_id)`, or lake-to-serving
exactness after restore. E1/E2 counts remain **zero**; TTL **never started**.

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

Implications:

- Protected can remain untouched **only if** the second Flink is **not**
  started under current capacity.
- Smallest preferred remediation: increase Kind/Docker capacity by **at least
  ~1.5 GiB**, then freshly remeasure available **≥ 1.9–2.0 GiB**.
- Alternatives that shrink protected footprint or suspend the protected runtime
  require **explicit owner authorization**.
- Capacity increase / protected suspension has **not** been approved or
  performed in this note.

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

**Owner/capacity decision first — not a raw retry.**

1. Choose one authorized path:
   - prefer: grow Kind/Docker capacity ≥ ~1.5 GiB and remeasure available
     ≥ 1.9–2.0 GiB with protected still live; **or**
   - owner-authorized protected footprint reduction / temporary suspend of
     protected runtime (explicit only).
2. Optionally clean leftover task topic/Jobs/hostPath (task-only).
3. Re-confirm protected STABLE/RUNNING, `restartNonce=1`, job
   `61e8042c8422974091cc3cad20f07380` (or note a later authorized job id),
   Helm rev 2, SA/CR UIDs unchanged.
4. Only then re-run the isolated restore/replay gate under proven capacity.

Until capacity is remediated and restore/replay assertions actually PASS,
the gate remains **open** and blocked.
