# AgentFlow Quality Report (stale local snapshot)

> This report was generated on 2026-04-12 and does not reflect the current
> test inventory. Collect-only on 2026-04-27 found 676 tests
> (unit 396, integration 202, e2e 18, property 15, contract 8, chaos 8,
> sdk 17). Regenerate with `python scripts/quality_report.py --output docs/quality.md`.

- Generated: `2026-04-12T18:45:16+00:00` (STALE)
- Generator: `python scripts/quality_report.py`

## Test Suites
- Unit: 207 collected (pytest --collect-only)
- Integration: 174 collected (pytest --collect-only)
- E2E: 13 collected (pytest --collect-only)
- Property-based: 15 collected (pytest --collect-only)
- Contract: 13 collected (pytest --collect-only)
- Chaos: 5 collected (pytest --collect-only)
- Coverage: 56.91% line coverage (3499/6148 lines, source `coverage.xml`)
- Property detail: Hypothesis profiles: ci=200, dev=50
- Chaos latest run: 5 passed, 0 failed, 0 errors (source `.artifacts/chaos/ci-chaos-summary.json`)

## Security
- Bandit: FAIL - 1 medium/high finding(s) (`python -m bandit ...`)
- Safety: PASS - 0 known vulnerability entries (`safety check`)
- pip-audit: PASS - 0 known vulnerability entries (`pip-audit`)
- Trivy: WARN - `Dockerfile.api` not found

## Performance (p95, 50 users, spawn rate 10/s, duration 60s)
- Entity lookup: FAIL - p95 26000.0 ms vs threshold 50.0 ms
- NL query: FAIL - p95 40000.0 ms vs threshold 500.0 ms
- Batch: WARN - no load-test sample collected (threshold 200.0 ms)
- Evidence: source `.artifacts/load/results.json`

## Mutation Score
- auth.py: WARN - no scored mutants yet (threshold 80%); 786 problematic mutant(s)
- masking.py: WARN - no scored mutants yet (threshold 80%); 128 problematic mutant(s)
- query_engine.py: WARN - no scored mutants yet (threshold 70%); 372 problematic mutant(s)
- outbox.py: WARN - no scored mutants yet (threshold 70%); 175 problematic mutant(s)
- rate_limiter.py: WARN - no scored mutants yet (threshold 75%); 104 problematic mutant(s)
- Overall: killed=0, survived=0, total=0 (source `mutants/mutmut-cicd-stats.json`)

## Notes
- Missing tools or fresh artifacts are reported explicitly instead of placeholders.
- This report uses local repo state plus the newest local quality artifacts it can find.

_Last updated automatically by `scripts/quality_report.py` at `2026-04-12T18:45:16+00:00`._
