# Golden canary2 FIX4 — kind residual PASS (D+C1-20)

- **Run window (UTC):** `2026-08-07T12:06:14Z`–`2026-08-07T12:08:10Z`
- **Result:** **`PASS_KIND_RESIDUAL_20`**
- **Contract:** D+C1-20 kind canary = residual-after-produce ≤ **20 s**
- **Context / namespace:** `kind-agentflow-reverify-ed03fc47` / `agentflow`
- **Task id / identity:** `golden-4h-canary2-fix4-rv-20260807-01` (**CONSUMED**)

## Claim boundary

This is **kind-tier residual** canary evidence only. It is **not**:

- dual mean ≥ 90 PASS (`applied_mean_eps` telemetry was **77.9059**)
- 4h soak PASS
- Helm rollback PASS
- production acceptance

Production status remains **`candidate`**. The open acceptance item remains the
full **4h soak + rollback rehearsal** until that run completes.

Full runtime packet (untracked task dir):
`.codex-grok-tasks/canary2-fix4-runtime-20260807-01/`.

## Independently recorded facts

| Check | Result |
| --- | --- |
| Coschedule (verify before producer) | PASS |
| Producer 2000 @ 100 | PASS delivered 2000, elapsed ~20.08 s |
| Residual after produce | **7.5127 s** ≤ 20 |
| Exactness Kafka/Iceberg/CH | 2000/2000, DLQ 0, lags 0 |
| Flink JID | `0d583c79169ff18cc25f905bd09eb0f3` |
| Failed checkpoint baseline | 1 (delta 0) |

## Product contract note

Owner-selected **D + C1-20**: kind residual canary unlocks kind-tier path
progress; golden dual mean≥90 remains the soak/golden SLA for full acceptance.
