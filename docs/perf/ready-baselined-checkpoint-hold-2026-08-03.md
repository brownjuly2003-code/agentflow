# Ready-baselined checkpoint hold — PASS

- **Run window (UTC):** `2026-08-03T15:46:34Z`–`2026-08-03T16:02:05Z`
- **Result:** **`RUNTIME_HOLD_PASS`** / JSON `result=PASS`
- **Mode:** 15-minute read-only readiness-baselined hold
- **Context / namespace:** `kind-agentflow-reverify-ed03fc47` / `agentflow`
- **FlinkDeployment:** `agentflow-soak-rv-stream-processor`
- **Existing JID:** `29d4f78ea965771e7769e5a3726f5c4e`

## Claim boundary

This report records a PASS for the readiness-baselined checkpoint hold only.
It proves that the already-running job stayed healthy after an admitted,
JobManager-attributed startup checkpoint failure. It does not prove canary2,
the four-hour soak, rollback, external penetration testing, or production
acceptance. Production remains `candidate`, and the repository-side pending
item remains `4h soak and rollback rehearsal on the golden topology`.

The earlier canary result
[`FAIL_CANARY_CATCHUP_RATE_FLOOR`](golden-4h-soak-canary-failure-2026-08-02.md)
remains the latest traffic attempt. No traffic ran during this hold.

## Acceptance evidence

| Metric | Baseline | Final | Delta | Required |
| --- | ---: | ---: | ---: | ---: |
| Completed checkpoints | `7675` | `8614` | `939` | at least `837` |
| Failed checkpoints | `1` | `1` | `0` | never increase |
| Elapsed seconds | — | `930` | — | at least `900` |
| Persisted samples | — | `11` | — | hold sampling contract |

The baseline admitted exactly one existing failed checkpoint only after the
JobManager log attributed it to `NOT_ALL_REQUIRED_TASKS_RUNNING`. The hold
kept deployment/job/task readiness, pod readiness and restart counts, Helm,
Kafka, ClickHouse, identity, and canonical-spec invariants fail closed. The
final evidence records `read_only=true`, `runtime_mutation=false`, and
`traffic_started=false`.

## Execution and exactly-once boundary

The frozen packet was staged under the previously absent remote directory
`/tmp/agentflow-ready-baselined-checkpoint-hold-20260803-03`. All five packet
files matched their local SHA-256 values before the runner was invoked exactly
once.

The first SSH tool call timed out while that runner remained active. That
transport timeout was not treated as a runtime verdict and did not trigger a
retry. A bounded monitor observed the same PID until natural exit, then copied
the terminal evidence. Independent verification confirmed the PID was absent,
the final JSON said `PASS`, and remote/local hashes matched.

## Canonical terminal evidence

The immutable control copy is under
`.codex-grok-tasks/ready-baselined-checkpoint-hold-20260803-03/`.

| File | SHA-256 |
| --- | --- |
| `ready-baseline-20260803-03.json` | `a63360f67d40488328e4d38ee530f3d4374fac3f4d27ad65160d65fdb1252d4b` |
| `hold-samples-20260803-03.jsonl` | `18bca6117fd267760389bc742bf348016410c70ead3a572db4bfb0a16e428024` |
| `hold-result-20260803-03.json` | `cfa518fc5ac905ab3a12652e99959413329e410fff5d5d259697eaa445a68d91` |

Only these terminal hashes support the PASS claim. An incomplete timeout-era
copy and a later nonterminal samples hash are transient snapshots and are not
acceptance evidence.

## Safety and next gate

- No retry, Kubernetes mutation, Helm action, traffic, nonce, new JID,
  canary2, soak, rollback, cleanup, commit, or push occurred in the runtime
  hold.
- The failed `20260803-02` packet and evidence remain immutable FAIL evidence.
- Packet, stage, and evidence `20260803-03` must not be rerun, restaged,
  overwritten, cleaned, reused, or refreshed.
- Canary2, the four-hour soak, corrected rollback rehearsal, push, and external
  penetration testing are separate gates with their own preconditions and
  authorization.
