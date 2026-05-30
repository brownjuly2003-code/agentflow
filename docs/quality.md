# AgentFlow Quality Report

- Generated: `2026-05-30T06:17:18+00:00`
- Generator: `python scripts/quality_report.py --skip-docker --skip-dependency-scans`

## Test Suites
- Unit: 571 collected (pytest --collect-only)
- Integration: 216 collected (pytest --collect-only)
- E2E: 23 collected (pytest --collect-only)
- Property-based: 15 collected (pytest --collect-only)
- Contract: 17 collected (pytest --collect-only)
- Chaos: 8 collected (pytest --collect-only)
- Coverage: 67.09% line coverage (5223/7785 lines, source `coverage.xml`)
- Property detail: Hypothesis profiles: ci=200, dev=50
- Chaos latest run: 5 passed, 0 failed, 0 errors (source `.artifacts/chaos/ci-chaos-summary.json`)

## Security
- Bandit: FAIL - 1 medium/high finding(s) (`python -m bandit ...`)
- Safety: SKIP - dependency scan skipped (`--skip-dependency-scans`)
- pip-audit: SKIP - dependency scan skipped (`--skip-dependency-scans`)
- Trivy: SKIP - Docker image scan skipped (`--skip-docker` or `SKIP_DOCKER_TESTS=1`)

## Performance (p95, 50 users, spawn rate 10/s, duration 60s)
- Entity lookup: FAIL - p95 610.0 ms vs threshold 50.0 ms
- NL query: FAIL - p95 690.0 ms vs threshold 500.0 ms
- Batch: FAIL - p95 670.0 ms vs threshold 200.0 ms
- Evidence: source `docs/benchmark-baseline.json`

## Mutation Score
- retry.py: PASS - 75.0% score (15 killed / 20 scored, threshold 75%)
- Overall: killed=15, survived=5, total=20 (source `mutants/mutmut-cicd-stats.json`)

## Notes
- Missing tools or fresh artifacts are reported explicitly instead of placeholders.
- This report uses local repo state plus the newest local quality artifacts it can find.

_Last updated automatically by `scripts/quality_report.py` at `2026-05-30T06:17:18+00:00`._
