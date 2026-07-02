from __future__ import annotations

import threading
from collections.abc import Callable

import duckdb
import pytest

import src.processing.event_replayer as event_replayer_module
import src.serving.control_plane.embedded as control_plane_embedded_module
from src.db_concurrency import catalog_ddl_lock
from src.processing.event_replayer import ensure_dead_letter_table
from src.serving.control_plane import (
    ensure_alert_history_table,
    ensure_webhook_deliveries_table,
    ensure_webhook_delivery_queue_table,
)

Ensurer = Callable[[duckdb.DuckDBPyConnection], None]

# ``ensure_webhook_delivery_queue_table`` is the control-plane store's lazy
# CREATE (run on the shared serving connection from the event loop; lives in
# ``control_plane.embedded`` since ADR 0010 slice 1). It was left out of the
# #123 lock and so still raced the offloaded read-handler DDL across tables;
# include it here so both the same-table and cross-table hammers cover it.
# (audit_30 D2/A2 follow-up residual)
_ENSURERS: list[Ensurer] = [
    ensure_dead_letter_table,
    ensure_alert_history_table,
    ensure_webhook_deliveries_table,
    ensure_webhook_delivery_queue_table,
]


def _hammer(conn: duckdb.DuckDBPyConnection, jobs: list[Ensurer]) -> list[Exception]:
    """Run each ensure_* on a fresh cursor on ``conn``, all firing the DDL at once.

    A ``Barrier`` releases every thread into ``ensure_*`` simultaneously so the
    cold-catalog write-write conflict is provoked deterministically: with the
    lock removed this reliably raises on most threads; with it, every thread
    serializes to a warm no-op and the list stays empty.
    """
    errors: list[Exception] = []
    barrier = threading.Barrier(len(jobs))

    def worker(ensure: Ensurer) -> None:
        cursor = conn.cursor()
        try:
            barrier.wait()
            ensure(cursor)
        except Exception as exc:  # noqa: BLE001 - capture the catalog conflict, if any
            errors.append(exc)
        finally:
            cursor.close()

    threads = [threading.Thread(target=worker, args=(job,)) for job in jobs]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return errors


@pytest.mark.parametrize("ensure", _ENSURERS)
def test_ensure_table_concurrency_safe_same_table_cold_db(ensure: Ensurer) -> None:
    # The #120 offload calls ensure_*_table on worker threads; on a cold DuckDB
    # a concurrent burst raced on the catalog -> "Catalog write-write conflict"
    # -> HTTP 500 (the serving DB default is :memory:, cold on every restart).
    # The shared catalog DDL lock serializes creation. (audit_30 A2 follow-up)
    conn = duckdb.connect(":memory:")
    errors = _hammer(conn, [ensure] * 32)
    assert errors == [], f"{ensure.__name__}: {errors[:2]}"


def test_ensure_tables_concurrency_safe_across_tables_cold_db() -> None:
    # DuckDB raises a catalog write-write conflict even across *different* tables,
    # so every ensure_*_table helper must share one lock (not a lock per table).
    # 12 interleaved calls per table on a cold DB.
    conn = duckdb.connect(":memory:")
    errors = _hammer(conn, _ENSURERS * 12)
    assert errors == [], errors[:3]


def test_catalog_ddl_lock_is_a_single_shared_instance() -> None:
    # Every ensure_* helper (across both modules) must guard DDL with the
    # *same* lock instance, or the cross-table conflict resurfaces. Pins against a
    # future per-module lock.
    assert (
        event_replayer_module.catalog_ddl_lock
        is control_plane_embedded_module.catalog_ddl_lock
        is catalog_ddl_lock
    )
