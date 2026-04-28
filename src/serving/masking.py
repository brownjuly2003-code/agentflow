from __future__ import annotations

import hashlib
from pathlib import Path

import sqlglot
from sqlglot import exp

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    yaml = None


class PiiMasker:
    def __init__(self, config_path: str | Path = "config/pii_fields.yaml"):
        if yaml is None:  # pragma: no cover
            raise RuntimeError("PyYAML is required for PII masking.")
        self.config_path = Path(config_path)
        self._config = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}

    def mask(self, entity_type: str, data: dict, tenant: str) -> dict:
        masking = self._config.get("masking", {})
        if tenant in masking.get("pii_exempt_tenants", []):
            return dict(data)
        rules = masking.get("entity_fields", {}).get(entity_type, [])
        default_strategy = masking.get("default_strategy", "partial")
        masked = dict(data)
        for rule in rules:
            field = rule.get("field")
            if field in masked:
                masked[field] = self._apply_strategy(
                    masked[field],
                    rule.get("strategy", default_strategy),
                )
        return masked

    def mask_query_results(
        self,
        sql: str,
        rows: list[dict],
        tenant: str,
        table_to_entity: dict[str, str],
    ) -> tuple[list[dict], bool]:
        tables = self._extract_table_names(sql)
        entity_types = {
            table_to_entity[table_name] for table_name in tables if table_name in table_to_entity
        }
        if len(entity_types) != 1:
            return [dict(row) for row in rows], False
        entity_type = next(iter(entity_types))
        masked_rows = [self.mask(entity_type, row, tenant) for row in rows]
        return masked_rows, masked_rows != rows

    def _extract_table_names(self, sql: str) -> set[str]:
        try:
            parsed = sqlglot.parse_one(sql, read="duckdb")
        except sqlglot.errors.ParseError:
            return set()
        return {table.name for table in parsed.find_all(exp.Table) if table.name}

    def _apply_strategy(self, value: object, strategy: str) -> object:
        if value is None:
            return None
        if strategy == "full":
            return "***"
        if strategy == "hash":
            return hashlib.sha256(str(value).encode()).hexdigest()[:12]
        if strategy == "partial":
            return self._partial_mask(str(value))
        return value

    def _partial_mask(self, value: str) -> str:
        if not value:
            return value
        if "@" in value and value.count("@") == 1:
            return self._mask_email(value)
        if self._looks_like_phone(value):
            return self._mask_phone(value)
        if self._looks_like_address(value):
            return self._mask_address(value)
        if " " in value.strip():
            return " ".join(self._mask_word(part) for part in value.split())
        return self._mask_word(value)

    def _mask_email(self, value: str) -> str:
        local, domain = value.split("@", 1)
        if not local:
            return f"***@{domain}"
        return f"{local[0]}***@{domain}"

    def _mask_phone(self, value: str) -> str:
        digits = "".join(char for char in value if char.isdigit())
        last4 = digits[-4:]
        return f"***-***-{last4}" if last4 else "***"

    def _mask_address(self, value: str) -> str:
        parts = [part.strip() for part in value.split(",") if part.strip()]
        if not parts:
            return "***"
        street_tokens = parts[0].split()
        if street_tokens and any(char.isdigit() for char in street_tokens[0]):
            masked_street = f"{street_tokens[0]} ***"
            if len(street_tokens) > 1:
                masked_street = f"{masked_street} {street_tokens[-1]}"
        else:
            masked_street = " ".join(self._mask_word(token) for token in street_tokens)
        if len(parts) == 1:
            return masked_street
        return ", ".join([masked_street, *["***"] * (len(parts) - 1)])

    def _looks_like_phone(self, value: str) -> bool:
        digits = sum(char.isdigit() for char in value)
        return digits >= 7 and all(char.isdigit() or char in "+-() ." for char in value)

    def _looks_like_address(self, value: str) -> bool:
        return any(char.isdigit() for char in value) and any(char.isalpha() for char in value)

    def _mask_word(self, value: str) -> str:
        if not value:
            return value
        return f"{value[0]}***"
