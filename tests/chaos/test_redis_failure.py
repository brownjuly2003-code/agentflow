from __future__ import annotations

import pytest

from tests.chaos.conftest import install_redis_query_cache


pytestmark = [pytest.mark.integration, pytest.mark.requires_docker]


def test_metrics_fall_back_when_redis_proxy_is_disabled(
    chaos_client,
    chaos_headers,
    chaos_stack,
    toxiproxy_client,
):
    install_redis_query_cache(chaos_client, chaos_stack)

    baseline = chaos_client.get(
        "/v1/metrics/revenue?window=24h",
        headers=chaos_headers,
    )
    cached = chaos_client.get(
        "/v1/metrics/revenue?window=24h",
        headers=chaos_headers,
    )
    toxiproxy_client.disable_proxy("redis")
    degraded = chaos_client.get(
        "/v1/metrics/revenue?window=24h",
        headers=chaos_headers,
    )
    entity = chaos_client.get(
        "/v1/entity/order/ORD-20260404-1001",
        headers=chaos_headers,
    )

    assert baseline.status_code == 200
    assert baseline.headers["X-Cache"] == "MISS"
    assert cached.status_code == 200
    assert cached.headers["X-Cache"] == "HIT"
    assert degraded.status_code == 200
    assert degraded.headers["X-Cache"] == "MISS"
    assert degraded.json()["value"] == baseline.json()["value"]
    assert entity.status_code == 200
