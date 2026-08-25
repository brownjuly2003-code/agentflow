"""Center node-ingest router (``POST /v1/node/events``) — unit contracts.

``tests/integration/test_node_topology.py`` drives the same router through the
fully booted app and already pins the role gate (N2/N12), the demo-key vs
bearer split (N3/N10), apply + branch tagging (N4), idempotency across POSTs
(N5) and the 501-event rejection. What it cannot reach — or reaches only by
accident of the producer's valid events — is pinned here against a minimal
app: the malformed-bearer ladder, a center whose token is unset, dead-letter
accounting and its interaction with the idempotency filter, duplicates
*within* one batch, events that carry no id at all, bodies that are not JSON
objects, the exact batch bound, the branch stamp's rules, and the topic scope
of the check-then-act filter that the n4 (G2 audit) note in the module relies
on.

The app here is the router plus the two pieces of ``app.state`` it reads
(``node_config`` and ``query_engine._conn``). No auth middleware, no seed, no
emitter: a 401/403 from these tests comes from the router's own ladder, which
is the point — the ingest surface is allow-listed past the demo-key middleware
and must stand on its own.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from types import SimpleNamespace
from uuid import uuid4

import duckdb
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from agentflow_runtime.ingestion.producers.event_producer import generate_order
from agentflow_runtime.processing.local_pipeline import _ensure_tables
from agentflow_runtime.serving.node.config import NodeConfig
from agentflow_runtime.serving.node.ingest import (
    MAX_EVENTS_PER_BATCH,
    NodeEventBatch,
    _existing_event_ids,
    router,
)
from agentflow_runtime.serving.node.stamp import stamp_origin_branch

_TOKEN = "unit-center-node-token"  # noqa: S105 — test fixture, not a real secret
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}
_EVENTS = "/v1/node/events"


def _order_event() -> dict:
    """A producer-shaped canonical order event (valid uuid ``event_id``)."""
    _topic, model = generate_order()
    return dict(json.loads(model.model_dump_json()))


def _malformed_event() -> dict:
    """Schema-invalid but carrying a valid-looking id, so the dead-letter row
    and the idempotency filter both have something to key on."""
    return {"event_id": str(uuid4()), "event_type": "order.created", "order_id": "ORD-BAD"}


def _cdc_event(source_metadata: object) -> dict:
    """CDC-shaped per ``schema_validator._is_cdc_event`` (source, operation,
    source_metadata); the rest is whatever ``CdcEvent`` needs to validate when
    ``source_metadata`` is a proper mapping."""
    return {
        "event_id": str(uuid4()),
        "event_type": "orders.update",
        "operation": "update",
        "timestamp": "2026-08-25T10:00:00+00:00",
        "source": "postgres_cdc",
        "entity_type": "orders",
        "entity_id": "1",
        "before": {"status": "pending"},
        "after": {"status": "paid"},
        "source_metadata": source_metadata,
    }


@pytest.fixture
def conn() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = duckdb.connect(":memory:")
    _ensure_tables(connection)
    try:
        yield connection
    finally:
        connection.close()


def _app(conn: duckdb.DuckDBPyConnection, config: NodeConfig) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.node_config = config
    app.state.query_engine = SimpleNamespace(_conn=conn)
    return app


@pytest.fixture
def center(conn: duckdb.DuckDBPyConnection) -> Iterator[TestClient]:
    with TestClient(_app(conn, NodeConfig(role="center", branch="msk", token=_TOKEN))) as client:
        yield client


def _journal(conn: duckdb.DuckDBPyConnection, event_id: str) -> list[tuple[str, str | None]]:
    return conn.execute(
        "SELECT topic, branch FROM pipeline_events WHERE event_id = ? ORDER BY topic",
        [event_id],
    ).fetchall()


def _post(client: TestClient, events: list[dict], branch: str = "spb") -> dict:
    resp = client.post(_EVENTS, json={"origin_branch": branch, "events": events}, headers=_AUTH)
    assert resp.status_code == 200, resp.text
    return dict(resp.json())


# --- bearer ladder: what the header must look like ------------------------


@pytest.mark.parametrize(
    "authorization",
    [
        pytest.param(f"Basic {_TOKEN}", id="wrong-scheme"),
        pytest.param("Bearer", id="scheme-without-value"),
        pytest.param("Bearer    ", id="scheme-with-blank-value"),
        pytest.param(_TOKEN, id="bare-token-no-scheme"),
    ],
)
def test_malformed_authorization_header_is_401_not_403(
    center: TestClient, authorization: str
) -> None:
    # 401 = the request never presented a bearer token; 403 = it presented the
    # wrong one. A right token under the wrong scheme is the former, so the
    # ladder never compares anything it did not parse as a bearer credential.
    resp = center.post(
        _EVENTS,
        json={"origin_branch": "spb", "events": []},
        headers={"Authorization": authorization},
    )

    assert resp.status_code == 401
    assert "bearer" in resp.json()["detail"].lower()


@pytest.mark.parametrize("scheme", ["bearer", "BEARER", "BeArEr"])
def test_bearer_scheme_is_case_insensitive_and_value_is_trimmed(
    center: TestClient, scheme: str
) -> None:
    resp = center.post(
        _EVENTS,
        json={"origin_branch": "spb", "events": []},
        headers={"Authorization": f"{scheme}   {_TOKEN}  "},
    )

    assert resp.status_code == 200


@pytest.mark.parametrize(
    ("presented", "expected"),
    [
        pytest.param("", 401, id="empty-bearer-never-reaches-the-compare"),
        pytest.param("x", 403, id="anything-is-wrong"),
        pytest.param(_TOKEN, 403, id="even-the-token-another-center-would-take"),
    ],
)
def test_center_with_no_configured_token_refuses_every_bearer(
    conn: duckdb.DuckDBPyConnection, presented: str, expected: int
) -> None:
    # resolve_node_config() never builds this (a center without a token fails
    # at boot), but if it ever did, "nothing configured" must read as "nothing
    # matches", never as "compare against the empty string".
    with TestClient(_app(conn, NodeConfig(role="center", branch="msk", token=None))) as client:
        resp = client.post(
            _EVENTS,
            json={"origin_branch": "spb", "events": []},
            headers={"Authorization": f"Bearer {presented}"},
        )

    assert resp.status_code == expected


# --- body shape ----------------------------------------------------------


def test_body_that_is_not_json_is_422(center: TestClient) -> None:
    resp = center.post(
        _EVENTS, content=b"{not json", headers={**_AUTH, "Content-Type": "application/json"}
    )

    assert resp.status_code == 422
    assert resp.json()["detail"].startswith("Invalid batch:")


def test_body_that_is_json_but_not_an_object_is_422(center: TestClient) -> None:
    resp = center.post(_EVENTS, json=[{"origin_branch": "spb"}], headers=_AUTH)

    assert resp.status_code == 422


def test_events_must_be_objects(center: TestClient) -> None:
    # The model rejects the shape before the apply loop's own `isinstance`
    # guards could matter, so a scalar in the list never reaches the pipeline.
    resp = center.post(_EVENTS, json={"origin_branch": "spb", "events": ["x"]}, headers=_AUTH)

    assert resp.status_code == 422


def test_batch_bound_is_exactly_max_events_per_batch() -> None:
    # The bound lives in the model, so it is pinned there: 500 is a batch, 501
    # is not. (Through the endpoint 500 events would be 500 real transactions
    # for a shape check; the 501 -> 422 case is in the topology suite.)
    at_bound: list[dict] = [{} for _ in range(MAX_EVENTS_PER_BATCH)]

    NodeEventBatch.model_validate({"origin_branch": "spb", "events": at_bound})
    with pytest.raises(ValidationError):
        NodeEventBatch.model_validate({"origin_branch": "spb", "events": [*at_bound, {}]})


# --- dead-letter accounting and the idempotency filter ---------------------


def test_schema_invalid_event_is_dead_lettered_and_branch_tagged(
    center: TestClient, conn: duckdb.DuckDBPyConnection
) -> None:
    event = _malformed_event()

    body = _post(center, [event], branch="ekb")

    assert body == {"accepted": 1, "applied": 0, "dead_lettered": 1, "duplicates": 0}
    # The branch is stamped before validation, so even a rejected event says
    # which edge sent it.
    assert _journal(conn, event["event_id"]) == [("events.deadletter", "ekb")]


def test_dead_lettered_id_is_a_duplicate_on_retry(
    center: TestClient, conn: duckdb.DuckDBPyConnection
) -> None:
    # The idempotency filter spans both ingest topics: an edge that retries a
    # batch after a rejection must not grow the dead-letter journal each time.
    event = _malformed_event()

    first = _post(center, [event])
    second = _post(center, [event])

    assert first["dead_lettered"] == 1
    assert second == {"accepted": 1, "applied": 0, "dead_lettered": 0, "duplicates": 1}
    assert len(_journal(conn, event["event_id"])) == 1


def test_same_event_twice_in_one_batch_applies_once(
    center: TestClient, conn: duckdb.DuckDBPyConnection
) -> None:
    # The pre-scan sees nothing, so the second copy is caught by the in-loop
    # `seen.add` — the filter is check-then-act *per event*, not per batch.
    event = _order_event()

    body = _post(center, [event, dict(event)])

    assert body == {"accepted": 2, "applied": 1, "dead_lettered": 0, "duplicates": 1}
    validated = conn.execute(
        "SELECT COUNT(*) FROM pipeline_events WHERE event_id = ? AND topic = 'events.validated'",
        [event["event_id"]],
    ).fetchone()
    assert validated == (1,)


def test_mixed_batch_counts_each_outcome_once(center: TestClient) -> None:
    good, bad = _order_event(), _malformed_event()
    assert _post(center, [good])["applied"] == 1

    body = _post(center, [good, bad, _order_event()])

    assert body == {"accepted": 3, "applied": 1, "dead_lettered": 1, "duplicates": 1}


def test_event_without_an_id_is_never_a_duplicate(center: TestClient) -> None:
    # The filter keys on event_id, so an event without one cannot be recognised
    # on retry. The schema requires an id, so such an event is dead-lettered
    # both times — never applied, never counted as seen. (Whether a retry
    # should also re-journal it is not pinned: the row is written with the
    # pipeline's literal `'unknown'` id, which is the pipeline's business.)
    event = _order_event()
    del event["event_id"]

    first = _post(center, [event])
    second = _post(center, [event])

    assert first == {"accepted": 1, "applied": 0, "dead_lettered": 1, "duplicates": 0}
    assert second == first


# --- the branch stamp -----------------------------------------------------


def test_non_mapping_source_metadata_is_replaced_so_the_tag_still_lands(
    center: TestClient, conn: duckdb.DuckDBPyConnection
) -> None:
    # BaseEvent does not declare source_metadata, so a string there does not
    # fail validation: the event applies. Skipping the tag in that case (the
    # original guard) journaled a federated event with no branch, and the
    # cross-branch view never saw it.
    event = _order_event()
    event["source_metadata"] = "not-a-mapping"

    body = _post(center, [event])

    assert body["applied"] == 1
    assert _journal(conn, event["event_id"]) == [("events.validated", "spb")]


def test_sender_supplied_branch_is_overwritten_by_the_center_stamp(
    center: TestClient, conn: duckdb.DuckDBPyConnection
) -> None:
    event = _order_event()
    event["source_metadata"] = {"branch": "msk", "emitter": "edge-1"}

    body = _post(center, [event], branch="ekb")

    assert body["applied"] == 1
    assert _journal(conn, event["event_id"]) == [("events.validated", "ekb")]


def test_cdc_event_with_non_mapping_source_metadata_is_not_healed(
    center: TestClient, conn: duckdb.DuckDBPyConnection
) -> None:
    # CdcEvent owns source_metadata (provenance, a non-empty mapping). Replacing
    # a broken value with {"branch": ...} would turn a schema reject into a
    # validated row with fabricated provenance, so the stamp leaves it alone
    # and the validator dead-letters it. Branch attribution is lost with it —
    # the sender's defect, recorded as a reject rather than papered over.
    event = _cdc_event('{"db": "shop", "lsn": 42}')

    body = _post(center, [event])

    assert body == {"accepted": 1, "applied": 0, "dead_lettered": 1, "duplicates": 0}
    assert [topic for topic, _branch in _journal(conn, event["event_id"])] == ["events.deadletter"]


def test_cdc_event_with_mapping_source_metadata_gets_the_branch_added() -> None:
    event = _cdc_event({"db": "shop", "lsn": 42})

    stamp_origin_branch(event, "spb")

    assert event["source_metadata"] == {"db": "shop", "lsn": 42, "branch": "spb"}


@pytest.mark.parametrize(
    "event",
    [
        pytest.param({"event_type": "order.created"}, id="absent"),
        pytest.param({"event_type": "order.created", "source_metadata": None}, id="null"),
        pytest.param({"event_type": "order.created", "source_metadata": ["x"]}, id="list"),
    ],
)
def test_stamp_creates_or_replaces_source_metadata_on_producer_events(event: dict) -> None:
    stamp_origin_branch(event, "ekb")

    assert event["source_metadata"] == {"branch": "ekb"}


# --- _existing_event_ids: the filter's scope -------------------------------


def test_existing_event_ids_short_circuits_on_an_empty_batch() -> None:
    # No tables at all: the query would raise, so a returned empty set proves
    # the short-circuit rather than an empty intersection.
    bare = duckdb.connect(":memory:")
    try:
        assert _existing_event_ids(bare, []) == set()
    finally:
        bare.close()


def test_existing_event_ids_is_scoped_to_the_two_ingest_topics(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    # Derived rows (the `orders.status` journal entry) reuse an id under another
    # topic; the n4 (G2 audit) note explains why this is a Python filter and
    # not a table-wide UNIQUE — this pins the scope that note depends on.
    conn.execute(
        "INSERT INTO pipeline_events (event_id, topic, latency_ms) VALUES "
        "('seen-ok', 'events.validated', 0), "
        "('seen-dead', 'events.deadletter', 0), "
        "('derived-only', 'orders.status', 0), "
        "('baseline-only', 'node.baseline', 0)"
    )

    present = _existing_event_ids(
        conn, ["seen-ok", "seen-dead", "derived-only", "baseline-only", "never-seen"]
    )

    assert present == {"seen-ok", "seen-dead"}


def test_existing_event_ids_returns_only_the_batch_intersection(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    conn.execute(
        "INSERT INTO pipeline_events (event_id, topic, latency_ms) VALUES "
        "('a', 'events.validated', 0), ('b', 'events.validated', 0)"
    )

    assert _existing_event_ids(conn, ["b", "c"]) == {"b"}
