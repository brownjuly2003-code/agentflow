"""ClickHouse -> PostgreSQL type mapping for the DV2 raw-vault migration.

The raw vault moves off ClickHouse onto PostgreSQL: a Data Vault is
reconstruction-heavy (argMax-collapse over UNION ALL of satellites + multi-way
LEFT JOINs), and joins are PostgreSQL's strength and ClickHouse's weak spot.
ClickHouse is retained only as an optional flat-mart serving backend.

This module is the single source of truth for translating the ClickHouse column
types carried in ``spec.yaml`` into PostgreSQL types, so the same spec renders
both dialects (see ``generate_satellites.py --dialect postgres``).
"""

from __future__ import annotations

import re

_DECIMAL_RE = re.compile(r"^Decimal\((\d+),\s*(\d+)\)$")
_FIXEDSTRING_RE = re.compile(r"^FixedString\((\d+)\)$")
_DATETIME64_RE = re.compile(r"^DateTime64\((\d+)\)$")
_LOWCARD_RE = re.compile(r"^LowCardinality\((.+)\)$")
_NULLABLE_RE = re.compile(r"^Nullable\((.+)\)$")

# Scalar ClickHouse -> PostgreSQL. Unsigned ints widen one PG step so the full
# CH range fits (UInt16 max 65535 > PG smallint; UInt32 > PG integer).
_SCALAR: dict[str, str] = {
    "String": "TEXT",
    "Date": "DATE",
    "DateTime": "TIMESTAMP",
    "Bool": "BOOLEAN",
    "UInt8": "SMALLINT",
    "UInt16": "INTEGER",
    "UInt32": "BIGINT",
    "UInt64": "NUMERIC(20, 0)",
    "Int8": "SMALLINT",
    "Int16": "SMALLINT",
    "Int32": "INTEGER",
    "Int64": "BIGINT",
    "Float32": "REAL",
    "Float64": "DOUBLE PRECISION",
}


def _unwrap(ch_type: str) -> str:
    """Strip CH ``LowCardinality(...)`` / ``Nullable(...)`` wrappers.

    Both are no-ops in PostgreSQL: LowCardinality is a CH storage hint, and PG
    columns are nullable by default (the satellite template marks only the
    required meta columns NOT NULL).
    """
    changed = True
    while changed:
        changed = False
        for pattern in (_LOWCARD_RE, _NULLABLE_RE):
            match = pattern.match(ch_type)
            if match:
                ch_type = match.group(1).strip()
                changed = True
    return ch_type


def _map_default(raw: str) -> str:
    lowered = raw.strip().lower()
    if lowered == "true":
        return "TRUE"
    if lowered == "false":
        return "FALSE"
    return raw.strip()


def clickhouse_to_postgres_type(ch_type: str) -> str:
    """Translate a single ClickHouse column type to PostgreSQL.

    Handles a trailing ``DEFAULT <value>`` clause (e.g. ``Bool DEFAULT true``).
    Raises ``ValueError`` on an unmapped type so a new spec type fails loudly
    rather than emitting silently-wrong DDL.
    """
    ch_type = ch_type.strip()
    default = ""
    if " DEFAULT " in ch_type:
        ch_type, _, raw_default = ch_type.partition(" DEFAULT ")
        default = f" DEFAULT {_map_default(raw_default)}"

    base = _unwrap(ch_type.strip())

    if base in _SCALAR:
        return _SCALAR[base] + default
    if match := _DECIMAL_RE.match(base):
        return f"NUMERIC({match.group(1)}, {match.group(2)})" + default
    if match := _FIXEDSTRING_RE.match(base):
        width = int(match.group(1))
        # 16-byte fixed strings are MD5 hashes (binary); narrower ones are codes.
        return ("BYTEA" if width == 16 else f"CHAR({width})") + default
    if match := _DATETIME64_RE.match(base):
        return f"TIMESTAMP({match.group(1)})" + default

    raise ValueError(f"unmapped ClickHouse type: {ch_type!r}")
