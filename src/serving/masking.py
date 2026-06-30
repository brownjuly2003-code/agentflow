from __future__ import annotations

import hashlib
from pathlib import Path

import sqlglot
from sqlglot import exp
from sqlglot.lineage import lineage

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


class _UnresolvedSources(frozenset[str]):
    """Sentinel column-source set whose membership test is always ``True``.

    Used when projection lineage can't be resolved for an output column (an
    ambiguous reference, or an exotic shape sqlglot's lineage rejects). Treating
    every masking rule field as a possible source masks the column **fail
    closed** rather than letting a renamed/derived PII value slip through as
    cleartext. (audit_30 D2 follow-up)
    """

    def __contains__(self, item: object) -> bool:
        return True


_UNRESOLVED_SOURCES: frozenset[str] = _UnresolvedSources()


class PiiMasker:
    def __init__(self, config_path: str | Path = "config/pii_fields.yaml"):
        if yaml is None:  # pragma: no cover
            raise RuntimeError("PyYAML is required for PII masking.")
        self.config_path = Path(config_path)
        self._config = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}

    def mask(
        self,
        entity_type: str,
        data: dict,
        tenant: str,
        *,
        source_columns: dict[str, frozenset[str]] | None = None,
    ) -> dict:
        masking = self._config.get("masking", {})
        if tenant in masking.get("pii_exempt_tenants", []):
            return dict(data)
        rules = masking.get("entity_fields", {}).get(entity_type, [])
        default_strategy = masking.get("default_strategy", "partial")
        masked = dict(data)
        for rule in rules:
            field = rule.get("field")
            if not field:
                continue
            strategy = rule.get("strategy", default_strategy)
            for output_col in self._output_columns_for_field(field, masked, source_columns):
                masked[output_col] = self._apply_strategy(masked[output_col], strategy)
        return masked

    def _output_columns_for_field(
        self,
        field: str,
        data: dict,
        source_columns: dict[str, frozenset[str]] | None,
    ) -> set[str]:
        """Which result columns to mask for a rule's source ``field``.

        With projection lineage (from a SELECT), mask every output column that
        *derives* from the source field — this catches a renamed/derived PII
        column such as ``email AS contact`` or ``lower(email) AS e`` that the old
        output-name match silently let through as cleartext. (audit_30_06_26.md D2)
        Without lineage (a single-entity payload, ``SELECT *``, or unparseable
        SQL) the output column keeps the source name, so match by name.
        """
        if source_columns is not None:
            return {
                output_col
                for output_col, sources in source_columns.items()
                if field in sources and output_col in data
            }
        return {field} if field in data else set()

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
        if not entity_types:
            return [dict(row) for row in rows], False
        # Resolve projection lineage so a renamed/derived PII column is masked by
        # what it's *built from*, not by its output name. (audit_30_06_26.md D2)
        source_columns = self._projection_source_columns(sql)
        # Apply every matched entity's masking rules. A multi-entity JOIN must not
        # bypass masking — returning the rows unmasked leaked cleartext PII
        # (e.g. users_enriched JOIN orders_v2). Mask the union of all matched
        # entities rather than failing open. (audit_28_06_26.md #6)
        masked_rows = [dict(row) for row in rows]
        for entity_type in entity_types:
            masked_rows = [
                self.mask(entity_type, row, tenant, source_columns=source_columns)
                for row in masked_rows
            ]
        return masked_rows, masked_rows != rows

    def _projection_source_columns(self, sql: str) -> dict[str, frozenset[str]] | None:
        """Map each output column to the source column names that feed it.

        Resolves *true* projection lineage (through subqueries, CTEs and unions)
        so a PII column renamed at any nesting depth is masked by what it is
        built from, not by its output name. The shallow one-level resolver this
        replaces saw only the outermost projection, so an inner rename —
        ``SELECT contact FROM (SELECT email AS contact FROM users_enriched)`` —
        returned cleartext. (audit_30 D2 follow-up: subquery/CTE-alias bypass)

        Returns ``None`` for a ``SELECT *`` (whose outputs are the source names
        verbatim, so name-matching is correct) or unparseable SQL, so masking
        falls back to matching rule fields against output names.
        """
        try:
            parsed = sqlglot.parse_one(sql, read="duckdb")
        except sqlglot.errors.ParseError:
            return None
        select = parsed.find(exp.Select)
        if select is None:
            return None
        if any(
            isinstance(projection, exp.Star) or projection.find(exp.Star) is not None
            for projection in select.expressions
        ):
            return None
        mapping: dict[str, frozenset[str]] = {}
        for projection in select.expressions:
            output_name = projection.alias_or_name
            if not output_name:
                continue
            # Union the *deep* lineage sources (which trace a renamed PII column
            # through subqueries/CTEs) with the *shallow* columns named directly
            # in this projection. Lineage is blind through an inner ``SELECT *``
            # (no schema to expand it), where the shallow scan still catches a
            # direct ``email AS contact``; lineage catches the inner rename the
            # shallow scan misses. Either alone leaks one shape — the union
            # closes both.
            deep = self._lineage_source_columns(output_name, sql)
            if isinstance(deep, _UnresolvedSources):
                mapping[output_name] = deep
                continue
            shallow = frozenset(col.name for col in projection.find_all(exp.Column) if col.name)
            mapping[output_name] = deep | shallow
        return mapping

    def _lineage_source_columns(self, output_name: str, sql: str) -> frozenset[str]:
        """The ultimate source column names feeding ``output_name``.

        Walks the lineage graph to its leaves (across subqueries, CTEs and union
        branches) and returns the bare column names. Fails closed — a sentinel
        that matches every rule field — when lineage can't be resolved, so an
        unresolved column is masked rather than leaked.
        """
        try:
            root = lineage(output_name, sql, dialect="duckdb")
        except Exception:  # noqa: BLE001 - any lineage failure must fail closed
            return _UNRESOLVED_SOURCES
        sources: set[str] = set()
        stack = [root]
        seen: set[int] = set()
        while stack:
            node = stack.pop()
            if id(node) in seen:
                continue
            seen.add(id(node))
            if not node.downstream and node.name:
                sources.add(node.name.split(".")[-1])
            stack.extend(node.downstream)
        return frozenset(sources)

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
