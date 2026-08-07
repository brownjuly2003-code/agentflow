# Golden 4h soak — START (in progress)

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
production acceptance. `production.status` remains **`candidate`**.

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

## Next

1. Wait producer Complete (~16:22Z UTC).  
2. Watchdog applies soak verify under `dual_mean_90`.  
3. On PASS: corrected rollback to Helm revision **3**.  
4. Publish final soak/rollback evidence and update claims only after outcomes.
