"""Live-ClickHouse regression for the webhook cohort-wedge (audit 2026-07-17 #1).

``test_webhook_dispatcher_unit.py`` proves the composite keyset drains a
saturated second on DuckDB, and ``test_pipeline_events_scan.py`` proves the
keyset predicate transpiles to ClickHouse — but nothing ran the dispatcher's
scan loop against a real ClickHouse server, and ClickHouse is exactly where
the wedge premise lives: ``processed_at`` is second-granular there, so a burst
second's rows all share one timestamp and only the ``event_id`` half of the
keyset can order them. These tests close that gap end-to-end: real transpiled
SQL, real JSON transport (timestamps come back as strings, not datetimes),
real ``ORDER BY``/``LIMIT`` pagination inside one second.

Gated on ``CLICKHOUSE_LIVE_HOST`` like the other live suites: CI provides a
`clickhouse` service container on the test-integration job; locally, point it
at any disposable server. The suite provisions and drops its own database so
the shared demo seed and the tenant-isolation store are never touched.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

from src.serving.api.webhook_dispatcher import (
    WebhookDispatcher,
    WebhookFilters,
    create_webhook,
)
from src.serving.backends.clickhouse_backend import ClickHouseBackend
from src.serving.backends.duckdb_backend import DuckDBBackend
from src.serving.semantic_layer.query import QueryEngine

LIVE_HOST = os.getenv("CLICKHOUSE_LIVE_HOST")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not LIVE_HOST,
        reason="CLICKHOUSE_LIVE_HOST not configured (live ClickHouse required)",
    ),
]

# Same shape as the DuckDB regression: a single second holding MORE rows than
# one scan batch, then rows strictly after it — the events the pre-fix cursor
# hid forever. Fixed timestamps keep the journal deterministic across runs.
BATCH = 5
COHORT = 12
SATURATED = "2026-07-10 10:00:00"
COHORT_IDS = [f"EVT-KS-{i:03d}" for i in range(COHORT)]
AFTER = [("Z-AFTER-1", "2026-07-10 10:00:01"), ("Z-AFTER-2", "2026-07-10 10:00:02")]


def _live_database() -> str:
    """A database of this suite's own — see the tenant-isolation suite for why
    sharing the demo-seeded ``agentflow`` store is not an option."""
    return f"{os.getenv('CLICKHOUSE_LIVE_DATABASE', 'agentflow')}_keyset_live"


def _backend(database: str) -> ClickHouseBackend:
    return ClickHouseBackend(
        host=LIVE_HOST or "localhost",
        port=int(os.getenv("CLICKHOUSE_LIVE_PORT", "8123")),
        user=os.getenv("CLICKHOUSE_LIVE_USER", "agentflow"),
        password=os.getenv("CLICKHOUSE_LIVE_PASSWORD", "agentflow"),
        database=database,
    )


def _ddl(backend: ClickHouseBackend, sql: str) -> None:
    backend._request(sql, expect_json=False, translate=False, use_database=False)  # noqa: SLF001


@pytest.fixture(scope="module")
def live_clickhouse() -> Iterator[ClickHouseBackend]:
    database = _live_database()
    backend = _backend(database)
    _ddl(backend, f"DROP DATABASE IF EXISTS {database}")
    backend.ensure_schema()
    backend.insert_rows(
        "pipeline_events",
        [
            {
                "event_id": event_id,
                "topic": "orders.raw",
                "tenant_id": "acme",
                "entity_id": f"ORD-{event_id}",
                "event_type": "order.created",
                "latency_ms": 100,
                "processed_at": processed_at,
            }
            for event_id, processed_at in [
                *((event_id, SATURATED) for event_id in COHORT_IDS),
                *AFTER,
            ]
        ],
    )
    yield backend
    _ddl(backend, f"DROP DATABASE IF EXISTS {database}")


@pytest.fixture
def clickhouse_engine(live_clickhouse: ClickHouseBackend) -> Iterator[QueryEngine]:
    """A QueryEngine whose journal scan hits live ClickHouse.

    Built via ``__new__`` exactly like the dispatcher unit suite's engine stub:
    the serving backend (journal) is the live server, while the embedded DuckDB
    connection only hosts the durable delivery queue — the same split a real
    ClickHouse-backed API process runs with.
    """
    conn = duckdb.connect(":memory:")
    engine = QueryEngine.__new__(QueryEngine)
    engine._backend = live_clickhouse
    engine._backend_name = live_clickhouse.name
    engine._duckdb_backend = DuckDBBackend(db_path=":memory:", connection=conn)
    engine._conn = conn
    try:
        yield engine
    finally:
        conn.close()


def test_inclusive_bound_alone_cannot_pass_a_saturated_second(
    clickhouse_engine: QueryEngine,
) -> None:
    """The wedge premise, demonstrated on the real server: with only the
    inclusive ``>=`` cursor (no ``min_event_id``), a full batch from the
    saturated second returns the *same* lowest-``event_id`` rows every time —
    the window cannot progress. This is the live behavior the keyset exists to
    escape; if ClickHouse ever stops behaving this way the fix's premise (and
    this suite) should be revisited.
    """
    first = clickhouse_engine.fetch_pipeline_events(min_processed_at=SATURATED, limit=BATCH)
    second = clickhouse_engine.fetch_pipeline_events(min_processed_at=SATURATED, limit=BATCH)

    assert [row["event_id"] for row in first] == COHORT_IDS[:BATCH]
    assert [row["event_id"] for row in second] == COHORT_IDS[:BATCH]


def test_keyset_advances_within_the_saturated_second_on_live_clickhouse(
    clickhouse_engine: QueryEngine,
) -> None:
    """The transpiled OR-decomposition keyset paginates *through* the saturated
    second on the real server — each page strictly after the last row's
    ``(processed_at, event_id)``, no overlap, no wedge, tail rows reached."""
    seen: list[str] = []
    cursor: tuple[str, str] | None = None
    for _ in range(10):  # 14 rows / batch 5 -> 3 pages; headroom, never a spin
        rows = clickhouse_engine.fetch_pipeline_events(
            limit=BATCH,
            min_processed_at=cursor[0] if cursor else SATURATED,
            min_event_id=cursor[1] if cursor else None,
        )
        if not rows:
            break
        seen.extend(str(row["event_id"]) for row in rows)
        last = rows[-1]
        cursor = (str(last["processed_at"]), str(last["event_id"]))

    assert seen == COHORT_IDS + [event_id for event_id, _ in AFTER]
    assert cursor == ("2026-07-10 10:00:02", "Z-AFTER-2")


async def test_dispatcher_drains_a_saturated_second_on_live_clickhouse(
    clickhouse_engine: QueryEngine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The full dispatcher loop against the live journal: every event in and
    after the saturated second is delivered exactly once and the scan cursor
    climbs past the second — the end-to-end property audit #1 said no test
    proved outside DuckDB."""
    app = SimpleNamespace(
        state=SimpleNamespace(
            query_engine=clickhouse_engine,
            webhook_config_path=tmp_path / "webhooks.yaml",
        )
    )
    create_webhook(app, url="https://keyset.test/hook", tenant="acme", filters=WebhookFilters())
    dispatcher = WebhookDispatcher(app, scan_batch_size=BATCH)

    delivered: list[str] = []

    async def _deliver(webhook: object, event: dict) -> dict:
        delivered.append(str(event["event_id"]))
        return {"success": True, "status_code": 200, "event_id": event["event_id"]}

    monkeypatch.setattr(dispatcher, "deliver", _deliver)

    # Drive the poll loop by hand, exactly like the DuckDB regression: the
    # keyset advances strictly each pass, so a bounded number of passes drains
    # the journal; a re-wedge surfaces as a failed assertion, never a spin.
    for _ in range(50):
        before = dispatcher._scan_cursor
        await dispatcher.dispatch_new_events()
        if dispatcher._scan_cursor == before:
            break

    expected = set(COHORT_IDS) | {event_id for event_id, _ in AFTER}
    assert set(delivered) == expected
    assert len(delivered) == len(expected), "idempotent enqueue + strict keyset: no duplicates"
    assert dispatcher._scan_cursor == ("2026-07-10 10:00:02", "Z-AFTER-2")
