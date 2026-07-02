/*
Purpose: Jurisdiction row scoping on the shared hub_customer (ADR 0006 Phase 2).
Layer:   Governance (ClickHouse row policies).
Model:   hub_customer is the one customer table shared across branches (branch
         is carried in record_source). PII-officer roles are row-scoped to
         their own jurisdiction; everyone else keeps full hub visibility (the
         hub holds pseudonymous business keys, not contact PII).

ClickHouse gotcha this file is built around: whether principals NOT addressed
by any policy on a policied table still see rows is controlled by the server
flag `access_control_improvements.users_without_row_policies_can_read_rows`
(true on modern default configs — verified true on 26.7; configs carried over
from older servers ship false, which silently hides ALL rows from unaddressed
principals). The catch-all policy below pins the intended behavior — full hub
visibility for every non-officer principal — independent of that flag, so the
governance layer behaves identically on any stand. Keep the TO ALL EXCEPT list
in sync with the officer roles in 01_roles.sql (pinned by
test_dv2_governance_ddl.py).

Note: bv_customer_mdm__* run SQL SECURITY DEFINER, so these policies do NOT
re-filter the views (the definer reads the hub); each view already pins its
branch in its own WHERE. The policies govern DIRECT hub queries.
Idempotent: IF NOT EXISTS; safe to re-run.
*/

CREATE ROW POLICY IF NOT EXISTS jurisdiction__msk ON rv.hub_customer
    FOR SELECT USING splitByString('__', record_source)[2] = 'msk'
    TO dv2_pii_officer__msk;

CREATE ROW POLICY IF NOT EXISTS jurisdiction__spb ON rv.hub_customer
    FOR SELECT USING splitByString('__', record_source)[2] = 'spb'
    TO dv2_pii_officer__spb;

CREATE ROW POLICY IF NOT EXISTS jurisdiction__ekb ON rv.hub_customer
    FOR SELECT USING splitByString('__', record_source)[2] = 'ekb'
    TO dv2_pii_officer__ekb;

CREATE ROW POLICY IF NOT EXISTS jurisdiction__dxb ON rv.hub_customer
    FOR SELECT USING splitByString('__', record_source)[2] = 'dxb'
    TO dv2_pii_officer__dxb;

CREATE ROW POLICY IF NOT EXISTS jurisdiction__ala ON rv.hub_customer
    FOR SELECT USING splitByString('__', record_source)[2] = 'ala'
    TO dv2_pii_officer__ala;

-- Catch-all: everyone who is not a jurisdiction-scoped officer keeps full hub
-- visibility. Required — see the gotcha in the header.
CREATE ROW POLICY IF NOT EXISTS jurisdiction__all ON rv.hub_customer
    FOR SELECT USING 1
    TO ALL EXCEPT dv2_pii_officer__msk, dv2_pii_officer__spb,
                  dv2_pii_officer__ekb, dv2_pii_officer__dxb,
                  dv2_pii_officer__ala;
