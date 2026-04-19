from __future__ import annotations

import pytest

from tests.chaos import test_duckdb_timeout, test_redis_failure


pytestmark = [pytest.mark.integration, pytest.mark.requires_docker]


def test_smoke_metric_endpoint_returns_503_on_duckdb_timeout(
    chaos_client,
    chaos_headers,
):
    test_duckdb_timeout.test_metric_endpoint_returns_503_on_duckdb_timeout(
        chaos_client,
        chaos_headers,
    )


def test_smoke_entity_endpoint_returns_503_on_duckdb_timeout(
    chaos_client,
    chaos_headers,
):
    test_duckdb_timeout.test_entity_endpoint_returns_503_on_duckdb_timeout(
        chaos_client,
        chaos_headers,
    )


def test_smoke_metrics_fall_back_when_redis_proxy_is_disabled(
    chaos_client,
    chaos_headers,
    chaos_stack,
    toxiproxy_client,
):
    test_redis_failure.test_metrics_fall_back_when_redis_proxy_is_disabled(
        chaos_client,
        chaos_headers,
        chaos_stack,
        toxiproxy_client,
    )
