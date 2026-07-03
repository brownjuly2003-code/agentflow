#!/usr/bin/env bash
# Live adversarial verification of the PostgreSQL vault PII governance
# (ADR 0006 Phase 2 follow-up — PostgreSQL port of ../../governance/verify_live.sh).
# Evidence transcript: docs/perf/vault-pii-governance-pg-verify-2026-07-02.md
#
# Prereqs: a running PostgreSQL with the DV2 vault applied (apply.sh) and
# governance/01..04 applied by a superuser (or the vault owner). Configure the
# client via PSQL (apply.sh convention) — it must connect as that admin:
#   PSQL="psql -h localhost -p 55432 -U agentflow -d agentflow" bash verify_live.sh
# Probe users connect through the same invocation with a trailing -U override.
#
# SEED_DEMO=1 additionally inserts a small deterministic per-branch data set
# (idempotent, ON CONFLICT DO NOTHING) so row-scoping is exercised on an
# otherwise empty stand. On a stand with real data leave it unset: the
# row-policy assertions compare officer-visible counts against admin-side
# per-branch counts, so they hold for any data volume.
#
# Creates four stand-local probe users (password 'probe'): analyst_probe,
# officer_msk_probe, officer_dxb_probe, and noscope_probe (SELECT on the hub
# but addressed by NO row policy — pins PostgreSQL's default-deny). Expected
# result: every line starts with PASS.
set -u
PSQL="${PSQL:-psql}"
ADMIN="$PSQL -v ON_ERROR_STOP=1 -qtA"
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== setup: probe users (stand-local, not part of the governance files) ==="
$ADMIN <<'EOF'
DO $$ BEGIN CREATE ROLE analyst_probe LOGIN PASSWORD 'probe'; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE officer_msk_probe LOGIN PASSWORD 'probe'; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE officer_dxb_probe LOGIN PASSWORD 'probe'; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE noscope_probe LOGIN PASSWORD 'probe'; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
GRANT dv2_analyst TO analyst_probe;
GRANT dv2_pii_officer__msk TO officer_msk_probe;
GRANT dv2_pii_officer__dxb TO officer_dxb_probe;
GRANT USAGE ON SCHEMA rv TO noscope_probe;
GRANT SELECT ON rv.hub_customer TO noscope_probe;
EOF
echo "users ready"

if [ "${SEED_DEMO:-0}" = "1" ]; then
  echo "=== setup: deterministic demo seed (SEED_DEMO=1) ==="
  $ADMIN <<'EOF'
INSERT INTO rv.hub_customer (customer_hk, customer_bk, record_source) VALUES
 (decode(md5('CUST-MSK-1'),'hex'),'CUST-MSK-1','1c__msk'),
 (decode(md5('CUST-MSK-2'),'hex'),'CUST-MSK-2','1c__msk'),
 (decode(md5('CUST-MSK-3'),'hex'),'CUST-MSK-3','1c__msk'),
 (decode(md5('CUST-MSK-4'),'hex'),'CUST-MSK-4','1c__msk'),
 (decode(md5('CUST-MSK-5'),'hex'),'CUST-MSK-5','1c__msk'),
 (decode(md5('CUST-MSK-6'),'hex'),'CUST-MSK-6','1c__msk'),
 (decode(md5('CUST-MSK-7'),'hex'),'CUST-MSK-7','pg_ops__msk'),
 (decode(md5('CUST-MSK-8'),'hex'),'CUST-MSK-8','mp__msk'),
 (decode(md5('CUST-DXB-1'),'hex'),'CUST-DXB-1','1c__dxb'),
 (decode(md5('CUST-DXB-2'),'hex'),'CUST-DXB-2','1c__dxb')
ON CONFLICT (customer_hk) DO NOTHING;
INSERT INTO rv.sat_customer_personal__1c__msk (customer_hk, load_ts, hash_diff, first_name, last_name, email, phone, birth_date) VALUES
 (decode(md5('CUST-MSK-1'),'hex'),'2026-07-01 10:00:00',decode(md5('p1'),'hex'),'Ivan','Petrov','ivan.petrov@example.com','+7-900-000-01-01','1990-03-14'),
 (decode(md5('CUST-MSK-2'),'hex'),'2026-07-01 10:00:00',decode(md5('p2'),'hex'),'Anna','Sidorova','anna.sidorova@example.com','+7-900-000-02-02','1985-11-02')
ON CONFLICT (customer_hk, load_ts) DO NOTHING;
INSERT INTO rv.sat_customer_personal__1c__dxb (customer_hk, load_ts, hash_diff, first_name, last_name, email, phone, birth_date) VALUES
 (decode(md5('CUST-DXB-1'),'hex'),'2026-07-01 10:00:00',decode(md5('p3'),'hex'),'Omar','Haddad','omar.haddad@example.ae','+971-50-000-00-01','1992-06-20')
ON CONFLICT (customer_hk, load_ts) DO NOTHING;
INSERT INTO rv.sat_customer_loyalty__bitrix__msk (customer_hk, load_ts, hash_diff, loyalty_segment, loyalty_points, last_visit_at) VALUES
 (decode(md5('CUST-MSK-1'),'hex'),'2026-07-01 11:00:00',decode(md5('l1'),'hex'),'gold',1250.00,'2026-06-30 18:45:00'),
 (decode(md5('CUST-MSK-2'),'hex'),'2026-07-01 11:00:00',decode(md5('l2'),'hex'),'silver',430.50,'2026-06-28 12:10:00')
ON CONFLICT (customer_hk, load_ts) DO NOTHING;
EOF
  echo "seed applied"
fi

probe() { # probe <label> <expect:OK|DENY> <user|admin> <query>
  local label="$1" expect="$2" user="$3" query="$4"
  local out rc
  if [ "$user" = "admin" ]; then
    out=$($PSQL -qtA -c "$query" 2>&1); rc=$?
  else
    out=$(PGPASSWORD=probe $PSQL -qtA -U "$user" -c "$query" 2>&1); rc=$?
  fi
  if [ "$expect" = "OK" ]; then
    if [ $rc -eq 0 ]; then echo "PASS  [$label] -> $(echo "$out" | head -2 | tr '\n' ' | ')"
    else echo "FAIL  [$label] expected OK, got rc=$rc: $(echo "$out" | grep -m1 'ERROR')"; fi
  else
    if [ $rc -ne 0 ] && echo "$out" | grep -q "permission denied"; then
      echo "PASS  [$label] -> permission denied"
    elif [ $rc -ne 0 ]; then echo "WARN  [$label] denied but unexpected error: $(echo "$out" | grep -m1 'ERROR')"
    else echo "FAIL  [$label] expected DENY, query SUCCEEDED: $(echo "$out" | head -1)"; fi
  fi
}

count_as() { # count_as <user|admin> <query> -> stdout number (empty on error)
  if [ "$1" = "admin" ]; then $PSQL -qtA -c "$2" 2>/dev/null
  else PGPASSWORD=probe $PSQL -qtA -U "$1" -c "$2" 2>/dev/null; fi
}

echo
echo "=== dv2_analyst: non-PII access works (owner-rights views, column grants) ==="
probe "analyst explicit non-PII projection" OK analyst_probe \
  "SELECT customer_bk, branch, loyalty_segment FROM rv.bv_customer_mdm__msk ORDER BY customer_bk LIMIT 2"
probe "analyst bare count(*)" OK analyst_probe \
  "SELECT count(*) FROM rv.bv_customer_mdm__msk"
probe "analyst aggregate over granted column" OK analyst_probe \
  "SELECT count(customer_hk), sum(loyalty_points) FROM rv.bv_customer_mdm__msk"
probe "analyst GROUP BY + HAVING on granted columns" OK analyst_probe \
  "SELECT loyalty_segment, count(customer_hk) AS c FROM rv.bv_customer_mdm__msk GROUP BY loyalty_segment HAVING count(customer_hk) > 0 ORDER BY c DESC LIMIT 2"
probe "analyst WHERE on passthrough column (customer_bk)" OK analyst_probe \
  "SELECT customer_bk FROM rv.bv_customer_mdm__msk WHERE customer_bk LIKE 'CUST-%' ORDER BY customer_bk LIMIT 1"
probe "analyst filter on view-derived column (CH limitation absent on PG)" OK analyst_probe \
  "SELECT count(*) FILTER (WHERE loyalty_segment = 'gold') FROM rv.bv_customer_mdm__msk"
probe "analyst hub_customer full visibility (jurisdiction__all policy)" OK analyst_probe \
  "SELECT count(*) FROM rv.hub_customer"
probe "analyst granted satellite (loyalty)" OK analyst_probe \
  "SELECT count(*) FROM rv.sat_customer_loyalty__bitrix__msk"

echo
echo "=== dv2_analyst: PII columns are engine-denied in EVERY shape ==="
probe "analyst plain PII column" DENY analyst_probe \
  "SELECT email FROM rv.bv_customer_mdm__msk LIMIT 1"
probe "analyst SELECT *" DENY analyst_probe \
  "SELECT * FROM rv.bv_customer_mdm__msk LIMIT 1"
probe "analyst bypass #1: whole-row ref" DENY analyst_probe \
  "SELECT t FROM rv.bv_customer_mdm__msk AS t LIMIT 1"
probe "analyst bypass #2: to_jsonb(whole row)" DENY analyst_probe \
  "SELECT to_jsonb(t) FROM rv.bv_customer_mdm__msk AS t LIMIT 1"
probe "analyst bypass #3: positional rename-list (expressible on PG)" DENY analyst_probe \
  "SELECT d FROM rv.bv_customer_mdm__msk AS t(a,b,c,d,e,f,g,h,i,j,k,l,m,n) LIMIT 1"
probe "analyst PII inside expression" DENY analyst_probe \
  "SELECT upper(email) FROM rv.bv_customer_mdm__msk LIMIT 1"
probe "analyst PII in WHERE only" DENY analyst_probe \
  "SELECT customer_bk FROM rv.bv_customer_mdm__msk WHERE email LIKE '%@%' LIMIT 1"
probe "analyst PII via subquery" DENY analyst_probe \
  "SELECT count(*) FROM (SELECT email FROM rv.bv_customer_mdm__msk) s"
probe "analyst raw personal satellite" DENY analyst_probe \
  "SELECT count(*) FROM rv.sat_customer_personal__1c__msk"
probe "analyst employee profile (name PII)" DENY analyst_probe \
  "SELECT count(*) FROM rv.sat_employee_profile__1c_zup__msk"

echo
echo "=== officers: PII bounded to own jurisdiction ==="
probe "officer_msk reads own-branch PII" OK officer_msk_probe \
  "SELECT first_name, email FROM rv.bv_customer_mdm__msk ORDER BY customer_bk LIMIT 1"
probe "officer_msk filtered aggregate (full view grant)" OK officer_msk_probe \
  "SELECT count(*) FILTER (WHERE loyalty_segment <> '') FROM rv.bv_customer_mdm__msk"
probe "officer_msk reads own personal satellite" OK officer_msk_probe \
  "SELECT count(*) FROM rv.sat_customer_personal__1c__msk"
probe "officer_msk cross-branch view denied" DENY officer_msk_probe \
  "SELECT email FROM rv.bv_customer_mdm__dxb LIMIT 1"
probe "officer_msk cross-branch satellite denied" DENY officer_msk_probe \
  "SELECT count(*) FROM rv.sat_customer_personal__1c__dxb"

msk_expected=$(count_as admin "SELECT count(*) FROM rv.hub_customer WHERE split_part(record_source,'__',2)='msk'")
dxb_expected=$(count_as admin "SELECT count(*) FROM rv.hub_customer WHERE split_part(record_source,'__',2)='dxb'")
msk_seen=$(count_as officer_msk_probe "SELECT count(*) FROM rv.hub_customer")
dxb_seen=$(count_as officer_dxb_probe "SELECT count(*) FROM rv.hub_customer")
dxb_sees_msk=$(count_as officer_dxb_probe "SELECT count(*) FILTER (WHERE split_part(record_source,'__',2)='msk') FROM rv.hub_customer")
if [ -n "$msk_seen" ] && [ "$msk_seen" = "$msk_expected" ]; then
  echo "PASS  [officer_msk hub row-scoped] -> sees $msk_seen of $msk_expected msk rows"
else echo "FAIL  [officer_msk hub row-scoped] sees '$msk_seen', admin counts $msk_expected msk rows"; fi
if [ -n "$dxb_seen" ] && [ "$dxb_seen" = "$dxb_expected" ]; then
  echo "PASS  [officer_dxb hub row-scoped] -> sees $dxb_seen of $dxb_expected dxb rows"
else echo "FAIL  [officer_dxb hub row-scoped] sees '$dxb_seen', admin counts $dxb_expected dxb rows"; fi
if [ "$dxb_sees_msk" = "0" ]; then
  echo "PASS  [officer_dxb sees zero msk rows via hub filter] -> 0"
else echo "FAIL  [officer_dxb sees zero msk rows via hub filter] -> '$dxb_sees_msk'"; fi

echo
echo "=== PostgreSQL default-deny: principal addressed by NO row policy ==="
noscope_seen=$(count_as noscope_probe "SELECT count(*) FROM rv.hub_customer")
if [ "$noscope_seen" = "0" ]; then
  echo "PASS  [noscope_probe (SELECT granted, no policy) sees zero hub rows] -> 0"
else echo "FAIL  [noscope_probe (SELECT granted, no policy)] -> '$noscope_seen' (expected 0)"; fi

echo
echo "=== admin (owner) unaffected: ENABLE (not FORCE) row level security ==="
probe "admin hub full visibility (owner bypasses RLS)" OK admin \
  "SELECT count(*) FROM rv.hub_customer"
probe "admin reads PII" OK admin \
  "SELECT email FROM rv.bv_customer_mdm__msk ORDER BY customer_bk LIMIT 1"

echo
echo "=== governance files re-apply cleanly (idempotency) ==="
for f in "$DIR"/01_roles.sql "$DIR"/02_grants_analyst.sql \
         "$DIR"/03_grants_pii_officers.sql "$DIR"/04_row_policies.sql; do
  if $PSQL -v ON_ERROR_STOP=1 -q -f "$f" >/dev/null 2>&1; then
    echo "PASS  [re-apply $(basename "$f")]"
  else echo "FAIL  [re-apply $(basename "$f")]"; fi
done

echo
echo "Done. Every line above should be PASS (officer hub counts must equal the"
echo "admin-side per-branch counts; cross-branch and no-policy counts must be 0)."
