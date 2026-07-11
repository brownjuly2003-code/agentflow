"""Provisioning is a writer privilege, not a boot side effect (audit P0-2).

``QueryEngine.__init__`` used to run the serving DDL and seed demo rows on both
the embedded store *and* whatever external backend was configured — on every
boot, whatever ``AGENTFLOW_DEMO_MODE`` said, because the seed had already
happened by the time the flag was read. Three consequences, pinned here:

* the serving identity had to hold CREATE/ALTER/INSERT on the production store;
* several booting replicas could see the same empty table and all seed it;
* an empty production ClickHouse got demo orders because it was empty.
"""

from __future__ import annotations

import duckdb
import pytest

from src.serving import provision
from src.serving.backends.clickhouse_backend import ClickHouseBackend
from src.serving.duckdb_connection import connect_duckdb
from src.serving.semantic_layer.catalog import DataCatalog
from src.serving.semantic_layer.query.engine import QueryEngine


def _order_count(conn: duckdb.DuckDBPyConnection) -> int:
    row = conn.execute("SELECT COUNT(*) FROM orders_v2").fetchone()
    return int(row[0]) if row else 0


def test_the_shipped_default_boots_an_empty_store(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The shipped default — no AGENTFLOW_SEED_ON_BOOT — creates the tables and
    # writes nothing into them. (The suite's conftest turns seeding on, because
    # most fixtures assert on the canonical demo entities; this test pins what a
    # deployment actually gets.)
    monkeypatch.delenv("AGENTFLOW_SEED_ON_BOOT", raising=False)
    db_file = tmp_path / "serving.duckdb"

    engine = QueryEngine(catalog=DataCatalog(), db_path=str(db_file))
    try:
        assert _order_count(engine._conn) == 0
    finally:
        engine.close()


def test_seed_on_boot_flag_is_what_puts_demo_rows_in(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTFLOW_SEED_ON_BOOT", "true")
    db_file = tmp_path / "serving.duckdb"

    engine = QueryEngine(catalog=DataCatalog(), db_path=str(db_file))
    try:
        assert _order_count(engine._conn) > 0
    finally:
        engine.close()


def test_boot_sends_nothing_at_all_to_an_external_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The regression that matters. With SERVING_BACKEND=clickhouse, booting the
    # engine must not send a single statement — no DDL, no seed, no probe — even
    # with seeding switched on, which only ever concerns the embedded store.
    # Every ClickHouse statement goes through _request, so recording it there is
    # exhaustive.
    statements: list[str] = []

    def _record(self, statement, *args, **kwargs):  # noqa: ANN001, ANN202
        statements.append(str(statement))
        raise AssertionError("the API process must not write to ClickHouse on boot")

    monkeypatch.setenv("SERVING_BACKEND", "clickhouse")
    monkeypatch.setenv("AGENTFLOW_SEED_ON_BOOT", "true")
    monkeypatch.setattr(ClickHouseBackend, "_request", _record)

    engine = QueryEngine(catalog=DataCatalog(), db_path=":memory:")
    try:
        assert engine._backend_name == "clickhouse"
        assert statements == []
    finally:
        engine.close()


def test_seeding_twice_does_not_duplicate_rows(tmp_path) -> None:
    # Stands in for two replicas booting against the same empty store: the seed
    # is guarded by the store's own contents, so the second one is a no-op.
    db_file = tmp_path / "serving.duckdb"

    engine = QueryEngine(catalog=DataCatalog(), db_path=str(db_file), seed_demo_data=True)
    try:
        first = _order_count(engine._conn)
        engine._duckdb_backend.seed_demo_data()
        engine._duckdb_backend.seed_demo_data()
        assert _order_count(engine._conn) == first
    finally:
        engine.close()


class TestProvisionCli:
    def test_schema_and_seed_provision_a_durable_store(
        self,
        tmp_path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_file = tmp_path / "serving.duckdb"
        monkeypatch.setenv("SERVING_BACKEND", "duckdb")
        monkeypatch.setenv("DUCKDB_PATH", str(db_file))

        assert provision.main(["--schema", "--seed"]) == 0

        conn = connect_duckdb(str(db_file))
        try:
            assert _order_count(conn) > 0
        finally:
            conn.close()

    def test_schema_alone_leaves_the_store_empty(
        self,
        tmp_path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_file = tmp_path / "serving.duckdb"
        monkeypatch.setenv("SERVING_BACKEND", "duckdb")
        monkeypatch.setenv("DUCKDB_PATH", str(db_file))

        assert provision.main(["--schema"]) == 0

        conn = connect_duckdb(str(db_file))
        try:
            assert _order_count(conn) == 0
        finally:
            conn.close()

    def test_in_memory_target_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SERVING_BACKEND", "duckdb")
        monkeypatch.setenv("DUCKDB_PATH", ":memory:")

        assert provision.main(["--schema"]) == 2

    def test_no_operation_requested_is_an_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SERVING_BACKEND", "duckdb")

        with pytest.raises(SystemExit):
            provision.main([])
