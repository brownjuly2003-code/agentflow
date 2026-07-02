"""Unit tests for the DV2 ClickHouse -> PostgreSQL raw-vault migration (no Docker).

Pins the type mapping, the spec-driven Postgres satellite generation, and that
every hand-authored and generated Postgres DDL statement parses under sqlglot's
PostgreSQL dialect with no ClickHouse constructs left behind. A live apply +
bv_order_canonical query is a separate Mac smoke (see postgres/README.md).
"""

from __future__ import annotations

import glob
import re
from pathlib import Path

import pytest
import sqlglot

import warehouse.agentflow.dv2.dialects as dialects_mod
from warehouse.agentflow.dv2.dialects import clickhouse_to_postgres_type as to_pg
from warehouse.agentflow.dv2.generate_satellites import render_satellites

DV2_DIR = Path(dialects_mod.__file__).resolve().parent
PG_DIR = DV2_DIR / "postgres"

# Tokens that must never survive into PostgreSQL DDL (checked on comment-stripped
# SQL, since the business-vault comments deliberately mention the CH originals).
CH_TOKENS = (
    "fixedstring",
    "lowcardinality",
    "nullable(",
    "engine",
    "toyyyymm",
    "mergetree",
    "argmax(",
    "splitbystring",
    "tofixedstring",
    "now64",
)


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", "", sql)
    return sql


def _pg_sql_files() -> list[Path]:
    files = [
        PG_DIR / "00_schema.sql",
        PG_DIR / "01_hubs.sql",
        PG_DIR / "02_links.sql",
        PG_DIR / "03_business_vault.sql",
    ]
    files += [Path(p) for p in sorted(glob.glob(str(PG_DIR / "satellites" / "*.sql")))]
    files += [Path(p) for p in sorted(glob.glob(str(PG_DIR / "governance" / "*.sql")))]
    return files


# --- type mapping ------------------------------------------------------------


@pytest.mark.parametrize(
    ("ch", "pg"),
    [
        ("String", "TEXT"),
        ("LowCardinality(String)", "TEXT"),
        ("Nullable(String)", "TEXT"),
        ("FixedString(16)", "BYTEA"),
        ("FixedString(2)", "CHAR(2)"),
        ("DateTime64(3)", "TIMESTAMP(3)"),
        ("Nullable(DateTime64(3))", "TIMESTAMP(3)"),
        ("Decimal(18, 2)", "NUMERIC(18, 2)"),
        ("Nullable(Decimal(18, 2))", "NUMERIC(18, 2)"),
        ("Decimal(5, 2)", "NUMERIC(5, 2)"),
        ("UInt8", "SMALLINT"),
        ("UInt16", "INTEGER"),
        ("UInt32", "BIGINT"),
        ("Nullable(Date)", "DATE"),
        ("Bool DEFAULT true", "BOOLEAN DEFAULT TRUE"),
        ("Bool DEFAULT false", "BOOLEAN DEFAULT FALSE"),
    ],
)
def test_clickhouse_to_postgres_type(ch: str, pg: str):
    assert to_pg(ch) == pg


def test_unsigned_ints_widen_to_hold_full_range():
    # UInt16 max 65535 > PG smallint; UInt32 > PG integer — widen one step.
    assert to_pg("UInt16") == "INTEGER"
    assert to_pg("UInt32") == "BIGINT"


def test_unmapped_type_raises():
    with pytest.raises(ValueError):
        to_pg("Tuple(UInt8, String)")


# --- generation --------------------------------------------------------------


def test_render_postgres_satellites_matches_clickhouse_count(tmp_path):
    pg_count = render_satellites(tmp_path / "pg", dialect="postgres")
    ch_count = render_satellites(tmp_path / "ch", dialect="clickhouse")
    assert pg_count == ch_count
    assert pg_count == len(list((tmp_path / "pg").glob("*.sql")))
    assert pg_count >= 39


def test_committed_postgres_satellites_present():
    generated = list((PG_DIR / "satellites").glob("*.sql"))
    assert len(generated) >= 39
    assert (PG_DIR / "satellites" / "sat_product_reference__ref__global.sql").exists()


# --- DDL validity ------------------------------------------------------------


def test_all_postgres_ddl_parses():
    files = _pg_sql_files()
    assert len(files) >= 47
    for path in files:
        sql = path.read_text(encoding="utf-8")
        parsed = sqlglot.parse(sql, dialect="postgres")
        assert parsed, f"{path.name} produced no statements"


def test_no_clickhouse_constructs_leak_into_postgres_ddl():
    for path in _pg_sql_files():
        body = _strip_comments(path.read_text(encoding="utf-8")).lower()
        for token in CH_TOKENS:
            assert token not in body, f"{path.name} still contains ClickHouse token {token!r}"


def test_business_vault_uses_postgres_collapse():
    bv = (PG_DIR / "03_business_vault.sql").read_text(encoding="utf-8")
    body = _strip_comments(bv).lower()
    assert "distinct on (order_hk)" in body
    assert "split_part(record_source, '__', 2)" in body
    assert "case when" in body
    # 5 LEFT JOINs in bv_order_canonical + 8 across the customer MDM views
    # (msk/spb/ekb: personal+loyalty = 2 each; dxb/ala: personal only = 1 each).
    assert body.count("left join") == 13
    parsed = sqlglot.parse(bv, dialect="postgres")
    assert parsed, "03_business_vault.sql produced no statements"


def test_customer_mdm_views_admit_all_source_conventions():
    """audit_28_06_26 #12: the customer MDM views must select hub rows by
    branch via split_part(record_source, '__', 2), NOT by a hard-coded
    record_source = '1c__<branch>' filter that silently drops OLTP/X5-promoted
    customers (record_source pg_ops__/x5__). Proven live on PG: the buggy filter
    returns 1 of 2 seeded customers, the split_part filter returns both."""
    body = _strip_comments((PG_DIR / "03_business_vault.sql").read_text(encoding="utf-8")).lower()
    branches = ("msk", "spb", "ekb", "dxb", "ala")
    for branch in branches:
        assert f"view rv.bv_customer_mdm__{branch}" in body, f"missing PG view for {branch}"
        assert f"split_part(record_source, '__', 2) = '{branch}'" in body, (
            f"bv_customer_mdm__{branch} must admit hubs by branch, not by source convention"
        )
    # the regressed pattern must never reappear in any customer MDM hub filter.
    assert "record_source = '1c__" not in body, (
        "hard-coded record_source = '1c__<branch>' filter reintroduces audit #12"
    )


def test_hubs_and_links_have_bytea_primary_keys():
    hubs = (PG_DIR / "01_hubs.sql").read_text(encoding="utf-8")
    links = (PG_DIR / "02_links.sql").read_text(encoding="utf-8")
    # one BYTEA primary key per table: 8 hubs, 8 links.
    assert hubs.count("BYTEA PRIMARY KEY") == 8
    assert links.count("BYTEA PRIMARY KEY") == 8
    # link member hash keys are NOT NULL, not part of the PK.
    assert "BYTEA NOT NULL" in links
