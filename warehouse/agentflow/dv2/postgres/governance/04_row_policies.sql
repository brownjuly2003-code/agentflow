/*
Purpose: Jurisdiction row scoping on the shared hub_customer — PostgreSQL port
         of the ClickHouse row policies (../../governance/04_row_policies.sql,
         ADR 0006 Phase 2 follow-up).
Layer:   Governance (PostgreSQL row-level security).
Model:   hub_customer is the one customer table shared across branches (branch
         is carried in record_source). PII-officer roles are row-scoped to
         their own jurisdiction; dv2_analyst keeps full hub visibility (the
         hub holds pseudonymous business keys, not contact PII).

PostgreSQL semantics this file is built around (they DIFFER from ClickHouse):
  - Default-deny once RLS is enabled: a principal not addressed by any policy
    sees ZERO rows. There is no users_without_row_policies_can_read_rows flag
    to pin against — but the flip side is that any future role granted SELECT
    on the hub reads nothing until it is classified into a policy here. That
    is fail-closed, consistent with the allow-list in 02_grants_analyst.sql.
  - Permissive policies combine with OR, and every role is a member of PUBLIC.
    The catch-all therefore must NOT be `TO PUBLIC` — OR-ing `USING (true)`
    into the officer policies would void their jurisdiction scoping. It
    addresses dv2_analyst explicitly instead (the ClickHouse original models
    the same intent as TO ALL EXCEPT <officers>).
  - ENABLE, not FORCE: the table owner bypasses RLS. The bv_customer_mdm__*
    views execute with their owner's rights (PostgreSQL default for views —
    the SQL SECURITY DEFINER analog; security_invoker is never set), so the
    views read the full hub and pin their branch in their own WHERE — the same
    construction as on ClickHouse. FORCE would subject the owner-executed
    views to these policies and empty them for every reader; never use FORCE
    here.
  - CREATE POLICY has no IF NOT EXISTS: DROP POLICY IF EXISTS + CREATE keeps
    re-apply idempotent.
A policy addresses the members of the roles in its TO list: a user GRANTed
dv2_pii_officer__msk is matched by jurisdiction__msk. Keep the TO lists in
sync with 01_roles.sql (pinned by tests/unit/test_dv2_postgres_governance_ddl.py).
*/

ALTER TABLE rv.hub_customer ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS jurisdiction__msk ON rv.hub_customer;
CREATE POLICY jurisdiction__msk ON rv.hub_customer
    FOR SELECT TO dv2_pii_officer__msk
    USING (split_part(record_source, '__', 2) = 'msk');

DROP POLICY IF EXISTS jurisdiction__spb ON rv.hub_customer;
CREATE POLICY jurisdiction__spb ON rv.hub_customer
    FOR SELECT TO dv2_pii_officer__spb
    USING (split_part(record_source, '__', 2) = 'spb');

DROP POLICY IF EXISTS jurisdiction__ekb ON rv.hub_customer;
CREATE POLICY jurisdiction__ekb ON rv.hub_customer
    FOR SELECT TO dv2_pii_officer__ekb
    USING (split_part(record_source, '__', 2) = 'ekb');

DROP POLICY IF EXISTS jurisdiction__dxb ON rv.hub_customer;
CREATE POLICY jurisdiction__dxb ON rv.hub_customer
    FOR SELECT TO dv2_pii_officer__dxb
    USING (split_part(record_source, '__', 2) = 'dxb');

DROP POLICY IF EXISTS jurisdiction__ala ON rv.hub_customer;
CREATE POLICY jurisdiction__ala ON rv.hub_customer
    FOR SELECT TO dv2_pii_officer__ala
    USING (split_part(record_source, '__', 2) = 'ala');

-- Catch-all for the non-officer analytics role: PostgreSQL RLS is default-deny,
-- so dv2_analyst must be addressed explicitly to keep full hub visibility
-- (the hub holds pseudonymous business keys, not contact PII). Deliberately
-- NOT `TO PUBLIC` — see the header.
DROP POLICY IF EXISTS jurisdiction__all ON rv.hub_customer;
CREATE POLICY jurisdiction__all ON rv.hub_customer
    FOR SELECT TO dv2_analyst
    USING (true);
