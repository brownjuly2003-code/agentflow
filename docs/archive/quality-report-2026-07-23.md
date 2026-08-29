# AgentFlow Quality Report

> **Archive metadata**
>
> - Original path: *docs/quality.md*
> - Archived: 2026-08-29
> - Reason: this host- and time-dependent report was replaced by a deterministic
>   current quality-gate reference; byte-for-byte regeneration is not portable
>   across local artifact sets or hosts
> - Current replacement: [quality gates](../quality.md); new local snapshots are
>   written by [`scripts/quality_report.py`](../../scripts/quality_report.py) to
>   ignored runtime artifacts
> - Content type: historical generated quality snapshot
>
> The report body below is unchanged; only this provenance block was added.

- Generated: `2026-07-23T09:59:55+00:00`
- Generator: `python scripts/quality_report.py --skip-docker --skip-dependency-scans`

## Enforced Gates
- Project coverage floor: 60%
- Patch coverage floor: 80%
- Critical-module coverage floor: 90%
- MkDocs strict build: required

## Test Suites
- Unit: 2096 collected (pytest --collect-only)
- Integration: 380 collected (pytest --collect-only)
- E2E: 27 collected (pytest --collect-only)
- Property-based: 13 collected (pytest --collect-only)
- Contract: 17 collected (pytest --collect-only)
- Chaos: 8 collected (pytest --collect-only)
- Coverage: 80.02% line coverage (9830/12284 lines, source `coverage.xml`)
- Property detail: Hypothesis profiles: ci=200, dev=50
- Chaos latest run: 5 passed, 0 failed, 0 errors (source `.artifacts/chaos/ci-chaos-summary.json`)

## Security
- Bandit: PASS - 0 medium/high finding(s) (`python -m bandit ...`)
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
- sql_guard.py: WARN - no scored mutants yet (threshold 90%); missing mutation data: D:\DE_project\mutants\serving\semantic_layer\sql_guard.py.meta
- rate_limiter.py: WARN - no scored mutants yet (threshold 90%); missing mutation data: D:\DE_project\mutants\serving\api\rate_limiter.py.meta
- sql_builder.py: WARN - no scored mutants yet (threshold 90%); missing mutation data: D:\DE_project\mutants\serving\semantic_layer\query\sql_builder.py.meta
- nl_queries.py: WARN - no scored mutants yet (threshold 90%); missing mutation data: D:\DE_project\mutants\serving\semantic_layer\query\nl_queries.py.meta
- manager.py: WARN - no scored mutants yet (threshold 80%); missing mutation data: D:\DE_project\mutants\serving\api\auth\manager.py.meta
- key_rotation.py: WARN - no scored mutants yet (threshold 90%); missing mutation data: D:\DE_project\mutants\serving\api\auth\key_rotation.py.meta
- Overall: killed=15, survived=5, total=20 (source `mutants/mutmut-cicd-stats.json`)

## Notes
- Missing tools or fresh artifacts are reported explicitly instead of placeholders.
- This report uses local repo state plus the newest local quality artifacts it can find.

_Last updated automatically by `scripts/quality_report.py` at `2026-07-23T09:59:55+00:00`._
