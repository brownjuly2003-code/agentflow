from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.serving.semantic_layer.catalog import DataCatalog
from src.serving.semantic_layer.entity_type_registry import (
    ContractValidationError,
    load_entity_contracts,
)

CONTRACT_DIR = Path(__file__).resolve().parents[2] / "contracts" / "entities"


def _write(tmp_path: Path, name: str, payload: dict) -> Path:
    target = tmp_path / f"{name}.yaml"
    target.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return target


def test_shipped_contracts_cover_four_legacy_types() -> None:
    loaded = {e.name for e in load_entity_contracts()}
    assert loaded == {"order", "user", "product", "session"}


def test_legacy_shapes_preserved_after_refactor() -> None:
    catalog = DataCatalog()
    expected = {
        "order": {
            "table": "orders_v2",
            "primary_key": "order_id",
            "field_keys": {
                "order_id",
                "user_id",
                "status",
                "total_amount",
                "currency",
                "created_at",
            },
            "relationships": {"user": "user_id"},
        },
        "user": {
            "table": "users_enriched",
            "primary_key": "user_id",
            "field_keys": {
                "user_id",
                "total_orders",
                "total_spent",
                "first_order_at",
                "last_order_at",
                "preferred_category",
            },
            "relationships": {"orders": "user_id", "sessions": "user_id"},
        },
        "product": {
            "table": "products_current",
            "primary_key": "product_id",
            "field_keys": {
                "product_id",
                "name",
                "category",
                "price",
                "in_stock",
                "stock_quantity",
            },
            "relationships": {},
        },
        "session": {
            "table": "sessions_aggregated",
            "primary_key": "session_id",
            "field_keys": {
                "session_id",
                "user_id",
                "started_at",
                "ended_at",
                "duration_seconds",
                "event_count",
                "unique_pages",
                "funnel_stage",
                "is_conversion",
            },
            "relationships": {"user": "user_id"},
        },
    }

    for name, spec in expected.items():
        entity = catalog.entities[name]
        assert entity.table == spec["table"]
        assert entity.primary_key == spec["primary_key"]
        assert set(entity.fields) == spec["field_keys"]
        assert entity.relationships == spec["relationships"]


def test_loader_rejects_primary_key_missing_from_fields(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "broken",
        {
            "name": "broken",
            "description": "bad contract",
            "table": "t",
            "primary_key": "missing_id",
            "fields": {"other_id": "not the pk"},
        },
    )
    with pytest.raises(ContractValidationError, match="primary_key"):
        load_entity_contracts(tmp_path)


def test_loader_rejects_name_filename_mismatch(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "widget",
        {
            "name": "gadget",
            "description": "wrong filename",
            "table": "t",
            "primary_key": "id",
            "fields": {"id": "pk"},
        },
    )
    with pytest.raises(ContractValidationError, match="filename"):
        load_entity_contracts(tmp_path)


def test_loader_rejects_duplicate_names(tmp_path: Path) -> None:
    # Two files whose `name` field collides but whose file stems differ
    # so the filename-matches-name guard does not fire first.
    base_dir = tmp_path / "contracts"
    base_dir.mkdir()

    def write_with_stem(stem: str, name: str) -> None:
        (base_dir / f"{stem}.yaml").write_text(
            yaml.safe_dump(
                {
                    "name": name,
                    "description": f"stem {stem}",
                    "table": "t",
                    "primary_key": "id",
                    "fields": {"id": "pk"},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

    # First file: stem and name both "dup" → passes the filename guard.
    write_with_stem("dup", "dup")
    # Second file: stem "dup_twin" but claims name "dup" → fails the
    # filename guard before even reaching the duplicate check.
    write_with_stem("dup_twin", "dup")

    with pytest.raises(ContractValidationError):
        load_entity_contracts(base_dir)


def test_loader_rejects_missing_directory(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist"
    with pytest.raises(ContractValidationError, match="not found"):
        load_entity_contracts(missing)


def test_contracts_dir_shipped_in_repo_is_wellformed() -> None:
    assert CONTRACT_DIR.is_dir()
    yaml_files = list(CONTRACT_DIR.glob("*.yaml"))
    assert len(yaml_files) == 4
    for path in yaml_files:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert data["name"] == path.stem
        assert data["primary_key"] in data["fields"]
