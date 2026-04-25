# 2026-04-24 post-hotfix sprint — three tracks

Sprint context: A01/A06 hotfix + A03 implementation landed on `a3ecd38`. Remaining work sorted into three tracks by priority.

## Current state

- HEAD: `a3ecd38`. Working tree clean.
- Local health-check clean: `ruff check && ruff format --check && mypy src/ --ignore-missing-imports`.
- CI on `a3ecd38`: Contract ✓, E2E ✓, Staging Deploy ✓, Security ✓. **Red:** CI test-integration (iceberg REST catalog 500 — pre-existing infra; T20), Load Test (chronic — thresholds не из замеров; T27).
- A03 CI smoke gate (p99 < 500 ms) passes on local (361 ms p99 after PII fix). Nightly SLO (p99 < 200 ms) — still ~1.8× over.

## Tracks

### Track 1 — Customer release unblock (urgent, 2-4 days)

- **T20** — Fix iceberg REST catalog 500 in test-integration. **P0** unblocks CI green.
- **T21** — v1.1.0-rc1 publish workflow smoke. Verify tag → build → testPyPI/npm pipeline works after A01 rename.
- **T22** — Write v1.1 migration guide (`docs/migration/v1.1.md`).

**Gate to v1.1.0 production tag:** T20 + T21 + T22 all green. Юзер решает момент tag'а, не CX.

### Track 2 — Perf next iteration (2-5 days, sequential)

- **T23** — Fresh flamegraph on `a3ecd38` + perf backlog refresh. Output: next hypothesis selected.
- **T24** — Implement next perf hypothesis (depends on T23). 5% p99 threshold rule.

Loop T23+T24 until nightly SLO reached or diminishing returns.

### Track 3 — Operationalize Q2 decisions (1-2 weeks, infra-heavy)

- **T25** — A04 Debezium + Kafka Connect — research and plan (not implementation).
- **T26** — A05 helm values schema live validation on kind.
- **T27** — Load Test thresholds rework under A03 split-decision. Depends on T23+T24 stable nightly.

## Running notes

- Sequential CX: one task at a time. No parallel CX invocations (cold-start cost).
- Each task ТЗ — self-contained. CX не видит conversation, только свою ТЗ.
- Hybrid Claude + Codex: Claude orchestrates, Codex executes. После каждого commit-batch — юзер или Claude commit-review → push.
- Docker requirement for T25-T27: нужен local Docker / kind. Если infra недоступна — defer.

## Done criteria for this sprint

- Track 1 complete → customer release GO verdict (TA10 refresh).
- Track 2 complete → nightly SLO p99 < 200 ms achievable (or documented infeasibility with evidence).
- Track 3 complete → A04/A05 operationalized, Load Test зелёный на main.
