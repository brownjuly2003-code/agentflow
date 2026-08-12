# Checkpoint restore/replay acceptance — 2026-08-02

**Date:** 2026-08-02

**Runtime source SHA:** `ed03fc47fa5f411016e588774d61a5b5eef21213`

**Audience:** developers and operations recording live verification evidence

**Result:** **PASS** (isolated checkpoint restore/replay with exact no-duplicate assertions)

## Goal and boundary

Prove on an isolated kind stand that a stateful PyFlink job can process E1,
complete a checkpoint, suspend to a non-empty savepoint, receive a byte-identical
replay of E1 plus a new E2 while suspended, and resume as a distinct job from
that exact savepoint without duplicating either identity downstream.

The measured path was:

`task source topic` → PyFlink → `events.validated` → {Iceberg; serving bridge →
ClickHouse → API}

This closes the checkpoint restore/replay acceptance gate only. It does not
claim a four-hour soak, Helm rollback, external penetration test, GitHub
Environment approval, or production acceptance. `production.status` remains
`candidate`.

The earlier capacity-blocker report remains the immutable record of the failed
2026-08-01 attempt. This fresh isolated run supersedes that blocker only for the
current restore/replay gate.

### Claimed scope

- fresh baseline proves both target identities absent from Kafka validated and
  DLQ topics, Iceberg, ClickHouse, and the API;
- J1 processes E1 exactly once and completes checkpoint `2`;
- suspension finishes J1 and captures a non-empty savepoint;
- byte-identical E1 plus new E2 are acknowledged while the job is suspended;
- J2 is distinct from J1 and Flink REST reports a restore from the captured
  savepoint;
- E1 and E2 each appear exactly once on every measured lake/serving surface,
  with no DLQ record;
- source-group offset reaches topic end offset `3` with lag `0`;
- the hard `<600 s` acceptance TTL passes at exactly `565 s`.

### Non-goals

- fresh four-hour soak and Helm rollback rehearsal;
- same-SHA runtime acceptance of later local chart/checkpoint configuration
  commits (the measured runtime remains exact `ed03fc47`);
- external penetration-test evidence or GitHub Environment `npm` protection;
- promotion above production candidate.

## Runtime identity

| Item | Value |
|------|-------|
| Cluster | `agentflow-reverify-ed03fc47` |
| Context | `kind-agentflow-reverify-ed03fc47` |
| Namespace | `agentflow` |
| Operator chart/app | `1.15.0` |
| Flink | `2.3.0` |
| Runtime source | `ed03fc47fa5f411016e588774d61a5b5eef21213` |
| Task id | `chk-restore-rv-20260802-02` |
| Source topic | `orders.raw.chk-restore-rv-20260802-02` |
| Source group | `agentflow-chk-restore-rv-20260802-02` |
| Task state path | `/var/agentflow-task-state/chk-restore-rv-20260802-02` |
| JobManager | process `896m`; metaspace `256m` |
| TaskManager | process `768m` |
| Pod state | JM/TM Ready; restarts `0` |

### Event identities

| Event | Event id | Order id | Timestamp |
|-------|----------|----------|-----------|
| E1 | `8c1f16a0-e2e0-4a01-8d02-000000000201` | `ORD-20260802-960201` | `2026-08-02T06:00:00+00:00` |
| E2 | `8c1f16a0-e2e0-4a01-8d02-000000000202` | `ORD-20260802-960202` | `2026-08-02T06:00:01+00:00` |

## Timeline

| UTC | Observation |
|-----|-------------|
| `06:27:35` | Fresh baseline PASS; both identities zero on every measured surface |
| `06:38:02` | Initial E1 producer ACKs partition `0`, offset `0` |
| `06:38:23` | E1 acceptance verifier PASS |
| after E1 | J1 checkpoint `2` completed |
| suspension | J1 `FINISHED`; savepoint captured; TaskManager scaled to zero |
| `06:41:49` | Replay producer ACKs E1 at offset `1` and E2 at offset `2` |
| resume | J2 `STABLE/RUNNING`; REST restore linkage present |
| `06:47:48` | Final exact verifier PASS |
| `06:58:11` | Independent task-only cleanup verification complete |

## Baseline and E1

The baseline verifier returned `result=PASS baseline_all_zero=1`. For E1 and
E2, all of the following were exactly zero before production:

- Kafka `events.validated`;
- Kafka `events.deadletter`;
- Iceberg `agentflow.validated_events`;
- ClickHouse `pipeline_events` and `orders_v2`;
- API entity presence.

After the initial E1 ACK, the E1 acceptance verifier required and observed:

| Surface | E1 count |
|---------|---------:|
| Kafka validated | 1 |
| Kafka DLQ | 0 |
| Iceberg | 1 |
| ClickHouse `pipeline_events` | 1 |
| ClickHouse `orders_v2` | 1 |
| API entity | 1 |
| API timeline | 1 |

J1 was `e843fce0b8b8b5e25a1707272ed5d969`. Its completed checkpoint `2`
was stored at:

```text
file:/mnt/flink-state/checkpoints/e843fce0b8b8b5e25a1707272ed5d969/chk-2
```

## Suspend, replay, and restore

Suspension placed J1 in `FINISHED` and captured:

```text
file:/mnt/flink-state/savepoints/savepoint-e843fc-2d0a0daf156c
```

The savepoint directory contained `11184` bytes; `_metadata` contained `7088`
bytes. While suspended, the replay producer acknowledged byte-identical E1 at
offset `1` and new E2 at offset `2`, bringing the physical topic end offset to
`3`.

J2 was `e1a8c58bc5f747d22c92354f7e90e070`, distinct from J1. Flink REST reported:

- `counts.restored=1`;
- restored checkpoint id `4` with `is_savepoint=true`;
- external path exactly equal to the captured savepoint;
- completed post-restore checkpoint `6` at
  `file:/mnt/flink-state/checkpoints/e1a8c58bc5f747d22c92354f7e90e070/chk-6`;
- a later snapshot with eight completed checkpoints, zero failed, latest id
  `12`.

The source group finished at current offset `3`, log end `3`, lag `0`, with no
active members.

## Final exact assertions

The final verifier independently counted by exact tenant/event/order identity.
For **each** of E1 and E2 it observed:

| Surface | Required | Observed |
|---------|---------:|---------:|
| Kafka validated | 1 | 1 |
| Kafka DLQ | 0 | 0 |
| Iceberg physical match | 1 | 1 |
| ClickHouse `pipeline_events` | 1 | 1 |
| ClickHouse `orders_v2` | 1 | 1 |
| API entity | 1 | 1 |
| API timeline | 1 | 1 |

The verifier returned exact `result=PASS`. The duration from E1 acceptance at
`06:38:23Z` to final PASS at `06:47:48Z` was `565 s`: the hard `<600 s`
criterion passed. The operational `<=540 s` target was missed by `25 s`; that
miss is retained as an optimization signal and does not weaken the written hard
acceptance criterion.

## Independent verification

Codex independently rechecked the runtime result, Job identities and statuses,
completion timestamps, source offsets, savepoint bytes, REST restore linkage,
exact verifier predicates, resource post-state, cleanup marker, and every
control-artifact digest. The local evidence contract returned:

```text
evidence_contract=PASS ttl_seconds=565 j1_distinct_j2=1 exact_surface_assertions=7 cleanup_complete=1 files=7
```

## Provenance hashes (SHA-256)

The source artifacts remain local under
`.codex-grok-tasks/checkpoint-restore-reverify-20260802-02/`.

| Artifact | SHA-256 |
|----------|---------|
| `baseline-verify-job.yaml` | `3D8140C28170194D6B7DEE7D31F3B7957B83623846C6EEA6331EF60A4B52EFE3` |
| `e1-accept-verify-job.yaml` | `E0E8A4BDC6E7B208AA5F09198FE13507B7895EB0701A5A0D5EB0295A12B1E4DF` |
| `flinkdeployment.yaml` | `FAD1542F98980C6A4AC076BB73D8425214C90924B2BA04020858E2E030467038` |
| `producer-first-job.yaml` | `017F899FFF6E01D6A067EA0BE48E2179515D4FE4EA47CD6B99F0B85981B78B63` |
| `producer-replay-job.yaml` | `C97187A3C139038E080C858F96BE9A187D78FE3F95F4463E1A8A123B22231116` |
| `runtime-result.md` | `B03A33C8E3EA1A73596E04686A37034DB486975BCF27F31B74B2EADA382AC20C` |
| `verify-job.yaml` | `7AF4A6C089D51372CF4DF94312421D38C0341A4A5C7E39F02DF13158D1CA5B2D` |

No secrets or ServiceAccount tokens are included in this tracked report.

## Cleanup and post-state

After independent verification, cleanup deleted only the fresh-02
FlinkDeployment/JM/TM, five fresh-02 Jobs, inactive source group, source topic,
and exact task state path. Those runtime objects are no longer recoverable from
the cluster; the local control manifests and this tracked evidence remain.

Post-cleanup checks at `2026-08-02T06:58:11Z` found all fresh-02 objects absent,
`/var=47%`, `MemAvailable=2575508 kB`, default Colima stopped, shared Kafka,
Redis, Iceberg materializer, serving bridge, API, and Flink operator healthy.

## Claim transition

- `production.status` remains `candidate`.
- `production.verified_checkpoint_restore_replay` points to this page.
- Removed from repository-side `pending_acceptance` only:
  `checkpoint restore and replay acceptance`.
- Repository-side `pending_acceptance` now contains only:
  `4h soak and rollback rehearsal on the golden topology`.
- External penetration-test and GitHub Environment `npm` gates retain their
  separately documented tracked status until separate evidence updates them.

The next repository-side production gate is the fresh four-hour soak plus Helm
rollback rehearsal. Do not raise production status from this restore/replay
PASS alone.
