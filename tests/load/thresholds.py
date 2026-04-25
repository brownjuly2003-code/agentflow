THRESHOLDS = {
    "GET /v1/entity/order/{id}": {"p99_ms": 750.0, "error_rate_max": 0.01},
    "GET /v1/entity/user/{id}": {"p99_ms": 750.0, "error_rate_max": 0.01},
    "GET /v1/entity/product/{id}": {"p99_ms": 750.0, "error_rate_max": 0.01},
    "GET /v1/metrics/{name}": {"p99_ms": 750.0, "error_rate_max": 0.01},
    "POST /v1/query": {"p99_ms": 800.0, "error_rate_max": 0.05},
    "POST /v1/batch": {"p99_ms": 800.0, "error_rate_max": 0.02},
}

LOAD_PROFILE = {
    "users": 50,
    "spawn_rate": 10,
    "run_time": "60s",
}
