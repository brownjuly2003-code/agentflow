"""Unit tests for the DV2 vault governance layer (ADR 0006 Phase 2, no Docker).

``warehouse/agentflow/dv2/governance/`` is the engine-enforced PII boundary:
roles, fail-closed allow-list grants and row policies. These tests pin the
*structure* that makes the boundary sound — sqlglot cannot fully type-check
RBAC DDL (CREATE ROLE / CREATE ROW POLICY fall back to Command), so the pins
are textual over comment-stripped SQL:

- the analyst allow-list never grants a contact-PII column or a PII table;
- every raw_vault satellite is either granted to ``dv2_analyst`` or explicitly
  listed in the DENIED block (fail-closed ratchet: adding a satellite without
  classifying it breaks this test, not the boundary);
- every branch has an officer role, jurisdiction-scoped grants and a row
  policy, and the mandatory catch-all row policy exempts exactly the officer
  roles (the ClickHouse gotcha: with
  ``users_without_row_policies_can_read_rows=false`` — older carried-over
  configs — any policy on a table hides all rows from unaddressed principals);
- the MDM views run SQL SECURITY DEFINER (a column grant on an INVOKER view
  would be dead — readers would need the underlying personal satellites);
- ``marts/customer_360`` stays PII-free (a cross-branch materialized mart
  carrying contact fields would copy PII past the column grants at build time).

Live behavior (ACCESS_DENIED on the historical bypass shapes, row-policy
filtering) is verified against a real ClickHouse in
``docs/perf/vault-pii-governance-verify-2026-07-02.md``.
"""

from __future__ import annotations

import glob
import re
from pathlib import Path

import sqlglot

import warehouse.agentflow.dv2.dialects as dialects_mod

DV2_DIR = Path(dialects_mod.__file__).resolve().parent
GOV_DIR = DV2_DIR / "governance"
BV_DIR = DV2_DIR / "business_vault"
SAT_DIR = DV2_DIR / "raw_vault" / "satellites"
MARTS_DIR = DV2_DIR / "dbt" / "models" / "marts"

BRANCHES = ("msk", "spb", "ekb", "dxb", "ala")
PII_COLUMNS = ("first_name", "last_name", "email", "phone", "birth_date")
OFFICER_ROLES = tuple(f"dv2_pii_officer__{b}" for b in BRANCHES)

ROLES_SQL = GOV_DIR / "01_roles.sql"
ANALYST_SQL = GOV_DIR / "02_grants_analyst.sql"
OFFICERS_SQL = GOV_DIR / "03_grants_pii_officers.sql"
POLICIES_SQL = GOV_DIR / "04_row_policies.sql"


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", "", sql)
    return sql


def _executable(path: Path) -> str:
    return _strip_comments(path.read_text(encoding="utf-8"))


def test_governance_files_exist_and_parse():
    for path in (ROLES_SQL, ANALYST_SQL, OFFICERS_SQL, POLICIES_SQL):
        assert path.exists(), f"missing governance file {path.name}"
        # CREATE ROLE / CREATE ROW POLICY fall back to sqlglot Command; the
        # assertion is "no parse error and at least one statement per file".
        parsed = sqlglot.parse(path.read_text(encoding="utf-8"), dialect="clickhouse")
        assert parsed, f"{path.name} produced no statements"


def test_roles_declared_once_and_referenced_consistently():
    roles_body = _executable(ROLES_SQL)
    assert "CREATE ROLE IF NOT EXISTS dv2_analyst" in roles_body
    for role in OFFICER_ROLES:
        assert f"CREATE ROLE IF NOT EXISTS {role}" in roles_body, (
            f"{role} must be declared in 01_roles.sql"
        )
    # Every role referenced by grants/policies must be declared in 01.
    referenced = set()
    for path in (ANALYST_SQL, OFFICERS_SQL, POLICIES_SQL):
        referenced.update(re.findall(r"dv2_[a-z_]+", _executable(path)))
    declared = set(re.findall(r"CREATE ROLE IF NOT EXISTS (dv2_[a-z_]+)", roles_body))
    assert referenced <= declared, (
        f"roles referenced but never declared: {sorted(referenced - declared)}"
    )


def test_analyst_allowlist_never_grants_pii():
    body = _executable(ANALYST_SQL)
    for col in PII_COLUMNS:
        assert col not in body, (
            f"02_grants_analyst.sql grants contact-PII column {col!r} — the "
            f"analyst boundary is exactly 'these columns are never granted'"
        )
    for pii_table in ("sat_customer_personal", "sat_employee_profile"):
        assert pii_table not in body, (
            f"02_grants_analyst.sql grants PII table {pii_table}* to dv2_analyst"
        )
    # Deny-by-default direction: the allow-list must not fall back to db-wide
    # grants, which would expose the next PII table by default.
    assert not re.search(r"GRANT[^;]+ON\s+rv\.\*", body), (
        "02_grants_analyst.sql must not grant rv.* — allow-list is per object"
    )


def test_every_satellite_is_classified():
    """Fail-closed ratchet: a new raw_vault satellite must be either granted to
    dv2_analyst or explicitly listed in the DENIED block of the allow-list."""
    raw = ANALYST_SQL.read_text(encoding="utf-8")
    satellites = [Path(p).stem for p in sorted(glob.glob(str(SAT_DIR / "*.sql")))]
    assert len(satellites) >= 40, "satellite fixture glob looks broken"
    unclassified = [s for s in satellites if s not in raw]
    assert not unclassified, (
        f"raw_vault satellites neither granted to dv2_analyst nor listed in "
        f"the DENIED block of 02_grants_analyst.sql: {unclassified} — classify "
        f"them (grant or deny) before shipping"
    )


def test_analyst_mdm_grants_are_column_limited():
    body = _executable(ANALYST_SQL)
    for branch in BRANCHES:
        pattern = (
            rf"GRANT SELECT\(([^)]+)\)\s*\n?\s*ON rv\.bv_customer_mdm__{branch} "
            rf"TO dv2_analyst"
        )
        match = re.search(pattern, body)
        assert match, (
            f"bv_customer_mdm__{branch} must have a column-limited "
            f"GRANT SELECT(...) for dv2_analyst"
        )
        granted = {c.strip() for c in match.group(1).replace("\n", " ").split(",")}
        assert not (granted & set(PII_COLUMNS)), (
            f"PII columns granted on bv_customer_mdm__{branch}: "
            f"{sorted(granted & set(PII_COLUMNS))}"
        )
        assert {"customer_hk", "customer_bk", "branch"} <= granted, (
            f"bv_customer_mdm__{branch} analyst grant lost its key columns"
        )


def test_officer_grants_are_jurisdiction_scoped():
    body = _executable(OFFICERS_SQL)
    statements = [s.strip() for s in body.split(";") if s.strip()]
    for branch in BRANCHES:
        role = f"dv2_pii_officer__{branch}"
        granted_objects = set()
        for stmt in statements:
            if not stmt.endswith(role):
                continue
            granted_objects.update(re.findall(r"ON (rv\.[a-z0-9_]+)", stmt))
        assert granted_objects == {
            f"rv.bv_customer_mdm__{branch}",
            f"rv.sat_customer_personal__1c__{branch}",
            "rv.hub_customer",
        }, f"{role} grant surface drifted: {sorted(granted_objects)}"
        # No statement may hand this role another branch's object.
        for other in BRANCHES:
            if other == branch:
                continue
            for stmt in statements:
                if stmt.endswith(role):
                    assert f"__{other}" not in stmt, f"{role} granted a {other} object: {stmt[:80]}"


def test_row_policies_cover_every_branch_and_keep_the_catch_all():
    body = _executable(POLICIES_SQL)
    for branch in BRANCHES:
        pattern = (
            rf"CREATE ROW POLICY IF NOT EXISTS jurisdiction__{branch} "
            rf"ON rv\.hub_customer\s*\n?\s*FOR SELECT "
            rf"USING splitByString\('__', record_source\)\[2\] = '{branch}'\s*\n?\s*"
            rf"TO dv2_pii_officer__{branch}"
        )
        assert re.search(pattern, body), f"missing/malformed jurisdiction row policy for {branch}"
    catch_all = re.search(
        r"CREATE ROW POLICY IF NOT EXISTS jurisdiction__all ON rv\.hub_customer"
        r"\s*\n?\s*FOR SELECT USING 1\s*\n?\s*TO ALL EXCEPT ([^;]+);",
        body,
    )
    assert catch_all, (
        "the catch-all row policy is mandatory: on stands where "
        "users_without_row_policies_can_read_rows=false (older configs), any "
        "policy on hub_customer hides ALL rows from unaddressed principals; "
        "the catch-all pins non-officer visibility independent of that flag"
    )
    excepted = {r.strip() for r in catch_all.group(1).replace("\n", " ").split(",")}
    assert excepted == set(OFFICER_ROLES), (
        f"catch-all EXCEPT list out of sync with officer roles: {sorted(excepted)}"
    )


def test_mdm_views_run_sql_security_definer():
    for branch in BRANCHES:
        body = _executable(BV_DIR / f"bv_customer_mdm__{branch}.sql")
        assert re.search(
            rf"CREATE OR REPLACE VIEW rv\.bv_customer_mdm__{branch}\s*\n?\s*"
            rf"SQL SECURITY DEFINER AS",
            body,
        ), (
            f"bv_customer_mdm__{branch} must run SQL SECURITY DEFINER — with "
            f"INVOKER the column-limited analyst grant is dead (readers would "
            f"need SELECT on the denied personal satellite)"
        )


def test_customer_360_mart_stays_pii_free():
    raw = (MARTS_DIR / "customer_360.sql").read_text(encoding="utf-8")
    # Strip jinja comments {# ... #} and SQL comments; keep executable SQL.
    body = _strip_comments(re.sub(r"\{#.*?#\}", "", raw, flags=re.DOTALL))
    for col in PII_COLUMNS:
        assert not re.search(rf"\b{col}\b", body), (
            f"marts/customer_360.sql selects contact-PII column {col!r} — the "
            f"mart is cross-branch and materialized, so this copies "
            f"jurisdiction-bound PII past the engine column grants"
        )
    assert "pii_source" in body, (
        "customer_360 should keep pii_source metadata (which source "
        "contributed PII) — only the contact fields are out of contract"
    )
