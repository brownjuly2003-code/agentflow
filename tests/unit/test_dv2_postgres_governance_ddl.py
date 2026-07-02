"""Unit tests for the PostgreSQL port of the DV2 vault governance layer (no Docker).

``warehouse/agentflow/dv2/postgres/governance/`` is the PostgreSQL analog of the
ClickHouse engine-enforced PII boundary (ADR 0006 Phase 2; ClickHouse pins live
in ``test_dv2_governance_ddl.py``): roles, fail-closed allow-list grants and
row-level security. sqlglot cannot fully type-check RBAC DDL (DO blocks and
CREATE POLICY fall back to Command), so the pins are textual over
comment-stripped SQL:

- the analyst allow-list never grants a contact-PII column or a PII table, and
  never uses the PostgreSQL fail-open shapes (``ALL TABLES IN SCHEMA``,
  ``ALTER DEFAULT PRIVILEGES``);
- every postgres satellite is either granted to ``dv2_analyst`` or explicitly
  listed in the DENIED block (fail-closed ratchet);
- every branch has an officer role, jurisdiction-scoped grants and a row
  policy; the catch-all addresses ``dv2_analyst`` explicitly and must NOT be
  ``TO PUBLIC`` (permissive policies OR together — a PUBLIC catch-all would
  void the officer scoping, since officers are members of PUBLIC);
- RLS is ENABLEd, never FORCEd (the owner-executed MDM views would return zero
  rows under FORCE), and the MDM views never set ``security_invoker`` (the
  PostgreSQL default — owner's rights — is the SQL SECURITY DEFINER analog the
  column-limited grants rely on).

Live behavior (``permission denied`` on every PII shape incl. the
PostgreSQL-only positional rename-list and whole-row/to_jsonb refs, row-policy
scoping, default-deny for unaddressed principals, owner bypass) is verified
against a real PostgreSQL 17.5 in
``docs/perf/vault-pii-governance-pg-verify-2026-07-02.md``.
"""

from __future__ import annotations

import glob
import re
from pathlib import Path

import sqlglot

import warehouse.agentflow.dv2.dialects as dialects_mod

DV2_DIR = Path(dialects_mod.__file__).resolve().parent
GOV_DIR = DV2_DIR / "postgres" / "governance"
SAT_DIR = DV2_DIR / "postgres" / "satellites"
BV_SQL = DV2_DIR / "postgres" / "03_business_vault.sql"

BRANCHES = ("msk", "spb", "ekb", "dxb", "ala")
PII_COLUMNS = ("first_name", "last_name", "email", "phone", "birth_date")
OFFICER_ROLES = tuple(f"dv2_pii_officer__{b}" for b in BRANCHES)
ALL_ROLES = ("dv2_analyst", *OFFICER_ROLES)

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
        # DO blocks / CREATE POLICY fall back to sqlglot Command; the assertion
        # is "no parse error and at least one statement per file".
        parsed = sqlglot.parse(path.read_text(encoding="utf-8"), dialect="postgres")
        assert parsed, f"{path.name} produced no statements"


def test_no_nested_block_comments():
    """PostgreSQL block comments NEST: a stray '/*' inside a header comment
    (e.g. a 'satellites/*.sql' glob) swallows the rest of the file silently on
    apply. Caught live; pinned here for every governance file."""
    for path in (ROLES_SQL, ANALYST_SQL, OFFICERS_SQL, POLICIES_SQL):
        text = path.read_text(encoding="utf-8")
        assert text.count("/*") == text.count("*/"), (
            f"{path.name}: unbalanced block comments — PostgreSQL nests them, "
            f"an inner '/*' makes the outer comment unterminated"
        )
        for block in re.findall(r"/\*(.*?)\*/", text, flags=re.DOTALL):
            assert "/*" not in block, (
                f"{path.name}: nested '/*' inside a block comment breaks psql apply"
            )


def test_roles_declared_once_and_referenced_consistently():
    roles_body = _executable(ROLES_SQL)
    declared = set(re.findall(r"CREATE ROLE (dv2_[a-z_]+) NOLOGIN", roles_body))
    assert declared == set(ALL_ROLES), f"role set drifted: {sorted(declared)}"
    # Every role referenced by grants/policies must be declared in 01.
    referenced = set()
    for path in (ANALYST_SQL, OFFICERS_SQL, POLICIES_SQL):
        referenced.update(re.findall(r"dv2_[a-z_]+", _executable(path)))
    assert referenced <= declared, (
        f"roles referenced but never declared: {sorted(referenced - declared)}"
    )


def test_schema_usage_granted_to_every_role():
    """USAGE on schema rv is the PostgreSQL prerequisite for reaching any
    object in it; without it every downstream grant is dead."""
    body = _executable(ROLES_SQL)
    match = re.search(r"GRANT USAGE ON SCHEMA rv TO ([^;]+);", body)
    assert match, "01_roles.sql must grant USAGE on schema rv"
    granted = {r.strip() for r in match.group(1).replace("\n", " ").split(",")}
    assert granted == set(ALL_ROLES), (
        f"schema USAGE grant out of sync with the role set: {sorted(granted)}"
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
    # Deny-by-default direction: the allow-list must not fall back to the
    # PostgreSQL fail-open shapes, which would expose the next PII table (or
    # future objects) by default.
    assert "ALL TABLES IN SCHEMA" not in body, (
        "02_grants_analyst.sql must not grant ALL TABLES IN SCHEMA — the allow-list is per object"
    )
    assert "ALTER DEFAULT PRIVILEGES" not in body, (
        "02_grants_analyst.sql must not use ALTER DEFAULT PRIVILEGES — future "
        "objects must stay invisible until classified"
    )


def test_every_satellite_is_classified():
    """Fail-closed ratchet: a new postgres satellite must be either granted to
    dv2_analyst or explicitly listed in the DENIED block of the allow-list."""
    raw = ANALYST_SQL.read_text(encoding="utf-8")
    satellites = [Path(p).stem for p in sorted(glob.glob(str(SAT_DIR / "*.sql")))]
    assert len(satellites) >= 40, "satellite fixture glob looks broken"
    unclassified = [s for s in satellites if s not in raw]
    assert not unclassified, (
        f"postgres satellites neither granted to dv2_analyst nor listed in "
        f"the DENIED block of 02_grants_analyst.sql: {unclassified} — classify "
        f"them (grant or deny) before shipping"
    )


def test_analyst_mdm_grants_are_column_limited():
    body = _executable(ANALYST_SQL)
    for branch in BRANCHES:
        pattern = (
            rf"GRANT SELECT \(([^)]+)\)\s*\n?\s*ON rv\.bv_customer_mdm__{branch} "
            rf"TO dv2_analyst"
        )
        match = re.search(pattern, body)
        assert match, (
            f"bv_customer_mdm__{branch} must have a column-limited "
            f"GRANT SELECT (...) for dv2_analyst"
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


def test_row_policies_cover_every_branch_and_keep_the_analyst_catch_all():
    body = _executable(POLICIES_SQL)
    assert re.search(r"ALTER TABLE rv\.hub_customer ENABLE ROW LEVEL SECURITY", body), (
        "04_row_policies.sql must ENABLE row level security on rv.hub_customer"
    )
    for branch in BRANCHES:
        assert f"DROP POLICY IF EXISTS jurisdiction__{branch} ON rv.hub_customer" in body, (
            f"jurisdiction__{branch} must DROP IF EXISTS before CREATE — "
            f"CREATE POLICY has no IF NOT EXISTS, re-apply would fail"
        )
        pattern = (
            rf"CREATE POLICY jurisdiction__{branch} ON rv\.hub_customer\s*\n?\s*"
            rf"FOR SELECT TO dv2_pii_officer__{branch}\s*\n?\s*"
            rf"USING \(split_part\(record_source, '__', 2\) = '{branch}'\)"
        )
        assert re.search(pattern, body), f"missing/malformed jurisdiction row policy for {branch}"
    catch_all = re.search(
        r"CREATE POLICY jurisdiction__all ON rv\.hub_customer\s*\n?\s*"
        r"FOR SELECT TO ([a-z0-9_,\s]+?)\s*\n?\s*USING \(true\)",
        body,
    )
    assert catch_all, (
        "the analyst catch-all policy is mandatory: PostgreSQL RLS is "
        "default-deny, so without it dv2_analyst reads zero hub rows"
    )
    addressed = {r.strip() for r in catch_all.group(1).split(",")}
    assert addressed == {"dv2_analyst"}, (
        f"catch-all must address exactly dv2_analyst, got {sorted(addressed)}"
    )


def test_policies_never_use_public_or_force():
    body = _executable(POLICIES_SQL)
    assert not re.search(r"\bTO PUBLIC\b", body, flags=re.IGNORECASE), (
        "a TO PUBLIC policy would OR into the officer policies (permissive "
        "policies combine, officers are members of PUBLIC) and void the "
        "jurisdiction scoping"
    )
    assert not re.search(r"\bFORCE ROW LEVEL SECURITY\b", body, flags=re.IGNORECASE), (
        "FORCE would subject the owner-executed bv_customer_mdm__* views to "
        "these policies and empty them for every reader — ENABLE only"
    )


def test_mdm_views_do_not_set_security_invoker():
    """The column-limited analyst grants rely on the PostgreSQL default view
    behavior (owner's rights — the SQL SECURITY DEFINER analog). A view with
    security_invoker=true would demand SELECT on the denied personal
    satellites from every reader, killing the grants."""
    body = _executable(BV_SQL).lower()
    assert "security_invoker" not in body, (
        "03_business_vault.sql sets security_invoker — the governance "
        "column grants require owner-rights (default) views"
    )
