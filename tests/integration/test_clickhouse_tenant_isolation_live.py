"""Two tenants, identical entity ids, one live ClickHouse (audit P0-1).

This is the acceptance test the audit asked for, and the one the project could
not have passed before ADR-004. Tenant isolation used to be a *schema
qualification*, and on ClickHouse that named a database nobody creates: an
authenticated read either died on `UNKNOWN_TABLE` or — with the qualification
dropped — shared one table *and one ReplacingMergeTree key* with every other
tenant, where two rows with the same `order_id` are two versions of one row and
the later insert destroys the earlier. No read-side filter can undo that, which
is why the boundary now lives in the physical schema and in the write key.

So the fixture plants the exact collision the old model could not survive: both
tenants get the same `order_id`, `user_id`, `session_id` and `product_id`, with
different rows behind them. Every read surface is then driven under both keys,
and the assertion is the same one every time: **nothing belonging to the other
tenant appears in the response** — not a row, not an id, not a snippet, not an
aggregate.

The DuckDB half of this proof is `tests/integration/test_tenant_isolation.py`
and `tests/property/test_tenant_isolation_properties.py`; those run everywhere.
This one needs a real server — `CLICKHOUSE_LIVE_HOST` (the `clickhouse` service
on the CI integration job; locally, any disposable instance). It provisions its
own database, so a shared `agentflow` store cannot blur what is asserted and the
foreign-tenant rows it plants cannot make an unscoped read elsewhere in the
session fail closed.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.serving.backends.clickhouse_backend import ClickHouseBackend
from src.serving.semantic_layer.query_engine import QueryEngine

LIVE_HOST = os.getenv("CLICKHOUSE_LIVE_HOST")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not LIVE_HOST,
        reason="CLICKHOUSE_LIVE_HOST not configured (live ClickHouse required)",
    ),
]

ACME = "acme"
DEMO = "demo"

# The collision. Every id below exists for *both* tenants.
SHARED_ORDER = "ORD-SHARED"
SHARED_USER = "USR-SHARED"
SHARED_SESSION = "SES-SHARED"
SHARED_PRODUCTS = ("PRD-SHARED-1", "PRD-SHARED-2", "PRD-SHARED-3")

# ...and one exclusive order each, so "did the other tenant's row come back?" has
# an answer that does not depend on reading the shared row's contents.
ACME_ONLY_ORDER = "ORD-ACME-ONLY"
DEMO_ONLY_ORDER = "ORD-DEMO-ONLY"

# Strings that exist in exactly one tenant's rows. If any of them appears in the
# other tenant's response — in a field, an id, or a search snippet — that is a
# leak, whatever the shape of the payload. Asserting against the raw response
# text means a new field on a response model cannot quietly open a hole this
# suite would not notice.
ACME_MARKERS = ("Widgetronic", "ORD-ACME-ONLY", "acme-confirmed", "EVT-ACME")
DEMO_MARKERS = ("Gadgetronic", "ORD-DEMO-ONLY", "demo-pending", "EVT-DEMO")

# Non-cancelled orders in the last 24h: 125.50 + 80.00 / 15.00 + 25.00.
ACME_REVENUE = 205.5
DEMO_REVENUE = 40.0

ACME_PRODUCTS = ("Widgetronic", "Widgetronic Mini", "Widgetronic Max")
DEMO_PRODUCTS = ("Gadgetronic", "Gadgetronic Mini", "Gadgetronic Max")


def _live_database() -> str:
    """A database of this suite's own.

    Sharing `agentflow` with the other live tests would mean sharing it with
    their demo seed and — worse — leaving two tenants' rows in a store the rest
    of the session reads unscoped, which is exactly what the fail-closed guard
    refuses to answer.
    """
    return f"{os.getenv('CLICKHOUSE_LIVE_DATABASE', 'agentflow')}_tenant_live"


def _backend(database: str) -> ClickHouseBackend:
    return ClickHouseBackend(
        host=LIVE_HOST or "localhost",
        port=int(os.getenv("CLICKHOUSE_LIVE_PORT", "8123")),
        user=os.getenv("CLICKHOUSE_LIVE_USER", "agentflow"),
        password=os.getenv("CLICKHOUSE_LIVE_PASSWORD", "agentflow"),
        database=database,
    )


def _ddl(backend: ClickHouseBackend, sql: str, *, use_database: bool = True) -> None:
    """Send a statement the query path will not carry.

    `execute()` is the SELECT path: it transpiles from DuckDB and asks for JSON
    back, neither of which a DROP DATABASE survives. This suite provisions its
    own store, so it talks to the server the way `ensure_schema` does.
    """
    backend._request(  # noqa: SLF001
        sql, expect_json=False, translate=False, use_database=use_database
    )


def _ts(minutes_ago: int) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%d %H:%M:%S")


def _seed(backend: ClickHouseBackend) -> None:
    backend.insert_rows(
        "orders_v2",
        [
            # Same order_id, same user_id, different rows. Under the old
            # single-column sorting key these two were one row, and one of them
            # was already gone by the time any read could be scoped.
            {
                "tenant_id": ACME,
                "order_id": SHARED_ORDER,
                "user_id": SHARED_USER,
                "status": "acme-confirmed",
                "total_amount": 125.50,
                "currency": "USD",
                "created_at": _ts(30),
            },
            {
                "tenant_id": DEMO,
                "order_id": SHARED_ORDER,
                "user_id": SHARED_USER,
                "status": "demo-pending",
                "total_amount": 15.00,
                "currency": "USD",
                "created_at": _ts(30),
            },
            {
                "tenant_id": ACME,
                "order_id": ACME_ONLY_ORDER,
                "user_id": "USR-ACME-2",
                "status": "delivered",
                "total_amount": 80.00,
                "currency": "USD",
                "created_at": _ts(60),
            },
            {
                "tenant_id": DEMO,
                "order_id": DEMO_ONLY_ORDER,
                "user_id": "USR-DEMO-2",
                "status": "pending",
                "total_amount": 25.00,
                "currency": "USD",
                "created_at": _ts(60),
            },
        ],
    )
    backend.insert_rows(
        "products_current",
        [
            {
                "tenant_id": tenant,
                "product_id": product_id,
                "name": name,
                "category": "tools",
                "price": price,
                "in_stock": 1,
                "stock_quantity": 7,
            }
            for tenant, names in ((ACME, ACME_PRODUCTS), (DEMO, DEMO_PRODUCTS))
            for product_id, name, price in zip(
                SHARED_PRODUCTS, names, (99.00, 49.00, 149.00), strict=True
            )
        ],
    )
    backend.insert_rows(
        "users_enriched",
        [
            {
                "tenant_id": ACME,
                "user_id": SHARED_USER,
                "total_orders": 2,
                "total_spent": ACME_REVENUE,
                "first_order_at": _ts(60),
                "last_order_at": _ts(30),
                "preferred_category": "tools",
            },
            {
                "tenant_id": DEMO,
                "user_id": SHARED_USER,
                "total_orders": 2,
                "total_spent": DEMO_REVENUE,
                "first_order_at": _ts(60),
                "last_order_at": _ts(30),
                "preferred_category": "toys",
            },
        ],
    )
    backend.insert_rows(
        "sessions_aggregated",
        [
            {
                "tenant_id": ACME,
                "session_id": SHARED_SESSION,
                "user_id": SHARED_USER,
                "started_at": _ts(20),
                "ended_at": _ts(10),
                "duration_seconds": 600.0,
                "event_count": 12,
                "unique_pages": 5,
                "funnel_stage": "checkout",
                "is_conversion": 1,
            },
            {
                "tenant_id": DEMO,
                "session_id": SHARED_SESSION,
                "user_id": SHARED_USER,
                "started_at": _ts(20),
                "ended_at": _ts(10),
                "duration_seconds": 120.0,
                "event_count": 3,
                "unique_pages": 1,
                "funnel_stage": "browse",
                "is_conversion": 0,
            },
        ],
    )
    backend.insert_rows(
        "pipeline_events",
        [
            # Both tenants' journals describe the *same* order id. The event ids
            # differ, so a lineage read that crossed over would say so in plain
            # text rather than hiding behind identical rows.
            {
                "event_id": f"EVT-{tenant.upper()}-{index}",
                "topic": topic,
                "tenant_id": tenant,
                "entity_id": SHARED_ORDER,
                "event_type": "order.created",
                "latency_ms": 120,
                "processed_at": _ts(5),
            }
            for tenant in (ACME, DEMO)
            for index, topic in enumerate(("orders.raw", "orders.enriched"))
        ],
    )


def _write_config(tmp_path: Path) -> tuple[Path, Path]:
    api_keys = tmp_path / "config" / "api_keys.yaml"
    tenants = tmp_path / "config" / "tenants.yaml"
    api_keys.parent.mkdir(parents=True, exist_ok=True)

    api_keys.write_text(
        "keys:\n"
        '  - key: "acme-key"\n'
        '    name: "Acme Agent"\n'
        f'    tenant: "{ACME}"\n'
        "    rate_limit_rpm: 1000\n"
        "    allowed_entity_types: null\n"
        '    created_at: "2026-07-11"\n'
        '  - key: "demo-key"\n'
        '    name: "Demo Agent"\n'
        f'    tenant: "{DEMO}"\n'
        "    rate_limit_rpm: 1000\n"
        "    allowed_entity_types: null\n"
        '    created_at: "2026-07-11"\n',
        encoding="utf-8",
        newline="\n",
    )
    tenants.write_text(
        "tenants:\n"
        f"  - id: {ACME}\n"
        '    display_name: "Acme Corp"\n'
        '    kafka_topic_prefix: "acme"\n'
        "    max_events_per_day: 1000000\n"
        "    max_api_keys: 10\n"
        "    allowed_entity_types: null\n"
        f"  - id: {DEMO}\n"
        '    display_name: "Demo Tenant"\n'
        '    kafka_topic_prefix: "demo"\n'
        "    max_events_per_day: 1000000\n"
        "    max_api_keys: 10\n"
        "    allowed_entity_types: null\n",
        encoding="utf-8",
        newline="\n",
    )
    return api_keys, tenants


@pytest.fixture(scope="module")
def live_clickhouse() -> Iterator[ClickHouseBackend]:
    database = _live_database()
    backend = _backend(database)
    # A clean store every run: the assertions below are exact sets, and a stale
    # row from an earlier version of this file would be indistinguishable from
    # a leak.
    _ddl(backend, f"DROP DATABASE IF EXISTS {database}", use_database=False)
    backend.ensure_schema()  # creates the database, and asserts the tenant-led sorting key
    _seed(backend)
    yield backend
    _ddl(backend, f"DROP DATABASE IF EXISTS {database}", use_database=False)


@pytest.fixture(scope="module")
def client(
    live_clickhouse: ClickHouseBackend,
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[TestClient]:
    from src.serving.api.main import app

    api_keys, tenants = _write_config(tmp_path_factory.mktemp("tenant-live"))
    patch = pytest.MonkeyPatch()
    patch.setenv("SERVING_BACKEND", "clickhouse")
    patch.setenv("CLICKHOUSE_HOST", LIVE_HOST or "localhost")
    patch.setenv("CLICKHOUSE_PORT", os.getenv("CLICKHOUSE_LIVE_PORT", "8123"))
    patch.setenv("CLICKHOUSE_USER", os.getenv("CLICKHOUSE_LIVE_USER", "agentflow"))
    patch.setenv("CLICKHOUSE_PASSWORD", os.getenv("CLICKHOUSE_LIVE_PASSWORD", "agentflow"))
    patch.setenv("CLICKHOUSE_DATABASE", _live_database())
    patch.setenv("DUCKDB_PATH", ":memory:")
    patch.setenv("AGENTFLOW_SEED_ON_BOOT", "false")
    patch.setenv("AGENTFLOW_API_KEYS_FILE", str(api_keys))
    patch.setenv("AGENTFLOW_TENANTS_FILE", str(tenants))

    # The search index is built once at boot from whatever the backend holds, so
    # the rows must already be in ClickHouse — `live_clickhouse` seeded them.
    with TestClient(app) as test_client:
        assert test_client.app.state.query_engine.backend.name == "clickhouse"
        yield test_client
    patch.undo()


@pytest.fixture(scope="module")
def engine(client: TestClient) -> QueryEngine:
    """The API's own engine: ClickHouse-backed, tenant router loaded."""
    return client.app.state.query_engine  # type: ignore[no-any-return]


def _headers(tenant: str) -> dict[str, str]:
    return {"X-API-Key": f"{tenant}-key"}


def _own_orders(tenant: str) -> set[str]:
    return {SHARED_ORDER, ACME_ONLY_ORDER if tenant == ACME else DEMO_ONLY_ORDER}


def _assert_no_foreign_markers(body: str, tenant: str) -> None:
    foreign = DEMO_MARKERS if tenant == ACME else ACME_MARKERS
    leaked = [marker for marker in foreign if marker in body]
    assert not leaked, f"{tenant} response leaked the other tenant's {leaked}: {body[:400]}"


# --- entity ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tenant", "expected_status"),
    [(ACME, "acme-confirmed"), (DEMO, "demo-pending")],
)
def test_shared_order_id_resolves_to_the_calling_tenants_row(
    client: TestClient, tenant: str, expected_status: str
) -> None:
    """The collision case: both tenants ask for the same order id."""
    response = client.get(f"/v1/entity/order/{SHARED_ORDER}", headers=_headers(tenant))

    assert response.status_code == 200
    assert response.json()["data"]["status"] == expected_status
    _assert_no_foreign_markers(response.text, tenant)


@pytest.mark.parametrize(
    ("tenant", "foreign_order"),
    [(ACME, DEMO_ONLY_ORDER), (DEMO, ACME_ONLY_ORDER)],
)
def test_the_other_tenants_order_is_absent_not_forbidden(
    client: TestClient, tenant: str, foreign_order: str
) -> None:
    """404, not 403: to this tenant the row does not exist. Any other answer
    confirms that it exists for somebody else."""
    response = client.get(f"/v1/entity/order/{foreign_order}", headers=_headers(tenant))

    assert response.status_code == 404


def test_entity_payload_does_not_carry_the_tenant_column(client: TestClient) -> None:
    """`SELECT * EXCLUDE (tenant_id)`, transpiled to ClickHouse's `EXCEPT`, is
    what keeps the boundary out of the entity contract. If it stopped working,
    the column would surface here first."""
    response = client.get(f"/v1/entity/order/{SHARED_ORDER}", headers=_headers(ACME))

    assert response.status_code == 200
    assert "tenant_id" not in response.json()["data"]


@pytest.mark.parametrize("tenant", [ACME, DEMO])
def test_shared_user_session_and_product_resolve_per_tenant(
    client: TestClient, tenant: str
) -> None:
    user = client.get(f"/v1/entity/user/{SHARED_USER}", headers=_headers(tenant))
    session = client.get(f"/v1/entity/session/{SHARED_SESSION}", headers=_headers(tenant))
    product = client.get(f"/v1/entity/product/{SHARED_PRODUCTS[0]}", headers=_headers(tenant))

    assert user.status_code == 200
    assert session.status_code == 200
    assert product.status_code == 200

    assert float(user.json()["data"]["total_spent"]) == (
        ACME_REVENUE if tenant == ACME else DEMO_REVENUE
    )
    assert session.json()["data"]["funnel_stage"] == ("checkout" if tenant == ACME else "browse")
    assert product.json()["data"]["name"] == (
        ACME_PRODUCTS[0] if tenant == ACME else DEMO_PRODUCTS[0]
    )
    for response in (user, session, product):
        _assert_no_foreign_markers(response.text, tenant)


@pytest.mark.parametrize("tenant", [ACME, DEMO])
def test_order_timeline_is_scoped(client: TestClient, tenant: str) -> None:
    response = client.get(f"/v1/entity/order/{SHARED_ORDER}/timeline", headers=_headers(tenant))

    assert response.status_code == 200
    assert response.json()["order"]["status"] == (
        "acme-confirmed" if tenant == ACME else "demo-pending"
    )
    _assert_no_foreign_markers(response.text, tenant)


# --- metric, historical ------------------------------------------------------


@pytest.mark.parametrize(("tenant", "revenue"), [(ACME, ACME_REVENUE), (DEMO, DEMO_REVENUE)])
def test_metric_aggregates_only_the_calling_tenants_rows(
    client: TestClient, tenant: str, revenue: float
) -> None:
    """An aggregate is where a missing predicate is *invisible*: the number is
    merely too large, and nothing in the payload says whose rows it summed."""
    response = client.get("/v1/metrics/revenue?window=24h", headers=_headers(tenant))

    assert response.status_code == 200
    assert response.json()["value"] == revenue


@pytest.mark.parametrize(("tenant", "revenue"), [(ACME, ACME_REVENUE), (DEMO, DEMO_REVENUE)])
def test_historical_read_is_scoped(client: TestClient, tenant: str, revenue: float) -> None:
    """`as_of` anchors NOW() to a literal timestamp — a second SQL path with its
    own transpile, which has to carry the predicate too."""
    as_of = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    response = client.get(f"/v1/metrics/revenue?window=24h&as_of={as_of}", headers=_headers(tenant))

    assert response.status_code == 200
    assert response.json()["value"] == revenue


# --- NL query, pagination, batch ---------------------------------------------


@pytest.mark.parametrize("tenant", [ACME, DEMO])
def test_nl_query_for_the_shared_order_returns_one_row(client: TestClient, tenant: str) -> None:
    """Free SQL, not a builder call: `_scope_sql` rewrites the table reference in
    the AST. Two rows back would mean it did not."""
    response = client.post(
        "/v1/query",
        json={"question": f"show me order {SHARED_ORDER}"},
        headers=_headers(tenant),
    )

    assert response.status_code == 200
    rows = response.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["status"] == ("acme-confirmed" if tenant == ACME else "demo-pending")
    _assert_no_foreign_markers(response.text, tenant)


@pytest.mark.parametrize("tenant", [ACME, DEMO])
def test_pagination_never_walks_into_the_other_tenant(engine: QueryEngine, tenant: str) -> None:
    """Three products per tenant behind three shared ids, walked one page at a
    time. The offset is applied *inside* the scoped relation, so page 2 is this
    tenant's second row — not the other tenant's first."""
    expected = set(ACME_PRODUCTS if tenant == ACME else DEMO_PRODUCTS)
    seen: set[str] = set()
    cursor: str | None = None

    for _ in range(6):  # bounded: 3 rows per tenant, so this must stop early
        page = engine.paginated_query("top 10 products", limit=1, cursor=cursor, tenant_id=tenant)
        seen.update(str(row["name"]) for row in page["data"])
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert cursor is None, "pagination did not terminate — it saw more rows than this tenant owns"
    assert seen == expected


@pytest.mark.parametrize("tenant", [ACME, DEMO])
def test_batch_items_are_each_scoped(client: TestClient, tenant: str) -> None:
    response = client.post(
        "/v1/batch",
        json={
            "requests": [
                {
                    "id": "e",
                    "type": "entity",
                    "params": {"entity_type": "order", "entity_id": SHARED_ORDER},
                },
                {
                    "id": "m",
                    "type": "metric",
                    "params": {"name": "revenue", "window": "24h"},
                },
                {
                    "id": "q",
                    "type": "query",
                    "params": {"question": f"show me order {SHARED_ORDER}"},
                },
            ]
        },
        headers=_headers(tenant),
    )

    assert response.status_code == 200
    results = {item["id"]: item for item in response.json()["results"]}
    assert all(item["status"] == "ok" for item in results.values()), results
    assert results["m"]["data"]["value"] == (ACME_REVENUE if tenant == ACME else DEMO_REVENUE)
    _assert_no_foreign_markers(response.text, tenant)


# --- search ------------------------------------------------------------------


@pytest.mark.parametrize("tenant", [ACME, DEMO])
def test_search_never_returns_the_other_tenants_snippet(client: TestClient, tenant: str) -> None:
    """The index is one corpus for every tenant (built once per process), so the
    tenant rides on the document and is filtered before scoring. A snippet is a
    leak even when the id behind it would have 404'd on the entity route."""
    foreign_term = "Gadgetronic" if tenant == ACME else "Widgetronic"

    response = client.get(f"/v1/search?q={foreign_term}", headers=_headers(tenant))

    assert response.status_code == 200
    entity_hits = [hit for hit in response.json()["results"] if hit["type"] == "entity"]
    assert entity_hits == [], f"{tenant} searched the other tenant's term and got rows back"
    # Only the results: the response echoes the query back, and the query *is*
    # the other tenant's term here — by construction, since that is the search
    # being attempted.
    _assert_no_foreign_markers(json.dumps(response.json()["results"]), tenant)


@pytest.mark.parametrize("tenant", [ACME, DEMO])
def test_search_still_finds_the_tenants_own_rows(client: TestClient, tenant: str) -> None:
    """The other half of the claim: the filter is not simply returning nothing."""
    own_term = "Widgetronic" if tenant == ACME else "Gadgetronic"

    response = client.get(f"/v1/search?q={own_term}", headers=_headers(tenant))

    assert response.status_code == 200
    entity_hits = [hit for hit in response.json()["results"] if hit["type"] == "entity"]
    assert entity_hits, f"{tenant} cannot find its own products"
    assert any(own_term in hit["snippet"] for hit in entity_hits)


def test_incremental_refresh_indexes_a_new_row_for_its_tenant_only(
    client: TestClient, live_clickhouse: ClickHouseBackend
) -> None:
    """Audit P1-6, the live half: a row that lands in ClickHouse after boot is
    picked up by the journal-cursor refresh — the targeted ``IN`` re-read
    through the real backend's sqlglot round trip, not a full rescan — and is
    visible to its own tenant only."""
    index = client.app.state.search_index
    # Everything seeded so far predates the boot rebuild's cursor.
    assert index.refresh() in {"noop", "incremental"}

    try:
        live_clickhouse.insert_rows(
            "orders_v2",
            [
                {
                    "tenant_id": ACME,
                    "order_id": "ORD-REFRESH-1",
                    "user_id": "USR-ACME-9",
                    "status": "refreshtastic",
                    "total_amount": 42.00,
                    "currency": "USD",
                    "created_at": _ts(0),
                }
            ],
        )
        live_clickhouse.insert_rows(
            "pipeline_events",
            [
                {
                    "event_id": "EVT-REFRESH-1",
                    "topic": "orders.raw",
                    "tenant_id": ACME,
                    "entity_id": "ORD-REFRESH-1",
                    "event_type": "order.created",
                    "latency_ms": 5,
                    "processed_at": _ts(0),
                }
            ],
        )

        assert index.refresh() == "incremental"

        response = client.get("/v1/search?q=refreshtastic", headers=_headers(ACME))
        assert response.status_code == 200
        entity_hits = [hit for hit in response.json()["results"] if hit["type"] == "entity"]
        assert [hit["id"] for hit in entity_hits] == ["ORD-REFRESH-1"]

        response = client.get("/v1/search?q=refreshtastic", headers=_headers(DEMO))
        assert response.status_code == 200
        assert [hit for hit in response.json()["results"] if hit["type"] == "entity"] == []
    finally:
        # The escape probes below assert EXACT row sets (their fixture warns a
        # stale row is indistinguishable from a leak) — take the rows back out,
        # synchronously, before any of them runs.
        _ddl(
            live_clickhouse,
            "ALTER TABLE orders_v2 DELETE WHERE order_id = 'ORD-REFRESH-1' "
            "SETTINGS mutations_sync = 1",
        )
        _ddl(
            live_clickhouse,
            "ALTER TABLE pipeline_events DELETE WHERE event_id = 'EVT-REFRESH-1' "
            "SETTINGS mutations_sync = 1",
        )


# --- lineage, SLO ------------------------------------------------------------


@pytest.mark.parametrize("tenant", [ACME, DEMO])
def test_lineage_reads_only_the_tenants_journal(client: TestClient, tenant: str) -> None:
    """Lineage reconstructs from `pipeline_events`. It used to read the embedded
    DuckDB whatever the configured backend was (audit P0-3); it now reads
    ClickHouse, where the journal predicate has to hold as well. Both tenants
    have events for this same order id."""
    response = client.get(f"/v1/lineage/order/{SHARED_ORDER}", headers=_headers(tenant))

    assert response.status_code == 200
    _assert_no_foreign_markers(response.text, tenant)


@pytest.mark.parametrize("tenant", [ACME, DEMO])
def test_slo_is_computed_per_tenant(client: TestClient, tenant: str) -> None:
    response = client.get("/v1/slo", headers=_headers(tenant))

    assert response.status_code == 200
    _assert_no_foreign_markers(response.text, tenant)


def test_sli_arithmetic_survives_the_clickhouse_transpile(
    client: TestClient, live_clickhouse: ClickHouseBackend
) -> None:
    """Audit P2-2, the live half: the SLI queries produce exact numbers
    through the real sqlglot round trip. The freshness SLI leans on
    LAG(...) OVER — where ClickHouse's lagInFrame hands the FIRST row a
    zero-date instead of NULL; without the epoch guard that row books a
    phantom threshold-sized credit (found live on 25.3, pinned here)."""
    from datetime import datetime as _datetime

    from src.serving.semantic_layer.journal import JournalReader, coerce_journal_datetime

    store_now = coerce_journal_datetime(live_clickhouse.execute("SELECT NOW() AS n")[0]["n"])
    assert isinstance(store_now, _datetime)
    live_clickhouse.insert_rows(
        "pipeline_events",
        [
            {
                "event_id": f"EVT-SLI-{index}",
                "topic": "orders.raw",
                "tenant_id": "sli-probe",
                "entity_id": f"ORD-SLI-{index}",
                "event_type": "order.created",
                "latency_ms": latency,
                "processed_at": (store_now - timedelta(seconds=age)).strftime("%Y-%m-%d %H:%M:%S"),
            }
            for index, (age, latency) in enumerate([(90, 50), (60, 150), (30, 80)])
        ],
    )
    try:
        journal = JournalReader(live_clickhouse)

        latency = journal.latency_within(threshold_ms=100, window="30 days", tenant_id="sli-probe")
        assert latency is not None
        assert (latency.total, latency.errors) == (3, 1)  # only the 150ms event is slow

        fresh = journal.freshness_within(
            threshold_seconds=20.0, window="30 days", tenant_id="sli-probe"
        )
        assert fresh is not None
        fresh_seconds, observed_seconds = fresh
        # Two 30s gaps capped at 20 each, plus a tail capped at 20 = 60.
        # A phantom first-row credit would make this 80.
        assert fresh_seconds == pytest.approx(60.0, abs=4.0)
        assert observed_seconds == pytest.approx(90.0, abs=10.0)
    finally:
        _ddl(
            live_clickhouse,
            "ALTER TABLE pipeline_events DELETE WHERE tenant_id = 'sli-probe' "
            "SETTINGS mutations_sync = 1",
        )


# --- adversarial SQL ---------------------------------------------------------


@pytest.mark.parametrize("tenant", [ACME, DEMO])
def test_qualified_table_name_cannot_escape_the_predicate(engine: QueryEngine, tenant: str) -> None:
    """A caller that names the table through its database — `agentflow.orders_v2`
    — must still be rewritten. `_scope_sql` replaces the reference wholesale,
    catalog and db included, precisely so that a qualified name is not a way out.
    """
    scoped = engine._scope_sql(  # noqa: SLF001
        f"SELECT * FROM {_live_database()}.orders_v2", tenant
    )
    rows = engine.backend.execute(scoped)

    assert {row["order_id"] for row in rows} == _own_orders(tenant)


@pytest.mark.parametrize("tenant", [ACME, DEMO])
def test_cte_shadowing_the_table_cannot_escape_the_predicate(
    engine: QueryEngine, tenant: str
) -> None:
    """`WITH orders_v2 AS (SELECT * FROM orders_v2) SELECT * FROM orders_v2`: the
    inner reference is physical, the outer one is the CTE. Scope resolution has
    to tell them apart — a global name match would skip both and read every
    tenant's rows."""
    hostile = "WITH orders_v2 AS (SELECT * FROM orders_v2) SELECT * FROM orders_v2"

    scoped = engine._scope_sql(hostile, tenant)  # noqa: SLF001
    rows = engine.backend.execute(scoped)

    assert {row["order_id"] for row in rows} == _own_orders(tenant)


def test_recursive_cte_shadowing_the_table_is_refused(engine: QueryEngine) -> None:
    """A recursive CTE keeps its own name in its body scope, so the physical
    anchor reference cannot be told apart from the self-reference. There is no
    safe rewrite, so it is refused rather than served unscoped."""
    hostile = (
        "WITH RECURSIVE orders_v2 AS ("
        "SELECT * FROM orders_v2 UNION ALL SELECT * FROM orders_v2"
        ") SELECT * FROM orders_v2"
    )

    with pytest.raises(ValueError, match="Recursive CTE shadows"):
        engine._scope_sql(hostile, ACME)  # noqa: SLF001


def test_unscoped_read_of_a_multi_tenant_store_fails_closed(engine: QueryEngine) -> None:
    """No tenant context against a store holding foreign-tenant rows: refuse.
    Answering would hand the caller every tenant's data, so a 503 is the honest
    reply — and under auth the middleware never produces this state anyway."""
    with pytest.raises(ValueError, match="Tenant context is required"):
        engine.get_entity("order", SHARED_ORDER, tenant_id=None)
