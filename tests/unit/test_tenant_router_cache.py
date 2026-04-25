from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

from src.ingestion.tenant_router import TenantRouter
from src.serving.semantic_layer.catalog import DataCatalog
from src.serving.semantic_layer.query.sql_builder import SQLBuilderMixin


def test_tenant_router_reuses_loaded_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    tenants_path = tmp_path / "tenants.yaml"
    tenants_path.write_text(
        (
            "tenants:\n"
            "  - id: demo\n"
            '    display_name: "Demo Tenant"\n'
            '    kafka_topic_prefix: "demo"\n'
            '    duckdb_schema: "demo"\n'
            "    max_events_per_day: 10000\n"
            "    max_api_keys: 2\n"
        ),
        encoding="utf-8",
        newline="\n",
    )
    original_read_text = Path.read_text
    read_count = 0

    def counted_read_text(self: Path, *args, **kwargs) -> str:
        nonlocal read_count
        if self == tenants_path:
            read_count += 1
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counted_read_text)
    router = TenantRouter(tenants_path)

    assert router.get_duckdb_schema("demo") == "demo"
    assert router.get_duckdb_schema("demo") == "demo"
    assert read_count == 1


class _TenantRouterStub:
    def __init__(self) -> None:
        self.load_calls = 0

    def has_config(self) -> bool:
        return True

    def load(self):
        self.load_calls += 1
        return SimpleNamespace(
            tenants=[
                SimpleNamespace(duckdb_schema="acme"),
                SimpleNamespace(duckdb_schema="demo"),
            ]
        )

    def get_duckdb_schema(self, tenant_id: str | None) -> str | None:
        assert tenant_id is None
        return None


class _QualificationHost(SQLBuilderMixin):
    def __init__(self) -> None:
        self.catalog = DataCatalog()
        self.tenant_router_stub = _TenantRouterStub()
        self._tenant_router = cast(TenantRouter, self.tenant_router_stub)
        self._qualified_table_cache: dict[tuple[str, str | None], str] = {}
        self.table_column_calls: list[str] = []

    def _table_columns(self, table_name: str) -> set[str]:
        self.table_column_calls.append(table_name)
        return set()


def test_table_qualification_reuses_no_tenant_resolution() -> None:
    host = _QualificationHost()

    assert host._qualify_table("orders_v2", tenant_id=None) == "orders_v2"
    assert host._qualify_table("orders_v2", tenant_id=None) == "orders_v2"

    assert host.tenant_router_stub.load_calls == 1
    assert host.table_column_calls == ['"acme"."orders_v2"', '"demo"."orders_v2"']
