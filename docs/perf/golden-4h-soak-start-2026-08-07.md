# Golden 4h soak — START (historical snapshot: identity `-01`)

> **Historical start snapshot only.** This document records the `-01` start
> and mid-run `SOAK_RUNNING` state. It is **not** the latest soak outcome.
> Latest terminal evidence for identity `-05`:
> [golden-4h-soak-05-failure-2026-08-08.md](golden-4h-soak-05-failure-2026-08-08.md)
> (`SOAK_FAIL`; producer PASS; dual-mean ABORT; corrected rollback not started).

- **Start (UTC):** `2026-08-07T12:21:52Z` (preflight) / producer ~`12:22:28Z`
- **Result (this document):** **`SOAK_RUNNING`** — not PASS
- **Context / namespace:** `kind-agentflow-reverify-ed03fc47` / `agentflow`
- **Identity:** `golden-4h-soak-rv-20260807-01`
- **Count / rate:** `1_440_000` @ `100` delivered eps (~4 h produce)
- **Soak verify contract:** `dual_mean_90`
- **Prerequisite canary:** FIX4 kind residual PASS
  ([kind residual report](golden-4h-canary2-fix4-kind-residual-pass-2026-08-07.md))

## Claim boundary

This document records that a full soak was **started** after a kind residual
canary PASS. It does **not** claim soak PASS, mean≥90, rollback PASS, or
production acceptance. `production.status` remains **`candidate`**. For the
later `-05` terminal fail and claim boundary, see
[golden-4h-soak-05-failure-2026-08-08.md](golden-4h-soak-05-failure-2026-08-08.md).

Untracked runtime packet:
`.codex-grok-tasks/golden-4h-soak-runtime-20260807-01/`.

## Start checklist (observed)

| Step | Result |
| --- | --- |
| Capacity soft (availish / disk) | ~2.6 GiB / ~519 GiB free |
| Flink STABLE/RUNNING | JID `0d583c79169ff18cc25f905bd09eb0f3`, failed baseline **1** |
| Baseline zero for soak identity | PASS |
| Observer running | yes (failed-cp baseline-aware) |
| Producer running | yes; early sample ~12k / 120 s @ ~100 eps |
| ABORT | none at start sample |
| Soak verify Job | deferred until producer Complete (watchdog) |
| Helm rollback | not started; target rev **3** if verify PASS |

## Session-close snapshot (2026-08-07, human session ended while RUNNING)

At close (~12:34Z sample): delivered **~72k / 1.44M**, eps **~100**, failures **0**,
ABORT **none**, observer Running, Flink STABLE/RUNNING, verify Job not yet created.
Mac watchdog still waiting for producer Complete.

Full next-session handoff (untracked):
`.codex-grok-tasks/session-close-20260807-soak-running/NEXT_SESSION.md`.

## Next (historical at `-01` start; superseded)

At the time of this `-01` snapshot the planned path was: wait for producer
Complete, apply `dual_mean_90` verify, then corrected rollback to Helm
revision **3** only on PASS. Later identities `-01`…`-05` were attempted;
latest terminal outcome is **`SOAK_FAIL`** for `-05` — see
[golden-4h-soak-05-failure-2026-08-08.md](golden-4h-soak-05-failure-2026-08-08.md).
Do **not** treat this start document as soak PASS or as the current outcome.
