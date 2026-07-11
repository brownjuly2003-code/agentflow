"""Tenant isolation as a property, not an example (ADR-004, audit P0-1).

The integration suite pins the two-tenant case by hand. This one states the
invariant the `tenant_id` column has to satisfy for *any* pair of tenants and
*any* entity id: **a read scoped to a tenant returns that tenant's rows and no
others** — in both directions, so "isolated" cannot be satisfied by returning
nothing at all.

These properties are what the old schema-per-tenant model could not have held.
It expressed the boundary as a schema qualification (`"acme"."orders_v2"`), and
nothing in `src/` ever issued `CREATE SCHEMA` — so a scoped read hit a relation
that did not exist, and an unscoped one read the shared table. The suite stayed
green because the scoping silently did nothing.

Rows accumulate across examples on purpose: the store is built once and every
example adds another tenant's rows to it. An invariant that survives a store
holding a hundred tenants' colliding ids is a stronger claim than one checked
against a store holding two.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from src.serving.semantic_layer.catalog import DataCatalog
from src.serving.semantic_layer.query_engine import QueryEngine

# The shape a tenant id may actually have (`SQLBuilderMixin._TENANT_ID_RE`).
# Tenant ids reach ClickHouse SQL as inlined literals — its `execute(params=...)`
# is a documented no-op — so the boundary validates them rather than trusting
# them, and this is the set it accepts.
_TENANT_IDS = st.from_regex(r"\A[A-Za-z0-9][A-Za-z0-9_.-]{0,20}\Z")

# ...and ids it must refuse: quotes, statement separators, whitespace, control
# characters, non-ASCII, the empty string. A tenant id is config, never request
# data — but the predicate built from it *is* the isolation boundary, so "it
# comes from a trusted place" is not the property being asserted here.
#
# The control characters are spelled `chr(n)` rather than as escapes so that the
# hostile input cannot be silently normalized away by whatever writes this file.
_HOSTILE_TENANT_IDS = st.sampled_from(
    [
        "",
        "'",
        "acme' OR '1'='1",
        "acme'; DROP TABLE orders_v2; --",
        "acme corp",
        "-leading-dash",
        "acme" + chr(9),  # tab
        "acme" + chr(10),  # newline
        "acme" + chr(0),  # NUL
        "acme" + chr(32),  # trailing space
        "acme" + chr(92),  # backslash
        "ак" * 40,  # non-ASCII, and over the length cap
    ]
)

_ENTITY_IDS = st.from_regex(r"\AORD-[A-Z0-9]{1,10}\Z")


@pytest.fixture(scope="module")
def engine(tmp_path_factory: pytest.TempPathFactory) -> Iterator[QueryEngine]:
    """One in-memory store, shared by every example.

    A tenants config has to exist for the fail-closed guard to be reachable:
    with no config at all the deployment is single-tenant by definition, the
    read resolves to `DEFAULT_TENANT`, and there is nothing to refuse.
    """
    tenants = tmp_path_factory.mktemp("tenancy") / "tenants.yaml"
    tenants.write_text(
        "tenants:\n"
        "  - id: default\n"
        '    display_name: "Default"\n'
        '    kafka_topic_prefix: "default"\n'
        "    max_events_per_day: 1000000\n"
        "    max_api_keys: 10\n"
        "    allowed_entity_types: null\n",
        encoding="utf-8",
        newline="\n",
    )
    instance = QueryEngine(
        catalog=DataCatalog(),
        db_path=":memory:",
        tenants_config_path=tenants,
    )
    try:
        yield instance
    finally:
        instance.close()


def _insert_order(
    engine: QueryEngine,
    tenant: str,
    order_id: str,
    user_id: str,
    amount: float,
) -> None:
    engine._conn.execute(  # noqa: SLF001
        """
        INSERT OR REPLACE INTO orders_v2
            (tenant_id, order_id, user_id, status, total_amount, currency, created_at)
        VALUES (?, ?, ?, 'confirmed', ?, 'USD', NOW())
        """,
        [tenant, order_id, user_id, amount],
    )


@settings(max_examples=40)
@given(tenant_a=_TENANT_IDS, tenant_b=_TENANT_IDS, order_id=_ENTITY_IDS)
def test_two_tenants_sharing_an_entity_id_each_read_their_own_row(
    engine: QueryEngine, tenant_a: str, tenant_b: str, order_id: str
) -> None:
    """The collision. One id, two tenants, two rows — not one row that the second
    write destroyed. The composite key `(tenant_id, order_id)` is what makes that
    true; the predicate is what keeps each read on its own side of it."""
    assume(tenant_a != tenant_b)

    _insert_order(engine, tenant_a, order_id, f"USR-{tenant_a}", 10.0)
    _insert_order(engine, tenant_b, order_id, f"USR-{tenant_b}", 20.0)

    row_a = engine.get_entity("order", order_id, tenant_id=tenant_a)
    row_b = engine.get_entity("order", order_id, tenant_id=tenant_b)

    assert row_a is not None
    assert row_b is not None
    assert row_a["user_id"] == f"USR-{tenant_a}"
    assert row_b["user_id"] == f"USR-{tenant_b}"


@settings(max_examples=40)
@given(owner=_TENANT_IDS, reader=_TENANT_IDS, order_id=_ENTITY_IDS)
def test_a_tenant_never_reads_a_row_it_does_not_own(
    engine: QueryEngine, owner: str, reader: str, order_id: str
) -> None:
    """The other direction: an id that exists, but not for you, is not found.
    Not 'forbidden' — not found, which is the only answer that does not confirm
    it exists for somebody else."""
    assume(owner != reader)

    # The id names its owner. Rows accumulate across examples, so an id built
    # only from `order_id` could have been written under `reader` by an earlier
    # example — and this test would then be asserting the absence of a row that
    # the reader legitimately owns.
    exclusive_id = f"{order_id}-{owner}"
    _insert_order(engine, owner, exclusive_id, f"USR-{owner}", 10.0)

    assert engine.get_entity("order", exclusive_id, tenant_id=reader) is None


@settings(max_examples=40)
@given(tenant=_TENANT_IDS, order_id=_ENTITY_IDS)
def test_the_tenant_column_never_reaches_the_payload(
    engine: QueryEngine, tenant: str, order_id: str
) -> None:
    """`SELECT * EXCLUDE (tenant_id)` keeps the boundary out of the entity
    contract, so the two stores stay column-identical and no caller learns the
    name of a tenant it is not."""
    _insert_order(engine, tenant, order_id, f"USR-{tenant}", 10.0)

    row = engine.get_entity("order", order_id, tenant_id=tenant)

    assert row is not None
    assert "tenant_id" not in row


@settings(max_examples=40)
@given(tenant=_TENANT_IDS, order_id=_ENTITY_IDS, amount=st.floats(1.0, 10_000.0, width=32))
def test_an_aggregate_sums_only_the_readers_rows(
    engine: QueryEngine, tenant: str, order_id: str, amount: float
) -> None:
    """Aggregates are where a lost predicate hides: the answer is merely too
    large, and nothing in the payload says whose rows it summed."""
    # A tenant of this example's own: keyed by the order id too, so a repeated
    # tenant with a different order cannot leave the store holding two of this
    # tenant's rows and make the expected total wrong. A repeat of the same pair
    # overwrites its own row (the primary key is `(tenant_id, order_id)`).
    scoped_tenant = f"agg-{tenant}-{order_id}"
    _insert_order(engine, scoped_tenant, order_id, f"USR-{scoped_tenant}", amount)

    metric = engine.get_metric("revenue", window="24h", tenant_id=scoped_tenant)

    assert metric["value"] == pytest.approx(round(amount, 2), abs=0.01)


@given(hostile=_HOSTILE_TENANT_IDS)
def test_a_string_that_cannot_be_a_tenant_id_is_refused(engine: QueryEngine, hostile: str) -> None:
    """The predicate inlines the tenant id as a SQL literal on the ClickHouse
    path, so the one thing it must never do is inline something that is not a
    tenant id. It validates and refuses; it does not escape and hope."""
    with pytest.raises(ValueError, match="Invalid tenant id"):
        engine.get_entity("order", "ORD-1", tenant_id=hostile)


@given(order_id=_ENTITY_IDS)
def test_a_read_without_tenant_context_is_refused_once_the_store_is_shared(
    engine: QueryEngine, order_id: str
) -> None:
    """No tenant context against a store that holds more than one tenant's rows:
    refuse. Answering would hand the caller every tenant's data. A single-tenant
    store — everything under `DEFAULT_TENANT` — has nothing to leak and stays
    readable, which is why the guard asks the store rather than the config."""
    _insert_order(engine, "some-other-tenant", order_id, "USR-1", 10.0)

    with pytest.raises(ValueError, match="Tenant context is required"):
        engine.get_entity("order", order_id, tenant_id=None)
