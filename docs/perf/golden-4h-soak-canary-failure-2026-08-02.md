# Golden 4h soak + rollback canary — FAIL

- **Run window (UTC):** `2026-08-02T10:07:07Z`–`2026-08-02T10:07:29Z`
- **Read-only re-verification (UTC):** `2026-08-03T03:37:39Z`
- **Result:** **`FAIL_CANARY_CATCHUP_RATE_FLOOR`**
- **4h soak / observer / rollback:** **NOT STARTED**
- **Context / namespace:** `kind-agentflow-reverify-ed03fc47` / `agentflow`
- **Run-contract source:** `ed03fc47fa5f411016e588774d61a5b5eef21213`
- **Task id:** `golden-4h-soak-rv-20260802-01`

## Claim boundary

This report records a fail-closed 2,000-event canary attempt. It is not 4h soak
evidence, rollback evidence, or production acceptance. The golden topology
remains a production `candidate`, and the repository-side pending item remains
`4h soak and rollback rehearsal on the golden topology`.

The earlier
[resource-capacity preflight](golden-4h-soak-rollback-resource-blocker-2026-08-01.md)
remains accurate for its 2026-08-01 stand and time. It is no longer the latest
attempt state: the later isolated stand reached baseline and canary execution.
The deployed CR exposes image reference `agentflow-flink-local:latest`; the
source SHA above is the task contract, not an immutable registry-digest claim.

## Independently re-verified runtime evidence

Codex used read-only SSH, Kubernetes log, and evidence-file reads. No apply,
delete, Helm mutation, traffic generation, or evidence write occurred.

| Check | Observed result | Gate |
|---|---|---|
| Task Jobs | baseline `Succeeded=1`; producer `Succeeded=1`; verifier `Failed=1` | confirms fail-closed order |
| Zero baseline | Kafka validated `0`, DLQ `0`, Iceberg `0`, ClickHouse pipeline/orders `0/0`, API hits `0` | PASS |
| Producer | attempted/delivered `2000/2000`, failures `0`, target `100 eps` | PASS delivery |
| Producer timing | elapsed `22.544071 s`; delivered `88.715123 eps` | diagnostic: producer rate was already below `90 eps` |
| Canary verifier | `catchup_rate_floor`; ClickHouse pipeline `1092/2000`, orders `546/2000` | FAIL |
| Evidence directory | producer progress/final files only | no canary verifier PASS evidence |
| Later stages | no observer, soak, rev3, rollback, or post-rollback result | NOT STARTED |

The immutable producer final JSON is bound to run/source
`golden-4h-canary-rv-20260802-01`, event prefix
`8c1f16a0-e2e0-4a01-8d05-`, and order prefix `ORD-20260802-805`. Its exact
recorded interval is `22.544071 s`; all 2,000 delivery callbacks succeeded.
The verifier stopped the program before any four-hour traffic because the
required catch-up rate was not met.

## Diagnostic result and recovery boundary

The direct failure path is deterministic. For canary phase, the verifier sets
its exact-catch-up deadline to `producer_start + 2000/90`, or approximately
`22.222 s`. The producer final record ended at `22.544071 s`, so that deadline
had already expired when the first downstream snapshot found pipeline/orders
at `1092/546`. The verifier therefore failed immediately and wrote no PASS
evidence.

Investigation separated that cause and two recorded runtime co-factors instead
of weakening the gate:

1. The task producer performed an unconditional approximately 2.5-second
   callback-drain loop after a successful `flush()`, depressing its recorded
   delivered rate after all callbacks had completed.
2. The canary ran with a 250m TaskManager CPU profile that showed throttling.
3. A 30-second checkpoint interval exposed downstream transactional output in
   bursts longer than the short canary catch-up window.

The local, untracked recovery pack makes only task-harness/profile changes:
one zero-time `poll(0)` after successful flush, checkpoint interval `1000 ms`,
JobManager CPU `0.5`, and TaskManager CPU `1`. Its behavioral flush-latency
test independently passed (`1 passed`) without writing bytecode/cache files.
These corrections are **not runtime-accepted**: no corrected reinstall,
15-minute hold, unique-namespace canary2, soak, or rollback was performed by
this evidence slice.

The next runtime gate is therefore a clean corrected rev1/rev2 install,
health/checkpoint hold, then fail-closed canary2 baseline → producer → verifier
with a new namespace. The 4h producer may start only after exact canary2 PASS.
Remote deployment remains a separate authorized operation.

## Mutation boundary

This evidence slice made no remote or runtime mutation and did not change the
untracked control packs. It triggered no observer, producer, deployment,
release, publish, push, or cleanup action. Credentials and tokens were neither
read nor printed.
