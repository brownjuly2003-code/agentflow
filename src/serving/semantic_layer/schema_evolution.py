from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

BREAKING_CHANGES = [
    "field_removed",
    "field_type_changed",
    "field_required_added",
    "enum_value_removed",
]

SAFE_CHANGES = [
    "field_added_optional",
    "description_changed",
    "enum_value_added",
    "field_default_added",
]


def _normalize_version(version: Any) -> str:
    normalized = str(version)
    return normalized[1:] if normalized.startswith("v") else normalized


def _version_sort_key(version: str) -> tuple[int, int | str]:
    normalized = _normalize_version(version)
    return (0, int(normalized)) if normalized.isdigit() else (1, normalized)


def load_schema(path: str | Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if "version" in payload:
        payload["version"] = _normalize_version(payload["version"])
    return payload


def has_version_bump(old_schema: dict[str, Any], new_schema: dict[str, Any]) -> bool:
    old_version = old_schema.get("version")
    new_version = new_schema.get("version")
    if old_version is None or new_version is None:
        return False
    return _version_sort_key(str(new_version)) > _version_sort_key(str(old_version))


@dataclass(frozen=True)
class EvolutionReport:
    breaking_changes: list[dict[str, Any]]
    safe_changes: list[dict[str, Any]]

    @property
    def is_breaking(self) -> bool:
        return bool(self.breaking_changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "breaking_changes": self.breaking_changes,
            "safe_changes": self.safe_changes,
            "is_breaking": self.is_breaking,
        }


class EvolutionChecker:
    def check(
        self,
        old_schema: dict[str, Any],
        new_schema: dict[str, Any],
    ) -> EvolutionReport:
        old_fields = self._field_map(old_schema)
        new_fields = self._field_map(new_schema)
        breaking_changes: list[dict[str, Any]] = []
        safe_changes: list[dict[str, Any]] = []

        for field_name in sorted(old_fields.keys() - new_fields.keys()):
            breaking_changes.append(
                {
                    "type": "field_removed",
                    "field": field_name,
                    "severity": "breaking",
                }
            )

        for field_name in sorted(new_fields.keys() - old_fields.keys()):
            target = breaking_changes if new_fields[field_name].get("required") else safe_changes
            target.append(
                {
                    "type": (
                        "field_required_added"
                        if new_fields[field_name].get("required")
                        else "field_added_optional"
                    ),
                    "field": field_name,
                    "severity": "breaking" if new_fields[field_name].get("required") else "safe",
                }
            )

        for field_name in sorted(old_fields.keys() & new_fields.keys()):
            old_field = old_fields[field_name]
            new_field = new_fields[field_name]

            if old_field.get("type") != new_field.get("type"):
                breaking_changes.append(
                    {
                        "type": "field_type_changed",
                        "field": field_name,
                        "severity": "breaking",
                        "from": old_field.get("type"),
                        "to": new_field.get("type"),
                    }
                )

            if not old_field.get("required", False) and new_field.get("required", False):
                breaking_changes.append(
                    {
                        "type": "field_required_added",
                        "field": field_name,
                        "severity": "breaking",
                    }
                )

            removed_values = sorted(
                set(old_field.get("values") or ()) - set(new_field.get("values") or ())
            )
            if removed_values:
                breaking_changes.append(
                    {
                        "type": "enum_value_removed",
                        "field": field_name,
                        "severity": "breaking",
                        "values": removed_values,
                    }
                )

            added_values = sorted(
                set(new_field.get("values") or ()) - set(old_field.get("values") or ())
            )
            if added_values:
                safe_changes.append(
                    {
                        "type": "enum_value_added",
                        "field": field_name,
                        "severity": "safe",
                        "values": added_values,
                    }
                )

            if old_field.get("description") != new_field.get("description"):
                safe_changes.append(
                    {
                        "type": "description_changed",
                        "field": field_name,
                        "severity": "safe",
                    }
                )

            if "default" not in old_field and "default" in new_field:
                safe_changes.append(
                    {
                        "type": "field_default_added",
                        "field": field_name,
                        "severity": "safe",
                        "default": new_field["default"],
                    }
                )

        return EvolutionReport(
            breaking_changes=breaking_changes,
            safe_changes=safe_changes,
        )

    def _field_map(self, schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {field["name"]: field for field in schema.get("fields", []) if "name" in field}
