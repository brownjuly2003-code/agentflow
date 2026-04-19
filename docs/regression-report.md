# Entity p99 Regression Follow-up

**Date:** 2026-04-17  
**Scope:** v14 SDK resilience post-release follow-up

## Current baseline

Committed benchmark data in `docs/benchmark-baseline.json` generated on `2026-04-17T13:37:10+03:00` still shows:

- `GET /v1/entity/order/{id}` p99 = `300 ms`
- `GET /v1/entity/product/{id}` p99 = `320 ms`
- `GET /v1/entity/user/{id}` p99 = `290 ms`

## Assessment

- These numbers are worse than the earlier pre-regression lab result of roughly `170 ms`.
- They are still inside the release gate documented for entity endpoints: `p99 < 500 ms`.
- v14 changed SDK client behavior only (`retry/backoff` and `circuit breaker`) and did not modify the API serving hot path under `src/`.

## Conclusion

v14 does not claim a new p99 performance fix. The current `290-320 ms` entity tail stays documented as a known limitation until a separate serving-path profiling pass is run with fresh benchmark data.
