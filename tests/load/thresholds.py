THRESHOLDS = {
    "GET /v1/entity/order/{id}": {"p95_ms": 50.0, "error_rate_max": 0.01},
    "GET /v1/entity/user/{id}": {"p95_ms": 50.0, "error_rate_max": 0.01},
    "GET /v1/entity/product/{id}": {"p95_ms": 50.0, "error_rate_max": 0.01},
    "GET /v1/metrics/{name}": {"p95_ms": 100.0, "error_rate_max": 0.01},
    "POST /v1/query": {"p95_ms": 500.0, "error_rate_max": 0.05},
    "POST /v1/batch": {"p95_ms": 200.0, "error_rate_max": 0.02},
    "GET /v1/health": {"p95_ms": 20.0, "error_rate_max": 0.0},
}

LOAD_PROFILE = {
    "users": 50,
    "spawn_rate": 10,
    "run_time": "60s",
}
