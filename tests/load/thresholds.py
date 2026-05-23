# CI runner p99 thresholds.
#
# These gates run against shared 4-core GitHub Actions hosted runners.
# Local hardware sustains p99 ~ 167 ms on the entity endpoint (after the
# tenant qualification cache landed in `aae27bf`); CI hardware sustains
# 600-800 ms on the same code path. The gap is the runner, not the
# application — see `docs/perf/ci-hardware-gap-2026-05-24.md`.
#
# Gates below are calibrated against the 2026-04-25 CI baseline + a 1.3x
# noise headroom (raised from 1.1x on 2026-05-24 after three flaky
# load-test runs that landed p99 within the documented divergent band).
# A self-hosted runner or paid larger runner would close the gap; until
# then, gates here are intentionally CI-realistic, not application-SLO.
THRESHOLDS = {
    "GET /v1/entity/order/{id}": {"p99_ms": 900.0, "error_rate_max": 0.01},
    "GET /v1/entity/user/{id}": {"p99_ms": 900.0, "error_rate_max": 0.01},
    "GET /v1/entity/product/{id}": {"p99_ms": 1100.0, "error_rate_max": 0.01},
    "GET /v1/metrics/{name}": {"p99_ms": 1100.0, "error_rate_max": 0.01},
    "POST /v1/query": {"p99_ms": 1200.0, "error_rate_max": 0.05},
    "POST /v1/batch": {"p99_ms": 1200.0, "error_rate_max": 0.02},
}

LOAD_PROFILE = {
    "users": 50,
    "spawn_rate": 10,
    "run_time": "60s",
}
