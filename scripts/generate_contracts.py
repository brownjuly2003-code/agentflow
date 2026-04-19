from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, get_args, get_origin

import yaml
from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "sdk") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "sdk"))

from agentflow.models import MetricResult, OrderEntity

from src.ingestion.schemas.events import Currency, OrderStatus

CONTRACTS_DIR = REPO_ROOT / "config" / "contracts"


@dataclass(frozen=True)
class ContractSpec:
    path: str
    entity: str
    version: str
    released: str
    status: str
    model: type[BaseModel]
    include_fields: tuple[str, ...]
    field_overrides: dict[str, dict[str, Any]]


CONTRACT_SPECS = (
    ContractSpec(
        path="order.v1.yaml",
        entity="order",
        version="1",
        released="2026-04-01",
        status="deprecated",
        model=OrderEntity,
        include_fields=(
            "order_id",
            "status",
            "total_amount",
            "currency",
            "user_id",
            "created_at",
        ),
        field_overrides={
            "order_id": {
                "description": "Unique order identifier (ORD-{n} format)",
            },
            "status": {
                "type": "enum",
                "values": [status.value for status in OrderStatus],
            },
            "total_amount": {
                "unit": "USD",
            },
            "currency": {
                "type": "enum",
                "values": [currency.value for currency in Currency],
            },
        },
    ),
    ContractSpec(
        path="order.v2.yaml",
        entity="order",
        version="2",
        released="2026-04-11",
        status="stable",
        model=OrderEntity,
        include_fields=(
            "order_id",
            "status",
            "total_amount",
            "currency",
            "user_id",
            "created_at",
            "is_overdue",
        ),
        field_overrides={
            "order_id": {
                "description": "Unique order identifier (ORD-{n} format)",
            },
            "status": {
                "type": "enum",
                "values": [status.value for status in OrderStatus],
            },
            "total_amount": {
                "unit": "USD",
            },
            "currency": {
                "type": "enum",
                "values": [currency.value for currency in Currency],
            },
        },
    ),
    ContractSpec(
        path="metric.revenue.v1.yaml",
        entity="metric.revenue",
        version="1",
        released="2026-04-11",
        status="stable",
        model=MetricResult,
        include_fields=(
            "value",
            "unit",
            "window",
            "computed_at",
        ),
        field_overrides={
            "value": {
                "unit": "USD",
            },
        },
    ),
)


def _unwrap_annotation(annotation: Any) -> Any:
    origin = get_origin(annotation)
    if origin is None:
        return annotation
    if origin in (list, tuple, dict):
        return annotation
    args = tuple(arg for arg in get_args(annotation) if arg is not type(None))
    if len(args) == 1:
        return _unwrap_annotation(args[0])
    return annotation


def _contract_type(annotation: Any) -> str:
    annotation = _unwrap_annotation(annotation)
    origin = get_origin(annotation)
    if origin is list:
        return "array"
    if origin is dict:
        return "object"
    if isinstance(annotation, type):
        if issubclass(annotation, Enum):
            return "enum"
        if issubclass(annotation, bool):
            return "boolean"
        if issubclass(annotation, int):
            return "integer"
        if issubclass(annotation, float) or issubclass(annotation, Decimal):
            return "float"
        if issubclass(annotation, datetime):
            return "datetime"
        if issubclass(annotation, str):
            return "string"
    return "string"


def _field_payload(model: type[BaseModel], field_name: str, overrides: dict[str, Any]) -> dict[str, Any]:
    field_info = model.model_fields[field_name]
    payload: dict[str, Any] = {
        "name": field_name,
        "type": overrides.get("type", _contract_type(field_info.annotation)),
        "required": field_info.is_required(),
    }
    values = overrides.get("values")
    if values is not None:
        payload["values"] = values
    description = overrides.get("description")
    if description is not None:
        payload["description"] = description
    unit = overrides.get("unit")
    if unit is not None:
        payload["unit"] = unit
    return payload


def _render_contract(spec: ContractSpec) -> dict[str, Any]:
    return {
        "entity": spec.entity,
        "version": spec.version,
        "released": spec.released,
        "status": spec.status,
        "fields": [
            _field_payload(
                spec.model,
                field_name,
                spec.field_overrides.get(field_name, {}),
            )
            for field_name in spec.include_fields
        ],
        "breaking_changes": [],
    }


def _dump_yaml(payload: dict[str, Any]) -> str:
    return yaml.safe_dump(payload, sort_keys=False)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate config/contracts/*.yaml from Pydantic models.",
    )
    parser.add_argument("--check", action="store_true", help="fail if generated files drift")
    args = parser.parse_args()

    drift: list[str] = []
    CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)

    for spec in CONTRACT_SPECS:
        path = CONTRACTS_DIR / spec.path
        expected = _render_contract(spec)
        if args.check:
            if not path.exists():
                drift.append(spec.path)
                continue
            actual = yaml.safe_load(path.read_text(encoding="utf-8"))
            if actual != expected:
                drift.append(spec.path)
            continue
        path.write_text(_dump_yaml(expected), encoding="utf-8", newline="\n")

    if args.check and drift:
        print("Contracts drifted: " + ", ".join(drift), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
