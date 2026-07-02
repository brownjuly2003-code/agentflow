#!/usr/bin/env bash
# Live adversarial verification of the vault PII governance (ADR 0006 Phase 2).
# Evidence transcript: docs/perf/vault-pii-governance-verify-2026-07-02.md
#
# Prereqs: a running ClickHouse with the DV2 vault applied (raw vault + seeds +
# business_vault views + governance/*.sql) and an admin identity with
# access_management=1. Configure the client via CH_CLIENT, e.g.:
#   CH_CLIENT="clickhouse-client --user default --password demo" bash verify_live.sh
#   CH_CLIENT="$HOME/clickhouse-bin client" bash verify_live.sh        # standalone
#   CH_CLIENT="kubectl exec -i -n dv2 clickhouse-0 -- clickhouse-client --user default --password demo" bash verify_live.sh
#
# Creates three stand-local probe users (analyst_probe / officer_msk_probe /
# officer_dxb_probe, password 'probe') and runs the deny/allow matrix. Expected
# result: every probe line starts with PASS.
set -u
CH="${CH_CLIENT:-clickhouse-client}"

echo "=== setup: probe users (stand-local, not part of the governance files) ==="
$CH --multiquery <<'EOF'
CREATE USER IF NOT EXISTS analyst_probe IDENTIFIED WITH plaintext_password BY 'probe';
CREATE USER IF NOT EXISTS officer_msk_probe IDENTIFIED WITH plaintext_password BY 'probe';
CREATE USER IF NOT EXISTS officer_dxb_probe IDENTIFIED WITH plaintext_password BY 'probe';
GRANT dv2_analyst TO analyst_probe;
GRANT dv2_pii_officer__msk TO officer_msk_probe;
GRANT dv2_pii_officer__dxb TO officer_dxb_probe;
ALTER USER analyst_probe DEFAULT ROLE dv2_analyst;
ALTER USER officer_msk_probe DEFAULT ROLE dv2_pii_officer__msk;
ALTER USER officer_dxb_probe DEFAULT ROLE dv2_pii_officer__dxb;
EOF
echo "users ready"

probe() { # probe <label> <expect:OK|DENY> <user> <query>
  local label="$1" expect="$2" user="$3" query="$4"
  local out rc auth
  if [ "$user" = "admin" ]; then auth=""; else auth="--user $user --password probe"; fi
  out=$($CH $auth -q "$query" 2>&1)
  rc=$?
  if [ "$expect" = "OK" ]; then
    if [ $rc -eq 0 ]; then echo "PASS  [$label] -> $(echo "$out" | head -2 | tr '\n' ' | ')"
    else echo "FAIL  [$label] expected OK, got rc=$rc: $(echo "$out" | grep -m1 'DB::Exception')"; fi
  else
    if [ $rc -ne 0 ] && echo "$out" | grep -q "ACCESS_DENIED"; then
      echo "PASS  [$label] -> ACCESS_DENIED"
    elif [ $rc -ne 0 ] && echo "$out" | grep -q "UNKNOWN_IDENTIFIER"; then
      echo "PASS  [$label] -> UNKNOWN_IDENTIFIER (shape not expressible on ClickHouse)"
    elif [ $rc -ne 0 ]; then echo "WARN  [$label] denied but unexpected error: $(echo "$out" | grep -m1 'DB::Exception')"
    else echo "FAIL  [$label] expected DENY, query SUCCEEDED: $(echo "$out" | head -1)"; fi
  fi
}

echo
echo "=== dv2_analyst: non-PII access works (DEFINER view, column grants) ==="
probe "analyst explicit non-PII projection" OK analyst_probe \
  "SELECT customer_bk, branch, loyalty_segment FROM rv.bv_customer_mdm__msk ORDER BY customer_bk LIMIT 2"
probe "analyst bare count()" OK analyst_probe \
  "SELECT count() FROM rv.bv_customer_mdm__msk"
probe "analyst aggregate over granted column" OK analyst_probe \
  "SELECT count(customer_hk), sum(loyalty_points) FROM rv.bv_customer_mdm__msk"
probe "analyst GROUP BY + HAVING on granted columns" OK analyst_probe \
  "SELECT loyalty_segment, count(customer_hk) AS c FROM rv.bv_customer_mdm__msk GROUP BY loyalty_segment HAVING c > 0 ORDER BY c DESC LIMIT 2"
probe "analyst WHERE on passthrough column (customer_bk)" OK analyst_probe \
  "SELECT customer_bk FROM rv.bv_customer_mdm__msk WHERE customer_bk LIKE 'CUST-%' ORDER BY customer_bk LIMIT 1"
probe "analyst hub_customer full visibility (catch-all row policy)" OK analyst_probe \
  "SELECT count() FROM rv.hub_customer"
probe "analyst granted satellite (loyalty)" OK analyst_probe \
  "SELECT count() FROM rv.sat_customer_loyalty__bitrix__msk"

echo
echo "=== dv2_analyst: PII columns are engine-denied in EVERY shape ==="
probe "analyst plain PII column" DENY analyst_probe \
  "SELECT email FROM rv.bv_customer_mdm__msk LIMIT 1"
probe "analyst SELECT *" DENY analyst_probe \
  "SELECT * FROM rv.bv_customer_mdm__msk LIMIT 1"
probe "analyst bypass #1: COLUMNS('.*') expr" DENY analyst_probe \
  "SELECT COLUMNS('.*') FROM rv.bv_customer_mdm__msk LIMIT 1"
probe "analyst bypass #2: whole-row struct ref" DENY analyst_probe \
  "SELECT t FROM rv.bv_customer_mdm__msk AS t LIMIT 1"
probe "analyst bypass #3: positional rename-list" DENY analyst_probe \
  "SELECT d FROM rv.bv_customer_mdm__msk AS t(a,b,c,d,e,f,g,h,i,j,k,l,m,n) LIMIT 1"
probe "analyst PII inside expression" DENY analyst_probe \
  "SELECT upper(email) FROM rv.bv_customer_mdm__msk LIMIT 1"
probe "analyst PII in WHERE only" DENY analyst_probe \
  "SELECT customer_bk FROM rv.bv_customer_mdm__msk WHERE email LIKE '%@%' LIMIT 1"
probe "analyst raw personal satellite" DENY analyst_probe \
  "SELECT count() FROM rv.sat_customer_personal__1c__msk"
probe "analyst employee profile (name PII)" DENY analyst_probe \
  "SELECT count() FROM rv.sat_employee_profile__1c_zup__msk"

echo
echo "=== known ergonomic limitation: filter pushdown vs column grants ==="
probe "analyst filter on argMax-derived column (raw)" DENY analyst_probe \
  "SELECT countIf(loyalty_segment != '') FROM rv.bv_customer_mdm__msk"
probe "analyst same filter via subquery wrap (PII-safe workaround)" OK analyst_probe \
  "SELECT countIf(loyalty_segment != '') FROM (SELECT loyalty_segment FROM rv.bv_customer_mdm__msk)"
probe "subquery wrap cannot smuggle PII" DENY analyst_probe \
  "SELECT count() FROM (SELECT email FROM rv.bv_customer_mdm__msk) WHERE email LIKE '%@%'"

echo
echo "=== officers: PII bounded to own jurisdiction ==="
probe "officer_msk reads own-branch PII" OK officer_msk_probe \
  "SELECT first_name, email FROM rv.bv_customer_mdm__msk ORDER BY customer_bk LIMIT 1"
probe "officer_msk filtered aggregate (full view grant)" OK officer_msk_probe \
  "SELECT countIf(loyalty_segment != '') FROM rv.bv_customer_mdm__msk"
probe "officer_msk reads own personal satellite" OK officer_msk_probe \
  "SELECT count() FROM rv.sat_customer_personal__1c__msk"
probe "officer_msk cross-branch view denied" DENY officer_msk_probe \
  "SELECT email FROM rv.bv_customer_mdm__dxb LIMIT 1"
probe "officer_msk cross-branch satellite denied" DENY officer_msk_probe \
  "SELECT count() FROM rv.sat_customer_personal__1c__dxb"
probe "officer_msk hub row-scoped (msk rows only)" OK officer_msk_probe \
  "SELECT count() FROM rv.hub_customer"
probe "officer_dxb hub row-scoped (dxb rows only)" OK officer_dxb_probe \
  "SELECT count() FROM rv.hub_customer"
probe "officer_dxb sees zero msk rows via hub filter" OK officer_dxb_probe \
  "SELECT countIf(splitByString('__', record_source)[2] = 'msk') FROM rv.hub_customer"

echo
echo "=== admin unaffected ==="
probe "admin hub full visibility (catch-all)" OK admin \
  "SELECT count() FROM rv.hub_customer"
probe "admin reads PII" OK admin \
  "SELECT email FROM rv.bv_customer_mdm__msk ORDER BY customer_bk LIMIT 1"

echo
echo "Done. Every line above should be PASS (officer hub counts must equal the"
echo "branch's own hub_customer row count; cross-branch countIf must be 0)."
