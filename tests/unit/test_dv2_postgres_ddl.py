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


# B2 (brand-neutral restoration of a guard dropped during X5 removal, G2
# audit): the header comment's illustrative "which source conventions does
# this admit" example must only ever name known-good record_source prefixes.
# Checked against an explicit allowlist rather than a literal bad string, so
# this test never itself has to spell out the retired dataset's prefix to
# guard against it reappearing.
_RECORD_SOURCE_PREFIX_ALLOWLIST = {"1c__", "mp__", "pg_ops__", "wms__", "ref__"}
_SOURCE_CONVENTION_PAREN_RE = re.compile(r"source convention\s*\(([^)]*)\)", re.IGNORECASE)
_SOURCE_AGNOSTIC_RE = re.compile(r"source-agnostic:\s*([^;]*);", re.IGNORECASE)
_PREFIX_TOKEN_RE = re.compile(r"([a-z0-9](?:[a-z0-9]|_(?!_))*)__")


def _record_source_example_prefixes(raw: str) -> set[str]:
    """Prefix tokens (``1c__``, ``mp__``, ...) named in a DDL header comment's
    illustrative "source convention"/"source-agnostic" example list — not
    every record_source value the file's views/tables actually use, just the
    documented examples."""
    prefixes: set[str] = set()
    for pattern in (_SOURCE_CONVENTION_PAREN_RE, _SOURCE_AGNOSTIC_RE):
        for match in pattern.finditer(raw):
            prefixes.update(f"{token}__" for token in _PREFIX_TOKEN_RE.findall(match.group(1)))
    return prefixes


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
    record_source = '1c__<branch>' filter that silently drops OLTP/marketplace-
    promoted customers (record_source pg_ops__/mp__). Proven live on PG: the
    buggy filter returns 1 of 2 seeded customers, the split_part filter returns
    both."""
    raw = (PG_DIR / "03_business_vault.sql").read_text(encoding="utf-8").lower()
    body = _strip_comments(raw)
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
    # domain.md §5.3/§5.4: the header comment's source-convention example must
    # document the consolidated marketplace-feed prefix (checked on the RAW
    # text — the example lives in the header comment, which body strips).
    assert "mp__" in raw, (
        "03_business_vault.sql should document the mp__ marketplace-feed convention (domain.md §5.3)"
    )
    example_prefixes = _record_source_example_prefixes(raw)
    assert example_prefixes, (
        "03_business_vault.sql should document its record_source source-convention "
        "examples in the header comment"
    )
    assert example_prefixes <= _RECORD_SOURCE_PREFIX_ALLOWLIST, (
        "03_business_vault.sql documents unexpected record_source prefix(es) "
        f"{sorted(example_prefixes - _RECORD_SOURCE_PREFIX_ALLOWLIST)} outside the "
        f"allowlist {sorted(_RECORD_SOURCE_PREFIX_ALLOWLIST)} — a stale/regressed "
        "dataset prefix may have leaked back into the header comment"
    )


def test_hubs_and_links_have_bytea_primary_keys():
    hubs = (PG_DIR / "01_hubs.sql").read_text(encoding="utf-8")
    links = (PG_DIR / "02_links.sql").read_text(encoding="utf-8")
    # one BYTEA primary key per table: 8 hubs, 8 links.
    assert hubs.count("BYTEA PRIMARY KEY") == 8
    assert links.count("BYTEA PRIMARY KEY") == 8
    # link member hash keys are NOT NULL, not part of the PK.
    assert "BYTEA NOT NULL" in links


# --- bv_order_canonical smoke seed (G1) --------------------------------------
# The live query is a Mac smoke (postgres/smoke/verify_bv_order.sh); the seed
# itself is gated no-Docker here, exactly like the rest of the PG vault.

SMOKE_SEED = PG_DIR / "smoke" / "order_smoke_seed.sql"


def test_bv_order_smoke_seed_parses_as_postgres():
    sql = SMOKE_SEED.read_text(encoding="utf-8")
    parsed = sqlglot.parse(sql, dialect="postgres")
    assert parsed, "order_smoke_seed.sql produced no statements"
    inserts = [s for s in parsed if s and s.key == "insert"]
    # hubs (3) + links (2) + headers (bitrix ×5 + 1c ×1) + pricing (×4) + wb (1)
    assert len(inserts) >= 15, f"expected >=15 INSERTs, got {len(inserts)}"


def test_bv_order_smoke_seed_has_no_clickhouse_constructs():
    body = _strip_comments(SMOKE_SEED.read_text(encoding="utf-8")).lower()
    for token in CH_TOKENS:
        assert token not in body, f"smoke seed still contains ClickHouse token {token!r}"
    # PostgreSQL hash idiom, not the ClickHouse MD5(toString(...)) form.
    assert "decode(md5(" in body
    assert "md5(tostring(" not in body


def test_bv_order_smoke_seed_covers_every_order_source_and_branch():
    body = _strip_comments(SMOKE_SEED.read_text(encoding="utf-8"))
    # all three order-satellite families the view reconstructs
    assert "rv.sat_order_header__bitrix__" in body
    assert "rv.sat_order_pricing__1c__" in body
    assert "rv.sat_order_marketplace__wb__msk" in body
    # marketplace state exists for msk (production seed never populated it)
    assert body.count("rv.sat_order_marketplace__wb__msk") == 1
    # every jurisdiction present so split_part branch derivation is exercised
    for branch in ("msk", "spb", "ekb", "dxb", "ala"):
        assert f"bitrix__{branch}__" in body, f"smoke seed missing {branch} order"
