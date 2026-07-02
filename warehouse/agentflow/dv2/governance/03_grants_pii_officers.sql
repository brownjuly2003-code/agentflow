/*
Purpose: Per-jurisdiction grants for the dv2_pii_officer__<branch> roles.
Layer:   Governance (ADR 0006 Phase 2).
Model:   An officer stewards contact PII of exactly ONE branch:
         - full columns on the branch's own bv_customer_mdm view (incl. PII);
         - the branch's own personal satellite (raw PII they steward);
         - hub_customer for direct key lookups — row-scoped to the branch by
           04_row_policies.sql, so a DXB officer never sees MSK customer keys.
         No grants on any other branch's view or satellite: cross-jurisdiction
         PII access fails with ACCESS_DENIED at the engine.
Idempotent: GRANT is additive; safe to re-run.
*/

-- ============ msk ============
GRANT SELECT ON rv.bv_customer_mdm__msk           TO dv2_pii_officer__msk;
GRANT SELECT ON rv.sat_customer_personal__1c__msk TO dv2_pii_officer__msk;
GRANT SELECT ON rv.hub_customer                   TO dv2_pii_officer__msk;

-- ============ spb ============
GRANT SELECT ON rv.bv_customer_mdm__spb           TO dv2_pii_officer__spb;
GRANT SELECT ON rv.sat_customer_personal__1c__spb TO dv2_pii_officer__spb;
GRANT SELECT ON rv.hub_customer                   TO dv2_pii_officer__spb;

-- ============ ekb ============
GRANT SELECT ON rv.bv_customer_mdm__ekb           TO dv2_pii_officer__ekb;
GRANT SELECT ON rv.sat_customer_personal__1c__ekb TO dv2_pii_officer__ekb;
GRANT SELECT ON rv.hub_customer                   TO dv2_pii_officer__ekb;

-- ============ dxb ============
GRANT SELECT ON rv.bv_customer_mdm__dxb           TO dv2_pii_officer__dxb;
GRANT SELECT ON rv.sat_customer_personal__1c__dxb TO dv2_pii_officer__dxb;
GRANT SELECT ON rv.hub_customer                   TO dv2_pii_officer__dxb;

-- ============ ala ============
GRANT SELECT ON rv.bv_customer_mdm__ala           TO dv2_pii_officer__ala;
GRANT SELECT ON rv.sat_customer_personal__1c__ala TO dv2_pii_officer__ala;
GRANT SELECT ON rv.hub_customer                   TO dv2_pii_officer__ala;
