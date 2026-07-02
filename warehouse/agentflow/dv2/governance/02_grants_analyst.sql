/*
Purpose: Allow-list grants for dv2_analyst (cross-branch analytics, NO contact PII).
Layer:   Governance (ADR 0006 Phase 2).
Policy:  FAIL-CLOSED. Every readable object is granted here explicitly; a new
         vault object is invisible to analysts until it is classified and added
         (tests/unit/test_dv2_governance_ddl.py enforces that every raw_vault
         satellite is either granted below or listed in the DENIED block).
The engine (ClickHouse access control), not the application, is the boundary:
`SELECT *`, `SELECT COLUMNS('.*')`, whole-row struct refs and positional
column-rename lists over a PII view all fail with ACCESS_DENIED because the PII
columns are simply not granted — there is no SQL shape that reaches them.

DENIED (contact PII — intentionally NO grants for dv2_analyst):
  - sat_customer_personal__1c__msk
  - sat_customer_personal__1c__spb
  - sat_customer_personal__1c__ekb
  - sat_customer_personal__1c__dxb
  - sat_customer_personal__1c__ala
  - sat_employee_profile__1c_zup__msk   (employee first/last name)
Idempotent: GRANT is additive; safe to re-run.
*/

-- ============ Hubs (business keys only — pseudonymous) ============
GRANT SELECT ON rv.hub_customer      TO dv2_analyst;
GRANT SELECT ON rv.hub_employee      TO dv2_analyst;
GRANT SELECT ON rv.hub_marking_code  TO dv2_analyst;
GRANT SELECT ON rv.hub_order         TO dv2_analyst;
GRANT SELECT ON rv.hub_product       TO dv2_analyst;
GRANT SELECT ON rv.hub_shipment      TO dv2_analyst;
GRANT SELECT ON rv.hub_store         TO dv2_analyst;
GRANT SELECT ON rv.hub_supplier      TO dv2_analyst;

-- ============ Links (hash keys only) ============
GRANT SELECT ON rv.lnk_order_customer   TO dv2_analyst;
GRANT SELECT ON rv.lnk_order_employee   TO dv2_analyst;
GRANT SELECT ON rv.lnk_order_product    TO dv2_analyst;
GRANT SELECT ON rv.lnk_order_shipment   TO dv2_analyst;
GRANT SELECT ON rv.lnk_order_store      TO dv2_analyst;
GRANT SELECT ON rv.lnk_product_marking  TO dv2_analyst;
GRANT SELECT ON rv.lnk_product_supplier TO dv2_analyst;
GRANT SELECT ON rv.lnk_shipment_store   TO dv2_analyst;

-- ============ Satellites (non-PII) ============
GRANT SELECT ON rv.sat_customer_anon__1c__ala            TO dv2_analyst;
GRANT SELECT ON rv.sat_customer_anon__1c__dxb            TO dv2_analyst;
GRANT SELECT ON rv.sat_customer_anon__1c__ekb            TO dv2_analyst;
GRANT SELECT ON rv.sat_customer_anon__1c__msk            TO dv2_analyst;
GRANT SELECT ON rv.sat_customer_anon__1c__spb            TO dv2_analyst;
GRANT SELECT ON rv.sat_customer_behavior__site__msk      TO dv2_analyst;
GRANT SELECT ON rv.sat_customer_loyalty__bitrix__ekb     TO dv2_analyst;
GRANT SELECT ON rv.sat_customer_loyalty__bitrix__msk     TO dv2_analyst;
GRANT SELECT ON rv.sat_customer_loyalty__bitrix__spb     TO dv2_analyst;
GRANT SELECT ON rv.sat_employee_sales__bitrix__msk       TO dv2_analyst;
GRANT SELECT ON rv.sat_lnk_order_product__1c__msk        TO dv2_analyst;
GRANT SELECT ON rv.sat_lnk_product_supplier__1c__global  TO dv2_analyst;
GRANT SELECT ON rv.sat_lnk_product_supplier__ref__global TO dv2_analyst;
GRANT SELECT ON rv.sat_marking_code_gs1__1c__global      TO dv2_analyst;
GRANT SELECT ON rv.sat_marking_code_gs1__ref__global     TO dv2_analyst;
GRANT SELECT ON rv.sat_marking_code_wms__wms__global     TO dv2_analyst;
GRANT SELECT ON rv.sat_order_header__1c__ala             TO dv2_analyst;
GRANT SELECT ON rv.sat_order_header__1c__dxb             TO dv2_analyst;
GRANT SELECT ON rv.sat_order_header__1c__ekb             TO dv2_analyst;
GRANT SELECT ON rv.sat_order_header__1c__msk             TO dv2_analyst;
GRANT SELECT ON rv.sat_order_header__1c__spb             TO dv2_analyst;
GRANT SELECT ON rv.sat_order_header__bitrix__ala         TO dv2_analyst;
GRANT SELECT ON rv.sat_order_header__bitrix__dxb         TO dv2_analyst;
GRANT SELECT ON rv.sat_order_header__bitrix__ekb         TO dv2_analyst;
GRANT SELECT ON rv.sat_order_header__bitrix__msk         TO dv2_analyst;
GRANT SELECT ON rv.sat_order_header__bitrix__spb         TO dv2_analyst;
GRANT SELECT ON rv.sat_order_marketplace__wb__msk        TO dv2_analyst;
GRANT SELECT ON rv.sat_order_pricing__1c__ala            TO dv2_analyst;
GRANT SELECT ON rv.sat_order_pricing__1c__dxb            TO dv2_analyst;
GRANT SELECT ON rv.sat_order_pricing__1c__ekb            TO dv2_analyst;
GRANT SELECT ON rv.sat_order_pricing__1c__msk            TO dv2_analyst;
GRANT SELECT ON rv.sat_order_pricing__1c__spb            TO dv2_analyst;
GRANT SELECT ON rv.sat_product_catalog__1c__msk          TO dv2_analyst;
GRANT SELECT ON rv.sat_product_marketplace__wb__msk      TO dv2_analyst;
GRANT SELECT ON rv.sat_product_price__1c__msk            TO dv2_analyst;
GRANT SELECT ON rv.sat_product_reference__ref__global    TO dv2_analyst;
GRANT SELECT ON rv.sat_product_stock__wms__msk           TO dv2_analyst;
GRANT SELECT ON rv.sat_shipment_logistics__wms__msk      TO dv2_analyst;
GRANT SELECT ON rv.sat_shipment_plan__excel__msk         TO dv2_analyst;
GRANT SELECT ON rv.sat_store_master__1c__global          TO dv2_analyst;
GRANT SELECT ON rv.sat_supplier_profile__1c__global      TO dv2_analyst;
GRANT SELECT ON rv.sat_supplier_profile__ref__global     TO dv2_analyst;

-- ============ Business vault ============
-- Customer MDM: column-limited — the five PII columns (first_name, last_name,
-- email, phone, birth_date) are NOT granted. The views run SQL SECURITY DEFINER,
-- so these grants work without exposing the underlying personal satellites.
GRANT SELECT(customer_hk, customer_bk, branch, loyalty_segment, loyalty_points,
             last_visit_at, pii_source, loyalty_source, last_seen_at)
    ON rv.bv_customer_mdm__msk TO dv2_analyst;
GRANT SELECT(customer_hk, customer_bk, branch, loyalty_segment, loyalty_points,
             last_visit_at, pii_source, loyalty_source, last_seen_at)
    ON rv.bv_customer_mdm__spb TO dv2_analyst;
GRANT SELECT(customer_hk, customer_bk, branch, loyalty_segment, loyalty_points,
             last_visit_at, pii_source, loyalty_source, last_seen_at)
    ON rv.bv_customer_mdm__ekb TO dv2_analyst;
GRANT SELECT(customer_hk, customer_bk, branch, loyalty_segment, loyalty_points,
             last_visit_at, pii_source, loyalty_source, last_seen_at)
    ON rv.bv_customer_mdm__dxb TO dv2_analyst;
GRANT SELECT(customer_hk, customer_bk, branch, loyalty_segment, loyalty_points,
             last_visit_at, pii_source, loyalty_source, last_seen_at)
    ON rv.bv_customer_mdm__ala TO dv2_analyst;

GRANT SELECT ON rv.bv_order_canonical     TO dv2_analyst;
GRANT SELECT ON rv.bv_order_canonical_mat TO dv2_analyst;

-- ============ Marts (dbt; PII-free by contract — see dbt/models/marts) ============
GRANT SELECT ON marts.customer_360     TO dv2_analyst;
GRANT SELECT ON marts.branch_pnl       TO dv2_analyst;
GRANT SELECT ON marts.returns_velocity TO dv2_analyst;
