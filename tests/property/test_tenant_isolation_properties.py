from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb
import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from src.serving.semantic_layer.catalog import DataCatalog
from src.serving.semantic_layer.query_engine import QueryEngine

_TENANT_IDS = st.sampled_from(["acme", "demo"])
_EXPECTED_USER_IDS = {
    "acme": "USR-ACME",
    "demo": "USR-DEMO",
}
_EXPECTED_REVENUE = {
    "acme": 205.5,
    "demo": 40.0,
}
_EXCLUSIVE_ORDER_IDS = {
    "acme": "ORD-ACME",
    "demo": "ORD-DEMO",
}


def _write_tenants(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (
            "tenants:\n"
            "  - id: acme\n"
            "    display_name: \"Acme Corp\"\n"
            "    kafka_topic_prefix: \"acme\"\n"
            "    duckdb_schema: \"acme\"\n"
            "    max_events_per_day: 1000000\n"
            "    max_api_keys: 10\n"
            "    allowed_entity_types: null\n"
            "  - id: demo\n"
            "    display_name: \"Demo Tenant\"\n"
            "    kafka_topic_prefix: \"demo\"\n"
            "    duckdb_schema: \"demo\"\n"
            "    max_events_per_day: 10000\n"
            "    max_api_keys: 2\n"
            "    allowed_entity_types:\n"
            "      - \"order\"\n"
            "      - \"product\"\n"
        ),
        encoding="utf-8",
        newline="\n",
    )


def _seed_tenant_data(db_path: Path) -> None:
    conn = duckdb.connect(str(db_path))
    try:
        for schema in ("acme", "demo"):
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {schema}.orders_v2 (
                    order_id VARCHAR PRIMARY KEY,
                    user_id VARCHAR,
                    status VARCHAR,
                    total_amount DECIMAL(10,2),
                    currency VARCHAR,
                    created_at TIMESTAMP
                )
                """
            )
            conn.execute(f"DELETE FROM {schema}.orders_v2")

        conn.execute(
            """
            INSERT INTO acme.orders_v2 VALUES
            ('ORD-SHARED', 'USR-ACME', 'confirmed', 125.50, 'USD', NOW()),
            ('ORD-ACME', 'USR-ACME-2', 'delivered', 80.00, 'USD', NOW())
            """
        )
        conn.execute(
            """
            INSERT INTO demo.orders_v2 VALUES
            ('ORD-SHARED', 'USR-DEMO', 'confirmed', 15.00, 'USD', NOW()),
            ('ORD-DEMO', 'USR-DEMO-2', 'pending', 25.00, 'USD', NOW())
            """
        )
    finally:
        conn.close()


def _build_tenant_engine(base_path: Path) -> QueryEngine:
    db_path = base_path / "tenant-isolation.duckdb"
    tenants_path = base_path / "config" / "tenants.yaml"
    _write_tenants(tenants_path)
    _seed_tenant_data(db_path)
    return QueryEngine(
        catalog=DataCatalog(),
        db_path=str(db_path),
        tenants_config_path=tenants_path,
    )


@given(tenant_id=_TENANT_IDS)
def test_shared_entity_id_resolves_to_tenant_scoped_data(tenant_id: str) -> None:
    with TemporaryDirectory() as temp_dir:
        tenant_engine = _build_tenant_engine(Path(temp_dir))
        order = tenant_engine.get_entity("order", "ORD-SHARED", tenant_id=tenant_id)

        assert order is not None
        assert order["user_id"] == _EXPECTED_USER_IDS[tenant_id]


@given(owner_tenant=_TENANT_IDS, other_tenant=_TENANT_IDS)
def test_cross_tenant_entity_lookup_does_not_leak_data(
    owner_tenant: str,
    other_tenant: str,
) -> None:
    assume(owner_tenant != other_tenant)

    with TemporaryDirectory() as temp_dir:
        tenant_engine = _build_tenant_engine(Path(temp_dir))
        result = tenant_engine.get_entity(
            "order",
            _EXCLUSIVE_ORDER_IDS[owner_tenant],
            tenant_id=other_tenant,
        )

        assert result is None


@given(tenant_id=_TENANT_IDS)
def test_metrics_are_scoped_to_the_requested_tenant(tenant_id: str) -> None:
    with TemporaryDirectory() as temp_dir:
        tenant_engine = _build_tenant_engine(Path(temp_dir))
        metric = tenant_engine.get_metric("revenue", window="24h", tenant_id=tenant_id)

        assert metric["value"] == _EXPECTED_REVENUE[tenant_id]


@given(order_id=st.sampled_from(["ORD-SHARED", "ORD-ACME", "ORD-DEMO"]))
def test_missing_tenant_context_fails_closed(order_id: str) -> None:
    with TemporaryDirectory() as temp_dir:
        tenant_engine = _build_tenant_engine(Path(temp_dir))

        with pytest.raises(ValueError, match="Tenant context is required"):
            tenant_engine.get_entity("order", order_id, tenant_id=None)
