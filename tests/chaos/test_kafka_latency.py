from __future__ import annotations

import pytest

from tests.chaos.conftest import (
    deadletter_status,
    install_deadletter_producer,
    outbox_status,
    seed_deadletter_event,
)


pytestmark = [pytest.mark.integration, pytest.mark.requires_docker]


def test_replay_succeeds_through_kafka_latency_proxy(
    chaos_client,
    chaos_context,
    chaos_headers,
    chaos_stack,
    toxiproxy_client,
):
    install_deadletter_producer(
        chaos_client,
        chaos_stack["kafka_bootstrap"],
        socket_timeout_ms=8000,
        message_timeout_ms=8000,
        flush_timeout_seconds=10,
    )
    event_id = "11111111-1111-1111-1111-111111111111"
    seed_deadletter_event(chaos_context.db_path, event_id)
    toxiproxy_client.add_toxic(
        "kafka",
        "latency",
        "latency",
        {"latency": 500, "jitter": 50},
    )

    replay = chaos_client.post(
        f"/v1/deadletter/{event_id}/replay",
        headers=chaos_headers,
        json={},
    )
    entity = chaos_client.get(
        "/v1/entity/order/ORD-20260404-1001",
        headers=chaos_headers,
    )

    assert replay.status_code == 200
    assert replay.json()["status"] == "replayed"
    assert deadletter_status(chaos_context.db_path, event_id) == ("replayed", 1)
    assert outbox_status(chaos_context.db_path, event_id) == ("sent", 0, None)
    assert entity.status_code == 200


def test_replay_stays_pending_when_kafka_proxy_times_out(
    chaos_client,
    chaos_context,
    chaos_headers,
    chaos_stack,
    toxiproxy_client,
):
    install_deadletter_producer(chaos_client, chaos_stack["kafka_bootstrap"])
    event_id = "22222222-2222-2222-2222-222222222222"
    seed_deadletter_event(chaos_context.db_path, event_id)
    toxiproxy_client.delete_proxy("kafka")

    replay = chaos_client.post(
        f"/v1/deadletter/{event_id}/replay",
        headers=chaos_headers,
        json={},
    )
    metric = chaos_client.get(
        "/v1/metrics/revenue?window=24h",
        headers=chaos_headers,
    )

    assert replay.status_code == 200
    assert replay.json()["status"] == "replay_pending"
    assert deadletter_status(chaos_context.db_path, event_id) == ("replay_pending", 1)
    pending_status = outbox_status(chaos_context.db_path, event_id)
    assert pending_status is not None
    assert pending_status[0] == "pending"
    assert pending_status[1] == 1
    assert pending_status[2]
    assert metric.status_code == 200
