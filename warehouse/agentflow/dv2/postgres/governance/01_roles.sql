/*
Purpose: DV2 vault access roles — PostgreSQL port of the ClickHouse governance
         layer (ADR 0006 Phase 2 follow-up; ClickHouse original:
         ../../governance/01_roles.sql).
Layer:   Governance (PostgreSQL roles; no data).
Model:
  - dv2_analyst            — cross-branch analytics, NO contact PII anywhere.
                             Explicit allow-list grants (02_grants_analyst.sql);
                             anything not granted is denied by the engine.
  - dv2_pii_officer__<b>   — contact-PII steward for ONE jurisdiction. Full
                             columns on the branch's own bv_customer_mdm view and
                             personal satellite; hub_customer is row-scoped to
                             the branch (04_row_policies.sql). No cross-branch PII.
Users are stand-specific and are NOT created here — create LOGIN users per
deployment and GRANT one of these roles (see governance/README.md).
PostgreSQL notes:
  - CREATE ROLE has no IF NOT EXISTS; the DO blocks swallow duplicate_object so
    the file stays idempotent (safe to re-run), like the ClickHouse layer.
  - Roles are cluster-wide; the grants in 02/03 are per-database.
  - USAGE on schema rv is a PostgreSQL prerequisite for reaching any object in
    it. USAGE conveys no SELECT by itself, so the allow-list stays fail-closed.
*/

DO $$ BEGIN CREATE ROLE dv2_analyst NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN CREATE ROLE dv2_pii_officer__msk NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE dv2_pii_officer__spb NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE dv2_pii_officer__ekb NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE dv2_pii_officer__dxb NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE dv2_pii_officer__ala NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;

GRANT USAGE ON SCHEMA rv TO dv2_analyst,
    dv2_pii_officer__msk, dv2_pii_officer__spb, dv2_pii_officer__ekb,
    dv2_pii_officer__dxb, dv2_pii_officer__ala;
