"""Unit tests for the DV2 PostgreSQL ingestion repoint (no Docker).

The raw vault moved off ClickHouse onto PostgreSQL; these tests pin that the X5
loader and the supplier reference can actually *feed* that PostgreSQL vault
without a live database:

* ``build_insert_sql`` renders an idempotent, sqlglot-valid INSERT;
* every column the loaders insert exists in the committed PostgreSQL DDL (the
  guard that catches a model/DDL or generic-vs-entity-name drift);
* ``PostgresVaultWriter`` streams rows through a fake DB-API connection in the
  right column order and batches, with hash keys preserved as ``bytes``;
* the X5 loader selects the right sink per ``--target``.

A live apply + ``bv_order_canonical`` query against real data is a separate
single-node Mac smoke (see dv2/postgres/README.md), mirroring the Flink and
ClickHouse smokes.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import click
import pytest
import sqlglot
from click.testing import CliRunner
from sqlglot import exp

import warehouse.agentflow.dv2.loaders.pg_vault_writer as pgw
from warehouse.agentflow.dv2.loaders import pg_vault_writer
from warehouse.agentflow.dv2.loaders.pg_vault_writer import PostgresVaultWriter, build_insert_sql
from warehouse.agentflow.dv2.loaders.x5_retail_hero import loader
from warehouse.agentflow.dv2.loaders.x5_retail_hero import schemas as x5
from warehouse.agentflow.dv2.reference import load_postgres
from warehouse.agentflow.dv2.reference.generator import build_reference
from warehouse.agentflow.dv2.reference.vault_mapping import VAULT_DB_COLUMNS, map_reference

PG_DIR = Path(pgw.__file__).resolve().parent.parent / "postgres"


# --- DDL helpers -------------------------------------------------------------


def _ddl_columns(sql_text: str, table_name: str) -> set[str]:
    """Column names of one ``CREATE TABLE`` parsed from a PostgreSQL DDL file."""
    for stmt in sqlglot.parse(sql_text, dialect="postgres"):
        if not isinstance(stmt, exp.Create) or stmt.kind != "TABLE":
            continue
        table = stmt.find(exp.Table)
        if table is not None and table.name == table_name:
            return {col.name for col in stmt.find_all(exp.ColumnDef)}
    raise AssertionError(f"CREATE TABLE {table_name} not found")


def _columns_for(table: str, ddl_file: str) -> set[str]:
    return _ddl_columns((PG_DIR / ddl_file).read_text(encoding="utf-8"), table)


# --- fake DB-API surface -----------------------------------------------------


class _FakeCursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[tuple]]] = []
        self.closed = False

    def executemany(self, sql: str, params) -> None:
        self.calls.append((sql, list(params)))

    def close(self) -> None:
        self.closed = True


class _FakeConnection:
    def __init__(self) -> None:
        self.cur = _FakeCursor()
        self.committed = False
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return self.cur

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:
        self.closed = True


# --- build_insert_sql --------------------------------------------------------


def test_build_insert_sql_shape_and_parses():
    sql = build_insert_sql(
        "hub_customer", ["customer_hk", "customer_bk", "load_ts", "record_source"]
    )
    assert sql == (
        "INSERT INTO rv.hub_customer (customer_hk, customer_bk, load_ts, record_source) "
        "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING"
    )
    # sqlglot validates the statement under the PostgreSQL dialect.
    parsed = sqlglot.parse_one(sql.replace("%s", "?"), dialect="postgres")
    assert parsed is not None


def test_build_insert_sql_is_idempotent_and_schema_qualified():
    sql = build_insert_sql("sat_order_header__1c__msk", ["order_hk", "load_ts"], schema="rv")
    assert sql.startswith("INSERT INTO rv.sat_order_header__1c__msk ")
    assert sql.endswith("ON CONFLICT DO NOTHING")


def test_build_insert_sql_rejects_no_columns():
    with pytest.raises(ValueError):
        build_insert_sql("hub_customer", [])


# --- inserted columns exist in the committed PostgreSQL DDL -------------------

# Tables the X5 loader actually emits (mappers.py), with the row model whose
# fields become the INSERT column list.
X5_TABLES = [
    ("hub_customer", "01_hubs.sql", x5.HubCustomer),
    ("hub_product", "01_hubs.sql", x5.HubProduct),
    ("hub_store", "01_hubs.sql", x5.HubStore),
    ("hub_order", "01_hubs.sql", x5.HubOrder),
    ("lnk_order_customer", "02_links.sql", x5.LinkOrderCustomer),
    ("lnk_order_product", "02_links.sql", x5.LinkOrderProduct),
    ("lnk_order_store", "02_links.sql", x5.LinkOrderStore),
    ("sat_order_header__1c__msk", "satellites/sat_order_header__1c__msk.sql", x5.SatOrderHeader),
    ("sat_order_pricing__1c__msk", "satellites/sat_order_pricing__1c__msk.sql", x5.SatOrderPricing),
]


@pytest.mark.parametrize(("table", "ddl_file", "model"), X5_TABLES)
def test_x5_insert_columns_exist_in_postgres_ddl(table, ddl_file, model):
    columns = list(model.model_fields.keys())
    ddl_columns = _columns_for(table, ddl_file)
    missing = set(columns) - ddl_columns
    assert not missing, f"{table}: model fields absent from DDL: {missing}"
    parsed = sqlglot.parse_one(
        build_insert_sql(table, columns).replace("%s", "?"), dialect="postgres"
    )
    assert parsed is not None


X5_BRANCHES = ["msk", "spb", "ekb", "dxb", "ala"]


@pytest.mark.parametrize("branch", X5_BRANCHES)
def test_x5_per_branch_order_satellites_have_postgres_ddl(branch):
    # The loader writes sat_order_header/pricing for every observed branch, so a
    # PostgreSQL table must exist for each.
    for prefix in ("sat_order_header", "sat_order_pricing"):
        path = PG_DIR / "satellites" / f"{prefix}__1c__{branch}.sql"
        assert path.exists(), f"missing PostgreSQL DDL for {prefix}__1c__{branch}"


# Reference feed: tables, model, and the destination columns the loader uses
# (generic hub/link fields are renamed via VAULT_DB_COLUMNS; satellites identity).
def _ref_insert_columns(table: str) -> list[str]:
    if table in VAULT_DB_COLUMNS:
        return VAULT_DB_COLUMNS[table]
    rows = map_reference(
        build_reference(n_suppliers=3, n_products=6, seed=1), datetime(2026, 6, 26)
    )
    return list(rows[table][0].model_dump().keys())


REF_TABLES = [
    ("hub_supplier", "01_hubs.sql"),
    ("hub_product", "01_hubs.sql"),
    ("hub_marking_code", "01_hubs.sql"),
    ("lnk_product_supplier", "02_links.sql"),
    ("lnk_product_marking", "02_links.sql"),
    ("sat_supplier_profile__ref__global", "satellites/sat_supplier_profile__ref__global.sql"),
    ("sat_product_reference__ref__global", "satellites/sat_product_reference__ref__global.sql"),
    ("sat_marking_code_gs1__ref__global", "satellites/sat_marking_code_gs1__ref__global.sql"),
    (
        "sat_lnk_product_supplier__ref__global",
        "satellites/sat_lnk_product_supplier__ref__global.sql",
    ),
]


@pytest.mark.parametrize(("table", "ddl_file"), REF_TABLES)
def test_reference_insert_columns_exist_in_postgres_ddl(table, ddl_file):
    columns = _ref_insert_columns(table)
    ddl_columns = _columns_for(table, ddl_file)
    missing = set(columns) - ddl_columns
    assert not missing, f"{table}: insert columns absent from DDL: {missing}"


def test_reference_generic_hub_link_fields_are_renamed():
    # The generic hk/bk/left_hk/right_hk must NOT reach the destination columns.
    for columns in VAULT_DB_COLUMNS.values():
        assert "hk" not in columns
        assert "bk" not in columns
        assert "left_hk" not in columns
        assert "right_hk" not in columns


# --- PostgresVaultWriter ------------------------------------------------------


def _hub_customers(n: int) -> list[x5.HubCustomer]:
    return [
        x5.HubCustomer(
            customer_hk=bytes([i]) * 16,
            customer_bk=f"c{i}",
            load_ts=datetime(2026, 5, 29, 10, 0, 0),
            record_source="1c__msk",
        )
        for i in range(n)
    ]


def test_writer_inserts_rows_in_model_field_order():
    conn = _FakeConnection()
    written = PostgresVaultWriter(conn).write("hub_customer", _hub_customers(2))

    assert written == 2
    assert len(conn.cur.calls) == 1
    sql, params = conn.cur.calls[0]
    assert sql == (
        "INSERT INTO rv.hub_customer (customer_hk, customer_bk, load_ts, record_source) "
        "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING"
    )
    # bytes hash key preserved, column order matches the SQL.
    assert params[0] == (b"\x00" * 16, "c0", datetime(2026, 5, 29, 10, 0, 0), "1c__msk")
    assert conn.cur.closed is True


def test_writer_empty_batch_is_a_noop():
    conn = _FakeConnection()
    assert PostgresVaultWriter(conn).write("hub_customer", []) == 0
    assert conn.cur.calls == []


def test_writer_batches_by_batch_size():
    conn = _FakeConnection()
    PostgresVaultWriter(conn, batch_size=1).write("hub_customer", _hub_customers(3))
    # one executemany per batch of one row.
    assert len(conn.cur.calls) == 3
    assert all(len(params) == 1 for _, params in conn.cur.calls)


def test_writer_column_override_renames_destination_columns():
    conn = _FakeConnection()
    rows = map_reference(
        build_reference(n_suppliers=2, n_products=4, seed=1), datetime(2026, 6, 26)
    )
    PostgresVaultWriter(conn).write(
        "hub_supplier", rows["hub_supplier"], VAULT_DB_COLUMNS["hub_supplier"]
    )
    sql, _ = conn.cur.calls[0]
    assert "rv.hub_supplier (supplier_hk, supplier_bk, load_ts, record_source)" in sql
    assert "(hk," not in sql


def test_writer_rejects_override_of_wrong_length():
    conn = _FakeConnection()
    with pytest.raises(ValueError):
        PostgresVaultWriter(conn).write("hub_customer", _hub_customers(1), ["only_one_column"])


def test_writer_write_mapped_applies_per_table_overrides():
    conn = _FakeConnection()
    rows = map_reference(
        build_reference(n_suppliers=3, n_products=6, seed=1), datetime(2026, 6, 26)
    )
    written = PostgresVaultWriter(conn).write_mapped(rows, columns_by_table=VAULT_DB_COLUMNS)

    assert set(written) == set(rows)
    assert written["hub_supplier"] == 3
    statements = " ".join(sql for sql, _ in conn.cur.calls)
    assert "rv.hub_supplier (supplier_hk, supplier_bk" in statements
    assert "rv.lnk_product_supplier (link_hk, product_hk, supplier_hk" in statements


# --- connect guard -----------------------------------------------------------


def test_connect_raises_when_psycopg_missing(monkeypatch):
    monkeypatch.setattr(pg_vault_writer, "psycopg", None)
    with pytest.raises(RuntimeError, match="psycopg is required"):
        pg_vault_writer.connect("postgresql://x")


# --- loader sink selection ---------------------------------------------------


def _open(target: str, dry_run: bool, monkeypatch=None):
    return loader._open_sink(
        target=target,
        dry_run=dry_run,
        clickhouse_host="h",
        clickhouse_port=9000,
        clickhouse_database="rv",
        clickhouse_user="u",
        clickhouse_password="",
        postgres_dsn="postgresql://agentflow@localhost:5432/agentflow",
        max_active_parts=5,
    )


def test_open_sink_dry_run_never_connects():
    sink, throttle = _open("postgres", dry_run=True)
    assert isinstance(sink, loader._DryRunSink)
    assert sink.mode == "mapped"
    assert throttle.client is None


def test_open_sink_postgres(monkeypatch):
    conn = _FakeConnection()
    monkeypatch.setattr(loader, "connect_postgres", lambda dsn: conn)
    sink, throttle = _open("postgres", dry_run=False)
    assert isinstance(sink, loader._PostgresSink)
    # ClickHouse part-count backpressure is inert on PostgreSQL.
    assert throttle.client is None


def test_open_sink_clickhouse(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(loader, "_connect", lambda *args: sentinel)
    sink, throttle = _open("clickhouse", dry_run=False)
    assert isinstance(sink, loader._ClickHouseSink)
    assert throttle.client is sentinel


def test_open_sink_unknown_target_raises():
    with pytest.raises(click.ClickException):
        _open("redis", dry_run=False)


# --- reference load_postgres CLI ---------------------------------------------


def test_reference_load_dry_run_does_not_connect(monkeypatch):
    def _boom(dsn):  # pragma: no cover - must not be called on dry-run
        raise AssertionError("dry-run must not connect")

    monkeypatch.setattr(load_postgres, "connect", _boom)
    result = CliRunner().invoke(
        load_postgres.main, ["--dry-run", "--n-suppliers", "3", "--n-products", "6"]
    )
    assert result.exit_code == 0, result.output
    assert "9 tables" in result.output
    assert "dry-run: not connecting" in result.output


def test_reference_load_writes_all_tables(monkeypatch):
    conn = _FakeConnection()
    monkeypatch.setattr(load_postgres, "connect", lambda dsn: conn)
    result = CliRunner().invoke(load_postgres.main, ["--n-suppliers", "3", "--n-products", "6"])
    assert result.exit_code == 0, result.output
    assert conn.committed is True
    assert conn.closed is True
    statements = " ".join(sql for sql, _ in conn.cur.calls)
    # the renamed hub and an identity satellite both landed.
    assert "rv.hub_supplier (supplier_hk, supplier_bk" in statements
    assert "rv.sat_product_reference__ref__global" in statements


# --- PostgreSQL-native OLTP -> vault promotion -------------------------------

OLTP_DIR = PG_DIR.parent / "postgres_oltp"
PROMOTION = OLTP_DIR / "promote_to_raw_vault_pg.sql"

# ClickHouse tells that must not survive the PostgreSQL-native promotion.
_CH_PROMOTION_TOKENS = ("now64", "oltp_live", "fixedstring", "materializedpostgresql", "engine =")


def _ddl_file_for(table: str) -> str:
    if table.startswith("hub_"):
        return "01_hubs.sql"
    if table.startswith("lnk_"):
        return "02_links.sql"
    return f"satellites/{table}.sql"


def _promotion_inserts() -> list[tuple[str, list[str]]]:
    inserts: list[tuple[str, list[str]]] = []
    for stmt in sqlglot.parse(PROMOTION.read_text(encoding="utf-8"), dialect="postgres"):
        if isinstance(stmt, exp.Insert):
            table = stmt.this.find(exp.Table)
            columns = [c.name for c in stmt.this.expressions]
            assert table is not None
            inserts.append((table.name, columns))
    return inserts


def test_promotion_parses_under_postgres():
    stmts = sqlglot.parse(PROMOTION.read_text(encoding="utf-8"), dialect="postgres")
    # 10 INSERTs (5 per branch) wrapped in BEGIN/COMMIT.
    assert sum(isinstance(s, exp.Insert) for s in stmts) == 10


def _promotion_sql_without_comments() -> str:
    # The header comment documents the ClickHouse originals on purpose, so the
    # "no CH constructs" / idempotency checks run on comment-stripped SQL.
    return re.sub(r"--[^\n]*", "", PROMOTION.read_text(encoding="utf-8"))


def test_promotion_has_no_clickhouse_constructs():
    body = _promotion_sql_without_comments().lower()
    for token in _CH_PROMOTION_TOKENS:
        assert token not in body, f"promotion still contains ClickHouse token {token!r}"


def test_promotion_reads_oltp_schemas_directly_not_a_bridge():
    body = _promotion_sql_without_comments()
    assert "ops_msk." in body
    assert "ops_dxb." in body
    # bridge is gone: the vault and OLTP share one PostgreSQL engine.
    assert "oltp_live" not in body


def test_promotion_hash_keys_are_bytea_md5():
    body = PROMOTION.read_text(encoding="utf-8")
    # decode(md5(...), 'hex') yields the 16-byte BYTEA that joins with the vault.
    assert "decode(md5(" in body
    assert "pg_ops__msk" in body
    assert "pg_ops__dxb" in body
    # one transaction so localtimestamp is a single stable load_ts.
    assert "BEGIN;" in body
    assert "COMMIT;" in body


@pytest.mark.parametrize(("table", "columns"), _promotion_inserts())
def test_promotion_targets_existing_postgres_columns(table, columns):
    ddl_columns = _columns_for(table, _ddl_file_for(table))
    missing = set(columns) - ddl_columns
    assert not missing, f"{table}: promotion columns absent from DDL: {missing}"


def test_promotion_is_idempotent_per_table_kind():
    body = _promotion_sql_without_comments().lower()
    # hubs/links are idempotent on their primary key; satellites are SCD2:
    # a new version lands only when hash_diff differs from the latest version.
    assert body.count("on conflict do nothing") == 6  # 2 hub_customer + 2 hub_order + 2 lnk
    assert body.count("where not exists") == 4  # 2 personal + 2 header satellites
    # the SCD2 gate compares against the current (latest load_ts) version — one
    # max(load_ts) subquery per satellite, else a re-run on changed data is lost.
    assert body.count("select max(e2.load_ts)") == 4


def test_promotion_satellites_capture_scd2_change_not_a_constant_tag():
    """Regression guard for audit_28_06_26.md #9.

    The promotion used a constant per-entity hash_diff (``md5(id || '|tag|v1')``),
    so the ``NOT EXISTS (… AND hash_diff = …)`` gate matched the unchanged row and
    silently dropped every UPDATE (e.g. order pending -> shipped). hash_diff must
    instead be derived from the descriptive columns so a changed row produces a
    new satellite version.
    """
    body = _promotion_sql_without_comments()
    # the old constant tags must be gone entirely
    assert "|pg-hdr|v1" not in body
    assert "|pg-oltp|v1" not in body
    # order-header hash_diff covers status + amount + date + channel (each appears
    # twice per satellite: in the inserted column and in the NOT EXISTS gate; ×2 branches)
    order_hd = "concat_ws('|', o.order_date::timestamp(3)::text, o.channel, o.order_status, o.total_amount::text)"
    assert body.count(order_hd) == 4
    # customer-personal hash_diff covers name + contact
    customer_hd = (
        "concat_ws('|', c.first_name, c.last_name, coalesce(c.email, ''), coalesce(c.phone, ''))"
    )
    assert body.count(customer_hd) == 4
