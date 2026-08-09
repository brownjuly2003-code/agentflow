# Golden 4h soak-05 — SOAK_FAIL (terminal Flink health)

- **Identity:** `golden-4h-soak-rv-20260807-05`
- **Context / namespace:** `kind-agentflow-reverify-ed03fc47` / `agentflow`
- **Producer window (UTC):** `2026-08-07T22:40:32.084Z` start → complete after
  `14,400.030287 s` (~`2026-08-08T02:40:32Z`)
- **Terminal health window (UTC):** Flink job `FAILED` by sample
  `2026-08-08T02:47:08.433486Z`; dual-mean ABORT text preserved at
  `2026-08-08T02:49:11.465889Z`
- **Read-only final investigation (UTC):** `2026-08-09` (unchanged Mac stand)
- **Raw emitted result:** **`SOAK_FAIL`**
  (`RESULT=SOAK_FAIL outcome=failed` in
  `/tmp/agentflow-soak-runtime-20260807-05/result-final.txt`)
- **Diagnostic classification (docs only, not a runtime emit):**
  **`UNRESOLVED_FLINK_TERMINAL_FAILURE`**
- **Soak verify contract:** `dual_mean_90` — no verifier PASS JSON produced
- **Corrected Helm rollback:** **not started**

## Claim boundary

This report records a failed four-hour soak gate after a completed producer.
It is **not**:

- soak PASS;
- dual-mean (`dual_mean_90`) PASS;
- corrected Helm rollback PASS;
- production acceptance.

`production.status` remains **`candidate`**. The combined soak/rollback
acceptance gate remains **open**.

The session-close snapshot
`.codex-grok-tasks/golden-4h-soak-runtime-20260807-05/runtime-result.md`
records mid-run **`SOAK_RUNNING`** only. It is superseded by the final
`result-final.txt` outcome above and must not be treated as the terminal
result.

## Producer facts (PASS) vs overall soak (FAIL)

| Surface | Observed |
| --- | --- |
| Producer attempted | `1,440,000` |
| Producer delivered | `1,440,000` |
| Producer failures | `0` |
| Producer elapsed | `14,400.030287 s` |
| Producer delivered EPS | `99.99979` |
| Producer result | **PASS** |
| Dual-mean verifier | **FAIL** — `result=FAIL reason=ABORT detail=pods_unhealthy ok=True ready=1/1 error=None` |
| Soak verifier PASS JSON | **absent** |
| Overall soak emit | **`SOAK_FAIL`** |

Producer completion alone is **not** soak PASS.

## Observer chronology (persisted JSONL)

Ordering matters: Flink was already terminal before the preserved `1/1`
topology ABORT text.

| Sample | UTC | Observed |
| ---: | --- | --- |
| 244 | `2026-08-08T02:44:33.557834Z` | Flink `RUNNING`, tasks `2/2`, completed checkpoints `1376`, failed checkpoints `0`; Kubernetes pod query had a transient `TimeoutError` |
| 245 | `02:46:04.288524Z` | Flink REST `HTTPError`; pods remained Ready `2/2` |
| 246 | `02:47:08.433486Z` | Flink job state **`FAILED`**, tasks `0/0`; pods still Ready `2/2` |
| 247 | `02:48:10.302454Z` | Flink still `FAILED`; TaskManager gone → Ready `1/1` (first bad topology sample) |
| 248 | `02:49:11.465889Z` | second `1/1` sample preserved ABORT text `pods_unhealthy ok=True ready=1/1 error=None`; Flink had already been `FAILED` for two samples |
| 249 | (next) | five-sample Flink streak also fatal: `flink_unhealthy state=FAILED tasks_running=0/0 error=HTTPError` |

The ABORT text is a **downstream topology symptom and ordering effect**. It is
**not** evidence that `pods_unhealthy` caused the Flink failure.

## Surviving FlinkDeployment status

Read-only status after the failure window:

| Field | Value |
| --- | --- |
| `status.lifecycleState` | `FAILED` |
| `status.jobStatus.state` | `FAILED` |
| Job ID | `3e5e2435dd1575dd5c19ac96041afe1c` |
| `status.jobManagerDeploymentStatus` | `MISSING` |
| Running condition transition | `2026-08-08T02:45:23.476996896Z` |
| Operator status error | `FlinkException: Job recovery is not needed.` |

## Evidence gap (root cause unresolved)

By the 2026-08-09 read-only investigation, JobManager and TaskManager pods,
their logs, and namespace events were **no longer available**. Current operator
log retention did **not** include the failure window. The exact original Flink
task/job exception is therefore **not proven**.

**Root cause classification:** unresolved due to an **evidence-retention gap**.

### Prohibited causal claims

Do **not** infer causality from OOM, Kafka, API, checkpoint, pod, verifier, or
Operator behavior. Those remain unproven for this run.

## Mutation boundary

The 2026-08-09 investigation performed **read-only** status, REST/status,
evidence-file, and log-retention checks only. It did **not**:

- restart Flink;
- create traffic;
- rerun the soak;
- apply or delete Kubernetes resources;
- run Helm;
- commit or push.

## Prerequisite for a future newly identified soak run

Before another newly identified soak identity is authorized, retain
JobManager/TaskManager logs and Flink exception-history evidence across the
failure window. This is **future work**, not a completed implementation and
not authorization to rerun.

## Related historical surfaces

- Kind residual canary prerequisite PASS:
  [golden-4h-canary2-fix4-kind-residual-pass-2026-08-07.md](golden-4h-canary2-fix4-kind-residual-pass-2026-08-07.md)
- Historical `-01` start snapshot (superseded as current soak outcome):
  [golden-4h-soak-start-2026-08-07.md](golden-4h-soak-start-2026-08-07.md)
