"""DuckDB connection pool with concurrent reads and serialized writes."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from queue import Queue

import duckdb

from src.serving.duckdb_connection import connect_duckdb


class DuckDBPool:
    def __init__(self, db_path: str, pool_size: int = 5):
        if pool_size < 1:
            raise ValueError("pool_size must be at least 1")

        self._db_path = db_path
        self._pool_size = pool_size
        self._read_pool: Queue[duckdb.DuckDBPyConnection] = Queue(maxsize=pool_size)
        self._read_connections: list[duckdb.DuckDBPyConnection] = []
        self._write_conn: duckdb.DuckDBPyConnection | None = None
        self._write_lock = threading.Lock()
        self._stats_lock = threading.Lock()
        self._read_in_use = 0
        self._write_in_use = 0
        self._initialized = False

    @property
    def write_connection(self) -> duckdb.DuckDBPyConnection:
        if self._write_conn is None:
            raise RuntimeError("DuckDBPool is not initialized")
        return self._write_conn

    def initialize(self) -> None:
        if self._initialized:
            return

        if self._db_path != ":memory:":
            Path(self._db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)

        self._write_conn = connect_duckdb(self._db_path)
        for _ in range(self._pool_size):
            conn = self._write_conn.cursor()
            self._read_connections.append(conn)
            self._read_pool.put(conn)

        self._initialized = True

    @contextmanager
    def read_conn(self) -> Iterator[duckdb.DuckDBPyConnection]:
        if not self._initialized:
            raise RuntimeError("DuckDBPool is not initialized")

        conn = self._read_pool.get()
        with self._stats_lock:
            self._read_in_use += 1

        try:
            yield conn
        finally:
            with self._stats_lock:
                self._read_in_use -= 1
            self._read_pool.put(conn)

    @contextmanager
    def write_conn(self) -> Iterator[duckdb.DuckDBPyConnection]:
        if not self._initialized:
            raise RuntimeError("DuckDBPool is not initialized")

        with self._write_lock:
            with self._stats_lock:
                self._write_in_use += 1
            try:
                yield self.write_connection
            finally:
                with self._stats_lock:
                    self._write_in_use -= 1

    def stats(self) -> dict[str, int | float]:
        with self._stats_lock:
            read_in_use = self._read_in_use
            write_in_use = self._write_in_use

        return {
            "pool_size": self._pool_size,
            "read_in_use": read_in_use,
            "read_available": self._pool_size - read_in_use,
            "read_utilization": round(read_in_use / self._pool_size, 4),
            "write_in_use": write_in_use,
        }

    def close(self) -> None:
        if not self._initialized:
            return

        for conn in self._read_connections:
            conn.close()
        self.write_connection.close()

        self._read_connections = []
        self._read_pool = Queue(maxsize=self._pool_size)
        self._write_conn = None
        self._initialized = False
