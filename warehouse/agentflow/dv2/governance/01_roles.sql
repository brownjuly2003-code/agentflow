/*
Purpose: DV2 vault access roles (ADR 0006 Phase 2 — engine-enforced PII boundary).
Layer:   Governance (ClickHouse RBAC objects; no data).
Model:
  - dv2_analyst            — cross-branch analytics, NO contact PII anywhere.
                             Explicit allow-list grants (02_grants_analyst.sql);
                             anything not granted is denied by the engine.
  - dv2_pii_officer__<b>   — contact-PII steward for ONE jurisdiction. Full
                             columns on the branch's own bv_customer_mdm view and
                             personal satellite; hub_customer is row-scoped to
                             the branch (04_row_policies.sql). No cross-branch PII.
Users are stand-specific and are NOT created here — create them per deployment
and GRANT one of these roles (see governance/README.md).
Requires: access_management=1 for the applying user (see README).
Idempotent: IF NOT EXISTS everywhere, safe to re-run.
*/
CREATE ROLE IF NOT EXISTS dv2_analyst;

CREATE ROLE IF NOT EXISTS dv2_pii_officer__msk;
CREATE ROLE IF NOT EXISTS dv2_pii_officer__spb;
CREATE ROLE IF NOT EXISTS dv2_pii_officer__ekb;
CREATE ROLE IF NOT EXISTS dv2_pii_officer__dxb;
CREATE ROLE IF NOT EXISTS dv2_pii_officer__ala;
