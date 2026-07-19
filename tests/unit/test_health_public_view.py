"""Unit coverage for the unauthenticated health-view sanitizer (audit S-3).

`/v1/health` is auth-exempt, so its payload must not carry recon: component
`message` text (``f"Kafka unavailable: {exc}"`` with internal hostnames),
`metrics` (broker/topic counts, cluster sizes), or backend identity. The view
keeps overall status and each component's name/status/source (the documented
contract) and nothing else.
"""

from __future__ import annotations

from src.serving.api.main import _public_health_view

_RAW_PAYLOAD = {
    "status": "unhealthy",
    "checked_at": "2026-07-19T07:00:00+00:00",
    "components": [
        {
            "name": "kafka",
            "status": "unhealthy",
            "message": "Kafka unavailable: [Errno -2] Name or service not known: kafka-broker-0.internal:9092",
            "metrics": {"brokers": 0, "topics": 0},
            "source": "placeholder",
        },
        {
            "name": "serving",
            "status": "healthy",
            "message": "clickhouse reachable",
            "metrics": {"backend": "clickhouse"},
            "source": "live",
        },
        {
            "name": "freshness",
            "status": "healthy",
            "message": "last event 4s ago",
            "metrics": {"last_event_age_seconds": 4},
            "source": "live",
        },
    ],
}


def test_view_keeps_only_name_status_source_per_component() -> None:
    view = _public_health_view(_RAW_PAYLOAD)
    for component in view["components"]:
        assert set(component) == {"name", "status", "source", "metrics"}


def test_view_drops_error_strings_counts_and_backend_identity() -> None:
    # message (internal hostnames), broker/topic counts and backend identity are
    # all recon and must be gone.
    flat = repr(_public_health_view(_RAW_PAYLOAD))
    for leak in ("kafka-broker-0.internal", "Errno", "clickhouse", "brokers", "topics"):
        assert leak not in flat


def test_view_keeps_only_allowlisted_operational_metrics() -> None:
    view = _public_health_view(_RAW_PAYLOAD)
    by_name = {c["name"]: c for c in view["components"]}
    # topology metrics dropped ...
    assert by_name["kafka"]["metrics"] == {}
    assert by_name["serving"]["metrics"] == {}  # backend identity dropped
    # ... freshness gauge (agent-facing, benign) preserved.
    assert by_name["freshness"]["metrics"] == {"last_event_age_seconds": 4}


def test_view_preserves_allowlisted_pool_gauges() -> None:
    payload = {
        "status": "healthy",
        "components": [
            {
                "name": "duckdb_pool",
                "status": "healthy",
                "source": "live",
                "metrics": {"pool_size": 4, "read_utilization": 0.25, "secret_dsn": "host:5432"},
            }
        ],
    }
    metrics = _public_health_view(payload)["components"][0]["metrics"]
    assert metrics == {"pool_size": 4, "read_utilization": 0.25}  # non-allowlisted key dropped


def test_view_preserves_overall_status_and_component_statuses() -> None:
    view = _public_health_view(_RAW_PAYLOAD)
    assert view["status"] == "unhealthy"
    assert [c["status"] for c in view["components"]] == ["unhealthy", "healthy", "healthy"]
    assert [c["name"] for c in view["components"]] == ["kafka", "serving", "freshness"]


def test_view_preserves_checked_at_when_present() -> None:
    assert _public_health_view(_RAW_PAYLOAD)["checked_at"] == "2026-07-19T07:00:00+00:00"


def test_view_tolerates_missing_optional_keys() -> None:
    view = _public_health_view({"status": "healthy", "components": [{"name": "x", "status": "ok"}]})
    assert view == {
        "status": "healthy",
        "components": [{"name": "x", "status": "ok", "source": None, "metrics": {}}],
    }
