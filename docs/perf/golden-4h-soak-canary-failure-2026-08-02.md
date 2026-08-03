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

At the time of the initial diagnosis, the planned next runtime gate was a clean
corrected rev1/rev2 install, health/checkpoint hold, then fail-closed canary2.
The addendum below supersedes that plan after discovering the reinstall had
already occurred. The 4h producer may start only after exact canary2 PASS.

## Recovery preflight addendum — 2026-08-03

- **Result:** **`BLOCKED_RUNTIME_MIN_PAUSE_NOT_RENDERED`**
- **Read-only observation (UTC):** `2026-08-03T03:56:09Z`
- **Runtime mutation in this addendum:** **none**

The next-turn preflight found that the intended clean reinstall had already
run outside this evidence slice. Helm history was newly based at revision 1
installed and revision 2 deployed at `13:47` remote time (`+03`, approximately
`10:47Z`), after the failed canary. The active recovery state was:

| Surface | Observed state |
|---|---|
| Helm values | checkpoint interval `1000`; JM CPU `0.5`; TM CPU `1`; inert marker `1001` |
| FlinkDeployment | UID `031f8387-3436-4408-bc99-7fbcd58ccfbc`; `STABLE` / `RUNNING` |
| Flink job | JID `1a0c82da8e7f91391a716bb9e8fb8357`; tasks `2/2` running |
| Task pods | JobManager and TaskManager Ready; restarts `0` |
| Checkpoints | completed `2040`, failed `0`, but recent trigger timestamps differ by approximately `30,000 ms` |
| Canary2 | no Jobs and no evidence |

The active CR contains `execution.checkpointing.interval: 1000 ms` but does
not contain `execution.checkpointing.min-pause`. Runtime source `ed03fc47`
predates the tracked chart support that renders this key, so the process keeps
its approximately 30-second effective cadence. A canary whose exact catch-up
budget is only `22.222... s` must not run under that configuration.

The reinstall also replayed the immutable canary1 input from earliest offsets:

- `orders.raw` end offset `2000`;
- `events.validated` end offset `4000`;
- `events.deadletter` end offset `0`;
- source, lake, and serving consumer-group lags all `0`;
- `events.validated` offsets `0` and `2000` contain the same canary1 event id
  `...000000000001`; their enrichment processing times are `10:07:16Z` and
  `10:49:29Z`, respectively.

This is replay evidence, not active traffic, but it proves that another blind
uninstall/reinstall would repeat work and cannot be treated as an idempotent
preflight action. Topics, offsets, evidence, Jobs, and data remain untouched.

Before canary2, a revised authorized runtime pack must explicitly render an
effective checkpoint minimum pause compatible with the 1-second interval
while preserving the pinned-source and rollback contracts. Because the
existing task contract permits exactly 14 memory injections and pins source
`ed03fc47`, that scope expansion is not assumed here. Product status remains
`candidate`; canary2, 4h soak, and rollback remain open.

## Mutation boundary

This evidence slice made no remote or runtime mutation and did not change the
untracked control packs. It triggered no observer, producer, deployment,
release, publish, push, or cleanup action. Credentials and tokens were neither
read nor printed.
