"""The usage database is opened once per process, and a failed usage write
never fails the request that triggered it.

Both properties fix one production defect. Every authenticated request writes
an ``api_usage`` row from a worker thread, and the analytics/admin routers
build a throwaway ``EmbeddedControlPlaneStore`` per request. When each of
those opened its own ``duckdb.connect(path)``, the last close destroyed the
DuckDB instance while another thread was opening it, and DuckDB refused the
second attach with ``BinderException: Unique file handle conflict``. The
exception escaped ``AuthMiddleware`` and turned successful requests into 500s
(2026-07-09 Load Test: 19 of 1712 requests, all six endpoints).

The race itself only reproduces under the CI runner's scheduling, so these
tests pin the two invariants that remove it rather than the timing:

1. N stores over N threads share ONE DuckDB connection per path — the
   instance is never destroyed, so there is no window to race.
2. If the store raises anyway, the request is still served.
"""

from __future__ import annotations

import threading
from pathlib import Path

import duckdb
import pytest

from src.serving.control_plane import embedded
from src.serving.control_plane.embedded import (
    EmbeddedControlPlaneStore,
    close_usage_connections,
)


@pytest.fixture(autouse=True)
def _isolate_usage_connections():
    close_usage_connections()
    yield
    close_usage_connections()


def _store(path: Path) -> EmbeddedControlPlaneStore:
    """A fresh store per call — analytics.py and admin_ui.py do exactly this."""
    return EmbeddedControlPlaneStore(usage_db_path_provider=lambda: path)


def test_concurrent_usage_writes_open_the_database_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "agentflow-api-usage.duckdb"
    _store(db_path).ensure_usage_schema()

    connects: list[str] = []
    real_connect = embedded.connect_duckdb

    def counting_connect(path, **kwargs):
        connects.append(str(path))
        return real_connect(path, **kwargs)

    monkeypatch.setattr(embedded, "connect_duckdb", counting_connect)
    close_usage_connections()  # drop the connection ensure_usage_schema opened

    errors: list[BaseException] = []
    barrier = threading.Barrier(8)

    def writer(worker: int) -> None:
        for _ in range(10):
            barrier.wait()
            try:
                _store(db_path).record_api_usage(
                    tenant="acme",
                    key_name=f"key-{worker}",
                    endpoint="/v1/metrics/order_count",
                    key_id=f"id-{worker}",
                    key_slot="current",
                )
            except BaseException as exc:  # noqa: BLE001 - the assertion is "none"
                errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    # 80 writes across 8 stores and 8 threads, one physical connection.
    assert len(connects) == 1, f"reopened the usage db {len(connects)} times"

    rows = _store(db_path).get_usage_by_tenant()
    assert rows == [{"tenant": "acme", "requests_last_24h": 80}]


def test_cursor_close_leaves_the_shared_connection_usable(tmp_path: Path) -> None:
    """Callers still ``close()`` what ``_usage_cursor`` hands them; that closes
    the cursor, not the connection every other caller is holding."""
    db_path = tmp_path / "agentflow-api-usage.duckdb"
    store = _store(db_path)
    store.ensure_usage_schema()

    first = store._usage_cursor()
    first.close()

    second = store._usage_cursor()
    try:
        assert second.execute("SELECT count(*) FROM api_usage").fetchone() == (0,)
    finally:
        second.close()


def test_dropping_a_poisoned_connection_reopens_it(tmp_path: Path) -> None:
    db_path = tmp_path / "agentflow-api-usage.duckdb"
    store = _store(db_path)
    store.ensure_usage_schema()

    embedded._USAGE_CONNECTIONS[str(db_path)].close()  # simulate a dead handle
    with pytest.raises(duckdb.Error):
        store._usage_cursor()

    # _usage_cursor evicted the dead entry, so the next caller gets a live one.
    cursor = store._usage_cursor()
    try:
        assert cursor.execute("SELECT count(*) FROM api_usage").fetchone() == (0,)
    finally:
        cursor.close()
