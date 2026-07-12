"""P2-3: the production profile refuses insecure transport to external stores.

The backend has supported CLICKHOUSE_SECURE for a while, but nothing ever
required it: a scale-profile deployment would happily speak HTTP Basic
Auth to an external ClickHouse. These tests pin the gate that makes the
production profile fail closed — per store, with loopback exempt (the
bytes never leave the host) and an explicit, greppable operator override
for deliberate plaintext (e.g. in-cluster traffic behind a NetworkPolicy).
"""

from __future__ import annotations

import pytest

from src.serving.transport_policy import (
    InsecureTransportError,
    assert_secure_transport,
    resolve_cors_origins,
    resolve_profile,
)


def _serving(backend: str = "clickhouse", host: str = "ch.prod.internal", secure: bool = False):
    return {
        "backend": backend,
        "clickhouse": {"host": host, "secure": secure},
    }


# --- profile resolution ---


def test_explicit_profile_wins() -> None:
    assert resolve_profile({"AGENTFLOW_PROFILE": "production"}) == "production"
    assert resolve_profile({"AGENTFLOW_PROFILE": " Dev "}) == "dev"


def test_unknown_profile_is_a_loud_error() -> None:
    with pytest.raises(ValueError, match="AGENTFLOW_PROFILE"):
        resolve_profile({"AGENTFLOW_PROFILE": "prod"})


def test_demo_mode_implies_demo_profile() -> None:
    assert resolve_profile({"AGENTFLOW_DEMO_MODE": "true"}) == "demo"


def test_default_profile_is_dev() -> None:
    assert resolve_profile({}) == "dev"


# --- clickhouse ---


def test_production_refuses_insecure_external_clickhouse() -> None:
    with pytest.raises(InsecureTransportError, match="clickhouse"):
        assert_secure_transport(profile="production", serving_config=_serving(), env={})


def test_production_accepts_secure_clickhouse() -> None:
    assert_secure_transport(profile="production", serving_config=_serving(secure=True), env={})


def test_loopback_clickhouse_is_exempt() -> None:
    assert_secure_transport(profile="production", serving_config=_serving(host="localhost"), env={})
    assert_secure_transport(profile="production", serving_config=_serving(host="127.0.0.1"), env={})


def test_duckdb_backend_has_no_clickhouse_transport() -> None:
    assert_secure_transport(profile="production", serving_config=_serving(backend="duckdb"), env={})


def test_operator_override_admits_plaintext_clickhouse() -> None:
    assert_secure_transport(
        profile="production",
        serving_config=_serving(),
        env={"AGENTFLOW_INSECURE_TRANSPORT_OK": "clickhouse"},
    )


# --- redis ---


def test_production_refuses_plaintext_external_redis() -> None:
    with pytest.raises(InsecureTransportError, match="redis"):
        assert_secure_transport(
            profile="production",
            serving_config=_serving(backend="duckdb"),
            redis_url="redis://cache.internal:6379",
            env={},
        )


def test_rediss_and_local_redis_pass() -> None:
    assert_secure_transport(
        profile="production",
        serving_config=_serving(backend="duckdb"),
        redis_url="rediss://cache.internal:6380",
        env={},
    )
    assert_secure_transport(
        profile="production",
        serving_config=_serving(backend="duckdb"),
        redis_url="redis://localhost:6379",
        env={},
    )
    assert_secure_transport(
        profile="production",
        serving_config=_serving(backend="duckdb"),
        redis_url="unix:///var/run/redis.sock",
        env={},
    )


# --- postgres ---


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://af:pw@pg.prod.internal:5432/agentflow?sslmode=require",
        "postgresql://af:pw@pg.prod.internal/agentflow?sslmode=verify-full",
        "host=pg.prod.internal dbname=agentflow sslmode=verify-ca",
        "host=localhost dbname=agentflow",  # loopback: bytes never leave the host
    ],
)
def test_tls_or_loopback_postgres_passes(dsn: str) -> None:
    assert_secure_transport(
        profile="production", serving_config=_serving(backend="duckdb"), pg_dsn=dsn, env={}
    )


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://af:pw@pg.prod.internal:5432/agentflow",
        "postgresql://af:pw@pg.prod.internal/agentflow?sslmode=disable",
        "postgresql://af:pw@pg.prod.internal/agentflow?sslmode=prefer",
        "host=pg.prod.internal dbname=agentflow",
    ],
)
def test_production_refuses_non_tls_external_postgres(dsn: str) -> None:
    with pytest.raises(InsecureTransportError, match="postgres"):
        assert_secure_transport(
            profile="production", serving_config=_serving(backend="duckdb"), pg_dsn=dsn, env={}
        )


# --- aggregation and other profiles ---


def test_all_problems_are_reported_at_once() -> None:
    with pytest.raises(InsecureTransportError) as excinfo:
        assert_secure_transport(
            profile="production",
            serving_config=_serving(),
            redis_url="redis://cache.internal:6379",
            pg_dsn="postgresql://af@pg.prod.internal/agentflow",
            env={},
        )
    message = str(excinfo.value)
    assert "clickhouse" in message
    assert "redis" in message
    assert "postgres" in message
    # The remedy ships with the refusal.
    assert "AGENTFLOW_INSECURE_TRANSPORT_OK" in message


def test_dev_and_demo_profiles_do_not_gate() -> None:
    for profile in ("dev", "demo"):
        assert_secure_transport(
            profile=profile,
            serving_config=_serving(),
            redis_url="redis://cache.internal:6379",
            pg_dsn="postgresql://af@pg.prod.internal/agentflow",
            env={},
        )


# --- CORS ---


def test_wildcard_cors_with_credentials_is_demo_only() -> None:
    env = {"AGENTFLOW_CORS_ORIGINS": "*", "AGENTFLOW_DEMO_MODE": "true"}
    assert resolve_cors_origins(env) == ["*"]

    with pytest.raises(InsecureTransportError, match="CORS"):
        resolve_cors_origins({"AGENTFLOW_CORS_ORIGINS": "*"})
    with pytest.raises(InsecureTransportError, match="CORS"):
        resolve_cors_origins(
            {"AGENTFLOW_CORS_ORIGINS": "https://a.example,*", "AGENTFLOW_PROFILE": "production"}
        )


def test_explicit_origin_list_passes_everywhere() -> None:
    env = {"AGENTFLOW_CORS_ORIGINS": "https://a.example, https://b.example"}
    assert resolve_cors_origins(env) == ["https://a.example", "https://b.example"]


def test_cors_default_is_localhost() -> None:
    assert resolve_cors_origins({}) == ["http://localhost:3000"]
