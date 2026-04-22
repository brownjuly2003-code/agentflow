"""Data-driven loader for entity type definitions.

The four core entity types (`order`, `user`, `product`, `session`) were
previously registered inline inside :class:`DataCatalog`. Keeping them
as YAML under ``contracts/entities/`` lets a new entity type ship
without forking Python, and gives ops a single place to diff when a
column is added.

This module intentionally stays a thin loader: it produces the same
:class:`EntityDefinition` dataclass the rest of the serving layer
already consumes. Richer schema semantics (typed fields, enum values,
relation targets) are a follow-up; dropping those on the floor here is
deliberate so this refactor stays behaviour-preserving.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import yaml  # type: ignore[import-untyped]

if TYPE_CHECKING:  # pragma: no cover - typing only
    from src.serving.semantic_layer.catalog import EntityDefinition as EntityDefinitionT

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONTRACTS_DIR = PROJECT_ROOT / "contracts" / "entities"

_REQUIRED_KEYS = ("name", "description", "table", "primary_key", "fields")


class ContractValidationError(ValueError):
    """Raised when an entity YAML file is malformed or self-inconsistent."""


def _validate_contract(path: Path, data: dict) -> None:
    for key in _REQUIRED_KEYS:
        if key not in data:
            raise ContractValidationError(f"{path.name}: missing required key '{key}'.")
    fields = data["fields"]
    if not isinstance(fields, dict) or not fields:
        raise ContractValidationError(f"{path.name}: 'fields' must be a non-empty mapping.")
    primary_key = data["primary_key"]
    if primary_key not in fields:
        raise ContractValidationError(
            f"{path.name}: primary_key '{primary_key}' is not declared in 'fields'."
        )
    relationships = data.get("relationships") or {}
    if not isinstance(relationships, dict):
        raise ContractValidationError(f"{path.name}: 'relationships' must be a mapping.")
    stem_name = path.stem
    if data["name"] != stem_name:
        raise ContractValidationError(
            f"{path.name}: 'name' is '{data['name']}' but filename implies '{stem_name}'."
        )


def load_entity_contracts(
    contracts_dir: Path | None = None,
) -> list[EntityDefinitionT]:
    """Load every ``*.yaml`` file under ``contracts_dir`` into
    :class:`EntityDefinition` instances.

    The ``contract_version`` field is left ``None`` here. Callers that
    care (``DataCatalog``) resolve it against the schema-level
    :class:`ContractRegistry` after loading.
    """
    from src.serving.semantic_layer.catalog import EntityDefinition

    directory = contracts_dir or DEFAULT_CONTRACTS_DIR
    if not directory.is_dir():
        raise ContractValidationError(f"Entity contracts directory not found: {directory}")

    files = sorted(directory.glob("*.yaml"))
    if not files:
        raise ContractValidationError(f"No entity contracts found under {directory}")

    seen_names: set[str] = set()
    entities: list[EntityDefinition] = []
    for path in files:
        raw = path.read_text(encoding="utf-8")
        try:
            data = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            raise ContractValidationError(f"{path.name}: invalid YAML ({exc}).") from exc
        if not isinstance(data, dict):
            raise ContractValidationError(f"{path.name}: top-level document must be a mapping.")

        _validate_contract(path, data)
        name = data["name"]
        if name in seen_names:
            raise ContractValidationError(f"Duplicate entity name '{name}' in {path.name}.")
        seen_names.add(name)

        entities.append(
            EntityDefinition(
                name=name,
                description=data["description"],
                table=data["table"],
                primary_key=data["primary_key"],
                fields=dict(data["fields"]),
                relationships=dict(data.get("relationships") or {}),
                contract_version=None,
            )
        )

    return entities
