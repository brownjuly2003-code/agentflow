from __future__ import annotations

import os
from pathlib import Path

import duckdb

ATTACHED_DB_ALIAS = "agentflow_db"
ENCRYPTION_KEY_ENV = "AGENTFLOW_DUCKDB_ENCRYPTION_KEY"
ENCRYPTION_KEY_FILE_ENV = "AGENTFLOW_DUCKDB_ENCRYPTION_KEY_FILE"
ENCRYPTION_CIPHER_ENV = "AGENTFLOW_DUCKDB_ENCRYPTION_CIPHER"
SUPPORTED_CIPHERS = {"GCM", "CTR", "CBC"}


def connect_duckdb(
    db_path: Path | str,
    *,
    read_only: bool = False,
) -> duckdb.DuckDBPyConnection:
    path = str(db_path)
    key = _configured_encryption_key()
    if key is None or path == ":memory:":
        if read_only:
            return duckdb.connect(path, read_only=True)
        return duckdb.connect(path)

    conn = duckdb.connect(":memory:")
    conn.execute("SET VARIABLE agentflow_duckdb_encryption_key = ?", [key])
    attach_options = ["ENCRYPTION_KEY getvariable('agentflow_duckdb_encryption_key')"]
    cipher = _configured_cipher()
    if cipher is not None:
        attach_options.append(f"ENCRYPTION_CIPHER '{cipher}'")
    if read_only:
        attach_options.append("READ_ONLY")
    conn.execute(
        f"ATTACH '{_sql_string(path)}' AS {ATTACHED_DB_ALIAS} ({', '.join(attach_options)})"
    )
    conn.execute(f"USE {ATTACHED_DB_ALIAS}")
    return conn


def _configured_encryption_key() -> str | None:
    key = os.getenv(ENCRYPTION_KEY_ENV)
    if key is not None:
        stripped = key.strip()
        if not stripped:
            raise ValueError(f"{ENCRYPTION_KEY_ENV} is empty")
        return stripped

    key_file = os.getenv(ENCRYPTION_KEY_FILE_ENV)
    if key_file is None:
        return None
    stripped = Path(key_file).read_text(encoding="utf-8").strip()
    if not stripped:
        raise ValueError(f"{ENCRYPTION_KEY_FILE_ENV} points to an empty key file")
    return stripped


def _configured_cipher() -> str | None:
    cipher = os.getenv(ENCRYPTION_CIPHER_ENV)
    if cipher is None or not cipher.strip():
        return None
    normalized = cipher.strip().upper()
    if normalized not in SUPPORTED_CIPHERS:
        raise ValueError(
            f"{ENCRYPTION_CIPHER_ENV} must be one of {', '.join(sorted(SUPPORTED_CIPHERS))}"
        )
    return normalized


def _sql_string(value: str) -> str:
    return value.replace("'", "''")
