"""Unit coverage for the pipeline_events journal's entity_id axis and the
orders.status stage-entry writer (ops-surfaces-spec.md §1.2, §1.3 — D2).

Before this, only the demo seed populated entity_id; the live write sites
(both DuckDB inserts here, plus clickhouse_sink.py's mirror, covered
separately in test_local_pipeline_clickhouse_mirror.py) left it NULL.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import duckdb
import pytest

from src.ingestion.producers.event_producer import generate_click, generate_order
from src.processing.local_pipeline import _derive_entity_id, _ensure_tables, _process_event


@pytest.fixture
def conn() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = duckdb.connect(":memory:")
    _ensure_tables(connection)
    try:
        yield connection
    finally:
        connection.close()


def _order_event() -> dict:
    _, event = generate_order()
    return json.loads(event.model_dump_json())


class TestDeriveEntityId:
    def test_order_event_uses_order_id(self) -> None:
        assert _derive_entity_id({"order_id": "ORD-1"}, "order.created") == "ORD-1"

    def test_user_event_uses_user_id(self) -> None:
        assert _derive_entity_id({"user_id": "USR-1"}, "user.updated") == "USR-1"

    def test_product_event_uses_product_id(self) -> None:
        assert _derive_entity_id({"product_id": "PROD-1"}, "product.updated") == "PROD-1"

    def test_session_event_uses_session_id(self) -> None:
        assert _derive_entity_id({"session_id": "SES-1"}, "session.ended") == "SES-1"

    def test_unrelated_event_type_is_not_derivable(self) -> None:
        assert _derive_entity_id({"order_id": "ORD-1"}, "payment.completed") is None

    def test_missing_field_is_not_synthesized(self) -> None:
        # order.* but no order_id in the payload — NULL, never a made-up id.
        assert _derive_entity_id({}, "order.created") is None


def test_validated_order_row_carries_entity_id(conn) -> None:
    event = _order_event()

    success, _ = _process_event(conn, event)

    assert success
    row = conn.execute(
        "SELECT entity_id FROM pipeline_events WHERE topic = 'events.validated'"
    ).fetchone()
    assert row is not None
    assert row[0] == str(event["order_id"])


def test_deadletter_row_derives_entity_id_when_order_id_present(conn) -> None:
    # order_id is present but the payload is otherwise schema-invalid.
    malformed = {"event_type": "order.created", "order_id": "ORD-BAD-1"}

    success, reason = _process_event(conn, malformed)

    assert not success
    assert reason.startswith("schema:")
    row = conn.execute(
        "SELECT entity_id FROM pipeline_events WHERE topic = 'events.deadletter'"
    ).fetchone()
    assert row is not None
    assert row[0] == "ORD-BAD-1"


def test_deadletter_row_entity_id_null_when_not_derivable(conn) -> None:
    success, reason = _process_event(conn, {"event_type": "order.created"})

    assert not success
    assert reason.startswith("schema:")
    row = conn.execute(
        "SELECT entity_id FROM pipeline_events WHERE topic = 'events.deadletter'"
    ).fetchone()
    assert row is not None
    assert row[0] is None


def test_click_event_journal_row_entity_id_null(conn) -> None:
    # Clickstream events carry no entity_id prefix mapping (session.* is the
    # session family; raw click/page_view/add_to_cart events are unmapped).
    _, click = generate_click()
    event = json.loads(click.model_dump_json())

    success, _ = _process_event(conn, event)

    assert success
    row = conn.execute(
        "SELECT entity_id FROM pipeline_events WHERE topic = 'events.validated'"
    ).fetchone()
    assert row is not None
    assert row[0] is None


class TestOrderStatusStageRow:
    def test_order_event_writes_a_stage_row(self, conn) -> None:
        event = _order_event()

        success, _ = _process_event(conn, event)

        assert success
        rows = conn.execute(
            "SELECT event_type, entity_id, latency_ms, tenant_id "
            "FROM pipeline_events WHERE topic = 'orders.status'"
        ).fetchall()
        assert len(rows) == 1
        event_type, entity_id, latency_ms, tenant_id = rows[0]
        assert event_type == f"order.status.{event['status']}"
        assert entity_id == str(event["order_id"])
        assert latency_ms is None
        assert tenant_id == "default"

    def test_stage_row_topic_is_disjoint_from_validated_row(self, conn) -> None:
        event = _order_event()

        success, _ = _process_event(conn, event)

        assert success
        topics = {
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT topic FROM pipeline_events WHERE entity_id = ?",
                [str(event["order_id"])],
            ).fetchall()
        }
        assert topics == {"events.validated", "orders.status"}

    def test_non_order_event_writes_no_stage_row(self, conn) -> None:
        _, click = generate_click()
        event = json.loads(click.model_dump_json())

        success, _ = _process_event(conn, event)

        assert success
        row = conn.execute(
            "SELECT COUNT(*) FROM pipeline_events WHERE topic = 'orders.status'"
        ).fetchone()
        assert row is not None
        assert row[0] == 0

    def test_deadletter_event_writes_no_stage_row(self, conn) -> None:
        success, _ = _process_event(conn, {"event_type": "order.created", "order_id": "ORD-X"})

        assert not success
        row = conn.execute(
            "SELECT COUNT(*) FROM pipeline_events WHERE topic = 'orders.status'"
        ).fetchone()
        assert row is not None
        assert row[0] == 0
