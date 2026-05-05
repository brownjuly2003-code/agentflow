from pathlib import Path

import pytest

from src.serving.db_pool import DuckDBPool
from src.serving.duckdb_connection import connect_duckdb


def _attached_db_encryption_state(conn) -> tuple[bool, str | None]:
    row = conn.execute(
        """
        SELECT encrypted, cipher
        FROM duckdb_databases()
        WHERE database_name = 'agentflow_db'
        """
    ).fetchone()
    if row is None:
        return False, None
    return bool(row[0]), row[1]


def test_connect_duckdb_defaults_to_plain_file_connection(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("AGENTFLOW_DUCKDB_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("AGENTFLOW_DUCKDB_ENCRYPTION_KEY_FILE", raising=False)

    db_path = tmp_path / "plain.duckdb"
    conn = connect_duckdb(db_path)
    try:
        conn.execute("CREATE TABLE items (id INTEGER)")
        conn.execute("INSERT INTO items VALUES (1)")
        assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1
        assert _attached_db_encryption_state(conn) == (False, None)
    finally:
        conn.close()


def test_connect_duckdb_uses_encrypted_attach_when_key_is_configured(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setenv("AGENTFLOW_DUCKDB_ENCRYPTION_KEY", "local-test-encryption-key")
    monkeypatch.delenv("AGENTFLOW_DUCKDB_ENCRYPTION_KEY_FILE", raising=False)

    db_path = tmp_path / "encrypted.duckdb"
    conn = connect_duckdb(db_path)
    try:
        encrypted, cipher = _attached_db_encryption_state(conn)
        assert encrypted is True
        assert cipher in {"GCM", "CTR", "CBC"}
        conn.execute("CREATE TABLE items (id INTEGER)")
        conn.execute("INSERT INTO items VALUES (1)")
    finally:
        conn.close()

    reopened = connect_duckdb(db_path)
    try:
        assert reopened.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1
    finally:
        reopened.close()


def test_duckdb_pool_uses_encrypted_connection_only_when_configured(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setenv("AGENTFLOW_DUCKDB_ENCRYPTION_KEY", "local-test-encryption-key")
    db_path = tmp_path / "pooled.duckdb"
    pool = DuckDBPool(str(db_path), pool_size=1)

    pool.initialize()
    try:
        encrypted, _ = _attached_db_encryption_state(pool.write_connection)
        assert encrypted is True
    finally:
        pool.close()


def test_connect_duckdb_rejects_empty_encryption_key_file(monkeypatch, tmp_path: Path):
    key_file = tmp_path / "empty.key"
    key_file.write_text("\n", encoding="utf-8")
    monkeypatch.delenv("AGENTFLOW_DUCKDB_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("AGENTFLOW_DUCKDB_ENCRYPTION_KEY_FILE", str(key_file))

    with pytest.raises(ValueError, match="empty"):
        connect_duckdb(tmp_path / "encrypted.duckdb")
