from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    yaml = None


def _default_contracts_dir() -> Path:
    return Path(os.getenv("AGENTFLOW_CONTRACTS_DIR", "config/contracts"))


def _normalize_version(version: str) -> str:
    return version[1:] if version.startswith("v") else version


def _version_sort_key(version: str) -> tuple[int, int | str]:
    normalized = _normalize_version(version)
    return (0, int(normalized)) if normalized.isdigit() else (1, normalized)


@dataclass(frozen=True)
class ContractField:
    name: str
    type: str
    required: bool
    description: str | None = None
    values: tuple[str, ...] | None = None
    unit: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "type": self.type,
            "required": self.required,
        }
        if self.description is not None:
            payload["description"] = self.description
        if self.values is not None:
            payload["values"] = list(self.values)
        if self.unit is not None:
            payload["unit"] = self.unit
        return payload


@dataclass(frozen=True)
class ContractVersion:
    entity: str
    version: str
    released: str
    status: str

    def to_dict(self) -> dict[str, str]:
        return {
            "entity": self.entity,
            "version": self.version,
            "released": self.released,
            "status": self.status,
        }


@dataclass(frozen=True)
class SchemaContract:
    entity: str
    version: str
    released: str
    status: str
    fields: tuple[ContractField, ...]
    breaking_changes: tuple[dict[str, Any], ...]
    source_path: Path | None = None

    def field_map(self) -> dict[str, ContractField]:
        return {field.name: field for field in self.fields}

    def summary(self) -> ContractVersion:
        return ContractVersion(
            entity=self.entity,
            version=self.version,
            released=self.released,
            status=self.status,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity": self.entity,
            "version": self.version,
            "released": self.released,
            "status": self.status,
            "fields": [field.to_dict() for field in self.fields],
            "breaking_changes": [dict(change) for change in self.breaking_changes],
        }


class ContractRegistry:
    def __init__(self, contracts_dir: str | Path | None = None) -> None:
        self.contracts_dir = Path(contracts_dir) if contracts_dir else _default_contracts_dir()
        self._contracts: dict[str, dict[str, SchemaContract]] = {}
        self.load()

    def load(self) -> None:
        self._contracts = {}
        if not self.contracts_dir.exists():
            return
        for path in sorted(self.contracts_dir.glob("*.yaml")):
            contract = self._load_contract(path)
            self._contracts.setdefault(contract.entity, {})[contract.version] = contract

    def list_contracts(self) -> list[SchemaContract]:
        contracts = [
            contract
            for entity_contracts in self._contracts.values()
            for contract in entity_contracts.values()
        ]
        return sorted(
            contracts,
            key=lambda contract: (contract.entity, _version_sort_key(contract.version)),
        )

    def list_versions(self, entity: str) -> list[ContractVersion]:
        return [contract.summary() for contract in self._sorted_entity_contracts(entity)]

    def latest_contract_version(self, entity: str) -> str | None:
        latest = self.get_latest_stable(entity)
        return latest.version if latest is not None else None

    def get_latest_stable(self, entity: str) -> SchemaContract | None:
        versions = self._sorted_entity_contracts(entity)
        stable_versions = [contract for contract in versions if contract.status == "stable"]
        if stable_versions:
            return stable_versions[-1]
        return versions[-1] if versions else None

    def get_contract(self, entity: str, version: str) -> SchemaContract:
        normalized_version = _normalize_version(version)
        entity_contracts = self._contracts.get(entity, {})
        contract = entity_contracts.get(normalized_version)
        if contract is None:
            raise KeyError(f"Unknown contract version: {entity}:{normalized_version}")
        return contract

    def diff(self, entity: str, from_version: str, to_version: str) -> dict[str, Any]:
        from_contract = self.get_contract(entity, from_version)
        to_contract = self.get_contract(entity, to_version)
        from_fields = from_contract.field_map()
        to_fields = to_contract.field_map()
        breaking_changes: list[dict[str, Any]] = []
        additive_changes: list[dict[str, Any]] = []

        for field_name in sorted(from_fields.keys() - to_fields.keys()):
            breaking_changes.append(
                {
                    "type": "field_removed",
                    "field": field_name,
                    "severity": "breaking",
                }
            )

        for field_name in sorted(to_fields.keys() - from_fields.keys()):
            target = breaking_changes if to_fields[field_name].required else additive_changes
            target.append(
                {
                    "type": "field_added",
                    "field": field_name,
                    "severity": "breaking" if to_fields[field_name].required else "non_breaking",
                }
            )

        for field_name in sorted(from_fields.keys() & to_fields.keys()):
            source_field = from_fields[field_name]
            target_field = to_fields[field_name]
            if source_field.type != target_field.type:
                breaking_changes.append(
                    {
                        "type": "field_type_changed",
                        "field": field_name,
                        "severity": "breaking",
                        "from": source_field.type,
                        "to": target_field.type,
                    }
                )
            if not source_field.required and target_field.required:
                breaking_changes.append(
                    {
                        "type": "field_became_required",
                        "field": field_name,
                        "severity": "breaking",
                    }
                )
            source_values = set(source_field.values or ())
            target_values = set(target_field.values or ())
            removed_values = sorted(source_values - target_values)
            added_values = sorted(target_values - source_values)
            if removed_values:
                breaking_changes.append(
                    {
                        "type": "enum_values_removed",
                        "field": field_name,
                        "severity": "breaking",
                        "values": removed_values,
                    }
                )
            if added_values:
                additive_changes.append(
                    {
                        "type": "enum_values_added",
                        "field": field_name,
                        "severity": "non_breaking",
                        "values": added_values,
                    }
                )

        return {
            "entity": entity,
            "from_version": from_contract.version,
            "to_version": to_contract.version,
            "breaking_changes": breaking_changes,
            "additive_changes": additive_changes,
        }

    def _sorted_entity_contracts(self, entity: str) -> list[SchemaContract]:
        entity_contracts = self._contracts.get(entity, {})
        return sorted(
            entity_contracts.values(),
            key=lambda contract: _version_sort_key(contract.version),
        )

    def _load_contract(self, path: Path) -> SchemaContract:
        raw = path.read_text(encoding="utf-8")
        if yaml is not None:
            payload = yaml.safe_load(raw) or {}
        else:  # pragma: no cover
            payload = json.loads(raw)
        fields = tuple(
            ContractField(
                name=field["name"],
                type=field["type"],
                required=bool(field.get("required", False)),
                description=field.get("description"),
                values=tuple(field["values"]) if field.get("values") is not None else None,
                unit=field.get("unit"),
            )
            for field in payload.get("fields", [])
        )
        return SchemaContract(
            entity=payload["entity"],
            version=_normalize_version(str(payload["version"])),
            released=str(payload["released"]),
            status=payload["status"],
            fields=fields,
            breaking_changes=tuple(payload.get("breaking_changes", [])),
            source_path=path,
        )
