"""Unit tests for the DV2 ClickHouse business-vault views (no Docker).

The ClickHouse ``business_vault/*.sql`` views had no parse or coverage before
this file. It pins that every view parses under sqlglot's ClickHouse dialect and
that the customer MDM views admit hub rows by branch via
``splitByString('__', record_source)[2]`` — NOT by a hard-coded
``record_source = '1c__<branch>'`` filter that silently dropped OLTP/marketplace-
promoted customers (``record_source`` ``pg_ops__`` / ``mp__``).

This is the ClickHouse half of audit_28_06_26 #12. The PostgreSQL port was fixed
in ``test_dv2_postgres_ddl.py::test_customer_mdm_views_admit_all_source_conventions``;
pinning the ClickHouse views to the same source-agnostic admission keeps the two
engines from drifting apart (the split-brain the audit flagged). A live apply +
``bv_customer_mdm`` query is a separate Mac smoke (see business_vault/README.md).
"""

from __future__ import annotations

import glob
import re
from pathlib import Path

import sqlglot

import warehouse.agentflow.dv2.dialects as dialects_mod

DV2_DIR = Path(dialects_mod.__file__).resolve().parent
BV_DIR = DV2_DIR / "business_vault"

MDM_BRANCHES = ("msk", "spb", "ekb", "dxb", "ala")


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", "", sql)
    return sql


def _bv_sql_files() -> list[Path]:
    return [Path(p) for p in sorted(glob.glob(str(BV_DIR / "*.sql")))]


def test_all_business_vault_ddl_parses():
    files = _bv_sql_files()
    # 5 customer MDM views + bv_order_canonical + bv_order_canonical_mat.
    assert len(files) >= 7, f"expected >=7 business-vault SQL files, found {len(files)}"
    for path in files:
        parsed = sqlglot.parse(path.read_text(encoding="utf-8"), dialect="clickhouse")
        assert parsed, f"{path.name} produced no statements"


def test_every_mdm_branch_view_exists():
    for branch in MDM_BRANCHES:
        path = BV_DIR / f"bv_customer_mdm__{branch}.sql"
        assert path.exists(), f"missing ClickHouse MDM view for branch {branch}"


def test_customer_mdm_views_admit_all_source_conventions():
    """audit_28_06_26 #12 (ClickHouse half): the customer MDM views must select
    hub rows by branch via ``splitByString('__', record_source)[2]``, NOT by a
    hard-coded ``record_source = '1c__<branch>'`` filter that silently drops
    OLTP/marketplace-promoted customers (record_source ``pg_ops__`` / ``mp__``).
    Proven live on PostgreSQL in #99: the buggy filter returns 1 of 2 seeded
    customers, the source-agnostic filter returns both. This keeps the
    ClickHouse views in lock-step with the PostgreSQL port so the engines
    cannot diverge again."""
    for branch in MDM_BRANCHES:
        path = BV_DIR / f"bv_customer_mdm__{branch}.sql"
        # Strip block/line comments: the headers deliberately quote the old,
        # buggy ``record_source = '1c__<branch>'`` filter to explain the fix.
        raw = path.read_text(encoding="utf-8")
        body = _strip_comments(raw)
        assert f"CREATE OR REPLACE VIEW rv.bv_customer_mdm__{branch}" in body, (
            f"bv_customer_mdm__{branch}.sql must define rv.bv_customer_mdm__{branch}"
        )
        assert f"splitByString('__', record_source)[2] = '{branch}'" in body, (
            f"bv_customer_mdm__{branch} must admit hubs by branch via "
            f"splitByString('__', record_source)[2], not by source convention"
        )
        # The regressed pattern must never reappear in executable SQL.
        assert "record_source = '1c__" not in body, (
            f"hard-coded record_source = '1c__<branch>' filter in "
            f"bv_customer_mdm__{branch} reintroduces audit #12"
        )
        # B2 (domain.md §5.4): the legend's marketplace-feed vocabulary replaces
        # the Kaggle dataset name in the third-source-convention example (checked
        # on the RAW text — the example lives in the header comment, which body
        # strips).
        assert "x5__" not in raw, (
            f"stale Kaggle-dataset record_source prefix x5__ leaked back into bv_customer_mdm__{branch}.sql"
        )
        assert "mp__" in raw, (
            f"bv_customer_mdm__{branch}.sql should document the mp__ marketplace-feed convention (domain.md §5.3)"
        )
