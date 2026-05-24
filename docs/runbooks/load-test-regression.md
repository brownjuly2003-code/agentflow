# Load Test Regression on `main`

**Last updated:** 2026-05-24

## Symptom

GitHub Actions `Load Test` workflow turns red on `main` after being green for
the last 5+ runs. The failure shows one or more endpoint p99 above the gate in
`tests/load/thresholds.py`:

| Endpoint | p99 gate (ms) | Error rate cap |
|----------|---------------|----------------|
| `GET /v1/entity/order/{id}` | 900 | 1% |
| `GET /v1/entity/user/{id}` | 900 | 1% |
| `GET /v1/entity/product/{id}` | 1100 | 1% |
| `GET /v1/metrics/{name}` | 1100 | 1% |
| `POST /v1/query` | 1200 | 5% |
| `POST /v1/batch` | 1200 | 2% |

These gates are 1.3x the 2026-04-25 CI baseline and were intentionally widened
to absorb GHA shared-runner variance — see
`docs/perf/ci-hardware-gap-2026-05-24.md`. A regression past these gates is a
real signal, not noise.

## Severity

Default **Sev 2**. Not customer-facing yet (CI gate, not production), but it
blocks releases and indicates real latency creep. Escalate to **Sev 1** only if
production Grafana shows the same p99 regression — then it is no longer about
the CI gate, it is `api-5xx-spike.md` territory.

## Owner

Author of the most recent change to `src/serving/`, `src/processing/`, or
`tests/load/`. If unclear, Platform on-call holds it until ownership is
assigned.

## Detection

1. Failing run output:
   ```
   gh run view <run-id> --log | grep -E "p99|threshold|FAIL"
   ```
2. Locust HTML report artifact (`load-test-report.html`) — download from the
   failing run. Look at per-endpoint p50/p95/p99 and the request rate.
3. Compare against the last green run on `main`:
   ```
   gh run list --workflow load-test.yml --branch main --limit 10 \
     --json conclusion,headSha,createdAt,databaseId | jq
   gh run download <last-green-id> -n load-test-report
   ```
4. The decision-record in `docs/perf/ci-hardware-gap-2026-05-24.md` is the
   canonical baseline reference. Do not raise gates without updating it.

## Triage

1. **Which endpoint(s)?** A single POST endpoint regressed = backend query
   path. All GETs regressed = ingress / auth / shared-resource issue. Both =
   broad change (deploy of API, pool resize).
2. **Is this transient runner variance?** Check the last 3 Load Test runs on
   `main`. If only this one is red and the previous two were comfortably under
   gate, retry once with the same SHA:
   ```
   gh workflow run load-test.yml --ref main
   ```
   A single re-run that goes green moves this to Sev 3 (capture evidence, file
   follow-up to track if it returns). Two consecutive reds = not variance.
3. **Recent commit?** Diff the failing SHA vs. the last green:
   ```
   git log --oneline <last-green>..<failing> -- src/ tests/
   ```
   Focus on changes to: backends (`src/serving/backends/`), the query engine
   (`src/serving/semantic_layer/query/`), auth middleware (regression in fast
   path), tenant scoping caches (`src/serving/tenant/`), DuckDB pool config.
4. **Memory cache regression?** PII masker `Path(...)` rebuild (commit
   `220f94c`) and tenant qualification cache (`aae27bf`) were both -hundreds
   of ms wins. A regression that undoes one of these will visibly retrace
   the p99 climb in the same direction.

## Mitigation

### Single suspicious commit

```
git revert <commit>
git push origin main
```

This is the fastest fix when the bisect points at a single SHA. The CI gate is
a quality bar; reverting and investigating offline is healthier than landing
"fix it forward" hot-patches under pressure.

### Suspected GHA runner variance, not a real regression

Do **not** silently widen the gate to mask the failure. Instead:

1. Re-run the same SHA twice. If 1/3 fails, this is variance — raise an issue
   to capture the run IDs and consider whether
   `docs/perf/ci-hardware-gap-2026-05-24.md` needs a third re-evaluation
   trigger added.
2. If you must merge while investigating, label the PR `perf-known-flake` and
   add yourself as the owner on the follow-up issue. Do not merge unrelated PRs
   into a known-flaky main — the regression-vs-flake signal gets impossible to
   read.

### Genuine performance regression with no obvious cause

```
# Reproduce locally with the same scenario:
python -m pytest tests/load -m perf_check
# Capture a flamegraph:
python -m pytest tests/load -m perf_check --profile-svg
```

Flamegraphs land in `prof/` (gitignored). Compare against the artifacts in
`docs/perf/` for past baselines. The most common offenders historically were:

- File path / config reload on hot path (commit `220f94c`).
- Per-request tenant lookup not cached (commit `aae27bf`).
- DuckDB connection per request instead of pooled.

## Resolution

1. Two consecutive green Load Test runs on `main`.
2. p99 for every gated endpoint is within budget with margin ≥ 100ms.
3. If the cause was a code change: PR landed with a perf justification in the
   description.
4. If the cause was a baseline drift: `docs/perf/ci-hardware-gap-2026-05-24.md`
   updated with the new measurement and rationale.

## Postmortem trigger

- Mandatory if production Grafana also showed the regression — that means CI
  caught a real customer-impacting drift and the postmortem should explain
  why staging did not catch it first.
- Recommended any time the gate had to be raised. Gate-raising under pressure
  is a known anti-pattern (see lessons-learned doc
  `docs/lessons/ci-repair-sprint-2026-04.md` § "Single-run baseline
  anti-pattern") — the postmortem should keep that lesson visible.
