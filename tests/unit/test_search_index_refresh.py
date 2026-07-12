"""Incremental search maintenance (audit P1-6).

The periodic tick used to full-scan and re-tokenize every entity table every
60 seconds, per replica, forever. ``refresh()`` reads the journal past a
cursor instead: a quiet journal costs one bounded read and zero table scans,
a small change-set costs targeted ``IN`` reads of exactly the changed rows —
and the result must be indistinguishable from a full rebuild, which is the
equivalence these tests pin. Deletion, window overflow, the scheduled full
pass, and the memory shape are covered here too; the live end of the same
surface stays in ``tests/integration/test_search.py``.
"""

from __future__ import annotations

import tracemalloc
from datetime import datetime, timedelta

from src.serving.semantic_layer.catalog import EntityDefinition
from src.serving.semantic_layer.search_index import SearchDocument, SearchIndex

T0 = datetime(2026, 7, 12, 12, 0, 0)


class FakeCatalog:
    def __init__(self, entities: dict[str, EntityDefinition]) -> None:
        self.entities = entities
        self.metrics: dict = {}


class FakeEngine:
    """In-memory stand-in for the query engine's three index-facing reads."""

    def __init__(self) -> None:
        self.tables: dict[str, dict[tuple[str, str], dict]] = {}
        self.journal: list[dict] = []
        self.full_scans = 0
        self.targeted_scans: list[tuple[str, tuple[str, ...]]] = []

    def add_row(self, table: str, row: dict, *, primary_key: str) -> None:
        self.tables.setdefault(table, {})[(row["tenant_id"], str(row[primary_key]))] = row

    def journal_event(self, processed_at: datetime, **columns: object) -> None:
        self.journal.append({"processed_at": processed_at, **columns})

    def scan_entity_rows(self, table_name: str, *, limit: int) -> list[dict]:
        self.full_scans += 1
        return list(self.tables.get(table_name, {}).values())[:limit]

    def scan_entity_rows_by_ids(
        self, table_name: str, *, primary_key: str, ids: list[str]
    ) -> list[dict]:
        self.targeted_scans.append((table_name, tuple(ids)))
        wanted = set(ids)
        return [
            row
            for row in self.tables.get(table_name, {}).values()
            if str(row[primary_key]) in wanted
        ]

    def fetch_pipeline_events(
        self,
        *,
        limit: int | None = None,
        newest_first: bool = False,
        min_processed_at: datetime | None = None,
    ) -> list[dict]:
        rows = sorted(self.journal, key=lambda row: row["processed_at"], reverse=newest_first)
        if min_processed_at is not None:
            rows = [row for row in rows if row["processed_at"] >= min_processed_at]
        return rows[: limit if limit is not None else len(rows)]


def _order_entity() -> EntityDefinition:
    return EntityDefinition(
        name="order",
        description="Customer order",
        table="orders_v2",
        primary_key="order_id",
        fields={"status": "Order status"},
    )


def _user_entity() -> EntityDefinition:
    return EntityDefinition(
        name="user",
        description="Enriched user",
        table="users_enriched",
        primary_key="user_id",
        fields={"preferred_category": "Preferred category"},
    )


def _order_row(order_id: str, *, tenant: str = "acme", status: str = "pending") -> dict:
    return {
        "tenant_id": tenant,
        "order_id": order_id,
        "status": status,
        "total_amount": 120,
        "currency": "RUB",
        "user_id": f"user-of-{order_id}",
    }


def _build() -> tuple[SearchIndex, FakeEngine]:
    engine = FakeEngine()
    engine.add_row("orders_v2", _order_row("o1"), primary_key="order_id")
    engine.add_row("orders_v2", _order_row("o2", status="shipped"), primary_key="order_id")
    engine.add_row(
        "users_enriched",
        {"tenant_id": "acme", "user_id": "u1", "preferred_category": "books"},
        primary_key="user_id",
    )
    engine.journal_event(T0, entity_id="o1", event_type="order.created")
    catalog = FakeCatalog({"order": _order_entity(), "user": _user_entity()})
    index = SearchIndex(catalog=catalog, query_engine=engine)  # type: ignore[arg-type]
    index.rebuild()
    return index, engine


def _index_state(index: SearchIndex) -> tuple[dict, dict]:
    documents = {
        key: (document.snippet, dict(document.tokens), document.tenant_id)
        for key, document in index._documents.items()
    }
    return documents, dict(index._document_frequency)


def test_quiet_journal_costs_no_table_scans() -> None:
    index, engine = _build()
    scans_after_rebuild = engine.full_scans

    assert index.refresh() == "noop"
    assert index.refresh() == "noop"

    assert engine.full_scans == scans_after_rebuild
    assert engine.targeted_scans == []


def test_incremental_refresh_equals_a_full_rebuild() -> None:
    index, engine = _build()
    scans_after_rebuild = engine.full_scans

    # One row changes, one appears; the journal names them.
    engine.add_row("orders_v2", _order_row("o1", status="delivered"), primary_key="order_id")
    engine.add_row("orders_v2", _order_row("o3", status="pending"), primary_key="order_id")
    engine.journal_event(T0 + timedelta(seconds=5), entity_id="o1", event_type="order.updated")
    engine.journal_event(T0 + timedelta(seconds=6), entity_id="o3", event_type="order.created")

    assert index.refresh() == "incremental"
    assert engine.full_scans == scans_after_rebuild  # no table was re-scanned wholesale
    assert {table for table, _ in engine.targeted_scans} == {"orders_v2", "users_enriched"}

    # The incremental state is byte-equivalent to starting over.
    reference = SearchIndex(catalog=index.catalog, query_engine=engine)  # type: ignore[arg-type]
    reference.rebuild()
    assert _index_state(index) == _index_state(reference)

    # And the change is visible to search.
    hits = index.search("delivered", tenant_id="acme")
    assert [hit["id"] for hit in hits] == ["o1"]


def test_refresh_updates_one_tenant_without_touching_the_other() -> None:
    index, engine = _build()
    # Same order_id under a second tenant — a legitimate collision (P0-1).
    engine.add_row("orders_v2", _order_row("o1", tenant="globex"), primary_key="order_id")
    engine.journal_event(T0 + timedelta(seconds=5), entity_id="o1", event_type="order.created")
    assert index.refresh() == "incremental"

    engine.add_row(
        "orders_v2", _order_row("o1", tenant="globex", status="cancelled"), primary_key="order_id"
    )
    engine.journal_event(T0 + timedelta(seconds=9), entity_id="o1", event_type="order.updated")
    assert index.refresh() == "incremental"

    assert [hit["id"] for hit in index.search("cancelled", tenant_id="globex")] == ["o1"]
    assert index.search("cancelled", tenant_id="acme") == []


def test_refresh_drops_documents_for_deleted_rows() -> None:
    index, engine = _build()
    assert index.search("shipped", tenant_id="acme")

    del engine.tables["orders_v2"][("acme", "o2")]
    engine.journal_event(T0 + timedelta(seconds=5), entity_id="o2", event_type="order.deleted")

    assert index.refresh() == "incremental"
    assert index.search("shipped", tenant_id="acme") == []
    reference = SearchIndex(catalog=index.catalog, query_engine=engine)  # type: ignore[arg-type]
    reference.rebuild()
    assert _index_state(index) == _index_state(reference)


def test_window_overflow_falls_back_to_a_full_rebuild() -> None:
    index, engine = _build()
    index._refresh_window_rows = 2
    for second in range(3):
        engine.journal_event(
            T0 + timedelta(seconds=5 + second), entity_id=f"o{second}", event_type="order.updated"
        )

    assert index.refresh() == "full:overflow"


def test_oversized_change_set_falls_back_to_a_full_rebuild() -> None:
    index, engine = _build()
    index._changed_ids_limit = 1
    engine.journal_event(T0 + timedelta(seconds=5), entity_id="o1", event_type="order.updated")
    engine.journal_event(T0 + timedelta(seconds=6), entity_id="o2", event_type="order.updated")

    assert index.refresh() == "full:changed-set"


def test_scheduled_full_rebuild_is_the_safety_net() -> None:
    index, engine = _build()
    index._full_rebuild_ticks = 3

    # A writer that bypasses the journal: the row changes, no event lands.
    engine.add_row("orders_v2", _order_row("o1", status="delivered"), primary_key="order_id")

    assert index.refresh() == "noop"
    assert index.refresh() == "noop"
    assert index.search("delivered", tenant_id="acme") == []  # staleness is bounded...
    assert index.refresh() == "full:scheduled"
    assert [hit["id"] for hit in index.search("delivered", tenant_id="acme")] == ["o1"]


def test_incremental_memory_stays_far_below_a_rebuild() -> None:
    """The audit's scale probe: a refresh over a small change-set must not
    re-materialize the corpus. Measured, not asserted from vibes: allocation
    during a 10-row refresh over a 3000-row corpus must stay well under the
    full rebuild's, and no wholesale table scan may run."""
    engine = FakeEngine()
    for number in range(3000):
        engine.add_row(
            "orders_v2",
            _order_row(f"o{number}", status=("shipped", "pending", "delivered")[number % 3]),
            primary_key="order_id",
        )
    engine.journal_event(T0, entity_id="o0", event_type="order.created")
    catalog = FakeCatalog({"order": _order_entity()})
    index = SearchIndex(catalog=catalog, query_engine=engine)  # type: ignore[arg-type]

    tracemalloc.start()
    index.rebuild()
    _, rebuild_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    for number in range(10):
        engine.add_row(
            "orders_v2", _order_row(f"o{number}", status="cancelled"), primary_key="order_id"
        )
        engine.journal_event(
            T0 + timedelta(seconds=1 + number),
            entity_id=f"o{number}",
            event_type="order.updated",
        )
    scans_after_rebuild = engine.full_scans

    tracemalloc.start()
    outcome = index.refresh()
    _, refresh_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert outcome == "incremental"
    assert engine.full_scans == scans_after_rebuild
    assert refresh_peak < rebuild_peak / 5
    assert len(index.search("cancelled", tenant_id="acme", limit=20)) == 10


def test_documents_swap_atomically_during_refresh() -> None:
    """search() iterates the live dict from the event loop while refresh()
    runs in a worker thread — the refresh must swap a new dict in, never
    mutate the one a concurrent iteration may hold."""
    index, engine = _build()
    live_documents = index._documents

    engine.add_row("orders_v2", _order_row("o1", status="delivered"), primary_key="order_id")
    engine.journal_event(T0 + timedelta(seconds=5), entity_id="o1", event_type="order.updated")
    assert index.refresh() == "incremental"

    assert index._documents is not live_documents
    key = ("entity", "order", "acme", "o1")
    assert "delivered" in index._documents[key].snippet
    assert "delivered" not in live_documents[key].snippet


def test_search_document_shape_is_pinned() -> None:
    # The incremental path keys documents by (type, entity, tenant, id); a
    # field rename here must fail loudly, not silently re-key the corpus.
    document = SearchDocument(
        doc_type="entity",
        doc_id="o1",
        entity_type="order",
        endpoint="/v1/entity/order/o1",
        snippet="Order o1",
        tokens=None,  # type: ignore[arg-type]
        tenant_id="acme",
    )
    assert SearchIndex._document_key(document) == ("entity", "order", "acme", "o1")
