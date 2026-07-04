#!/usr/bin/env bash
# Live smoke of rv.bv_order_canonical on a running PostgreSQL (G1 Mac smoke).
# Evidence transcript target: docs/perf/bv-order-canonical-pg-smoke-*.md
#
# Prereqs: a running PostgreSQL with the DV2 vault applied (postgres/apply.sh,
# which creates the schema, hubs, links, satellites and the bv_order_canonical
# view). Configure the client via PSQL (apply.sh convention) as the vault owner:
#   PSQL="psql -h localhost -p 55432 -U agentflow -d agentflow" bash verify_bv_order.sh
#
# APPLY=1 additionally runs postgres/apply.sh first (fresh stand).
# The order seed (order_smoke_seed.sql) is idempotent, so re-runs are safe.
#
# Expected result: every line starts with PASS. Expected values are pinned in
# smoke/README.md and derived by hand from order_smoke_seed.sql.
set -u
PSQL="${PSQL:-psql}"
Q="$PSQL -v ON_ERROR_STOP=1 -qtA"
DIR="$(cd "$(dirname "$0")" && pwd)"
PGDIR="$(cd "$DIR/.." && pwd)"

pass=0; fail=0

if [ "${APPLY:-0}" = "1" ]; then
  echo "=== setup: apply.sh (fresh vault) ==="
  PSQL="$PSQL" bash "$PGDIR/apply.sh" >/dev/null && echo "vault applied"
fi

echo "=== setup: order smoke seed (idempotent) ==="
$Q -f "$DIR/order_smoke_seed.sql" >/dev/null && echo "seed applied"
echo

# Scope every aggregate to this smoke's eight orders so the script is also
# correct on a stand that already carries promoted data.
SCOPE="order_bk IN (
 'mp__msk__0000001','mp__msk__0000002','site__msk__0008901','bitrix__msk__0009181',
 'bitrix__spb__0009541','bitrix__ekb__0009721','bitrix__dxb__0009851','bitrix__ala__0009925')"
BV="rv.bv_order_canonical"

assert_eq() { # assert_eq <label> <expected> <query>
  local label="$1" expected="$2" query="$3" got
  got=$($PSQL -qtA -c "$query" 2>&1 | tr -d '\r')
  if [ "$got" = "$expected" ]; then
    echo "PASS  [$label] -> $got"; pass=$((pass+1))
  else
    echo "FAIL  [$label] expected '$expected', got '$got'"; fail=$((fail+1))
  fi
}

echo "=== reconstruction: shape and coverage ==="
assert_eq "row count = 8 canonical orders" "8" \
  "SELECT count(*) FROM $BV WHERE $SCOPE"
assert_eq "branch derivation via split_part (msk 4 + 4 regionals)" "ala:1 dxb:1 ekb:1 msk:4 spb:1" \
  "SELECT string_agg(branch||':'||c,' ' ORDER BY branch) FROM (SELECT branch, count(*) c FROM $BV WHERE $SCOPE GROUP BY branch) s"
assert_eq "no branch escapes the five jurisdictions" "0" \
  "SELECT count(*) FROM $BV WHERE $SCOPE AND branch NOT IN ('msk','spb','ekb','dxb','ala')"
assert_eq "customer + store links all resolved" "8" \
  "SELECT count(*) FILTER (WHERE customer_hk IS NOT NULL AND store_hk IS NOT NULL) FROM $BV WHERE $SCOPE"
assert_eq "total_amount sum (RUB, net of VAT)" "197166.67" \
  "SELECT sum(total_amount) FROM $BV WHERE $SCOPE"

echo
echo "=== SCD2: latest load_ts wins ==="
assert_eq "O2 header collapses across UNION to newest Bitrix version" "shipped|2166.67" \
  "SELECT order_status||'|'||total_amount FROM $BV WHERE order_bk='mp__msk__0000002'"
assert_eq "O2 pricing collapses to newest 1C version" "2166.67|433.33" \
  "SELECT subtotal_amount||'|'||tax_amount FROM $BV WHERE order_bk='mp__msk__0000002'"
assert_eq "O2 marketplace collapses to newest wb version" "delivering" \
  "SELECT wb_status FROM $BV WHERE order_bk='mp__msk__0000002'"
assert_eq "O4 soft-delete tombstone (newer is_deleted=1) does NOT win" "confirmed" \
  "SELECT order_status FROM $BV WHERE order_bk='bitrix__msk__0009181'"

echo
echo "=== conflict policy: source attribution ==="
assert_eq "every order's header_source = bitrix__<branch>" "8" \
  "SELECT count(*) FILTER (WHERE header_source = 'bitrix__'||branch) FROM $BV WHERE $SCOPE"
assert_eq "pricing present for 7 of 8 (O8 ala has none)" "7" \
  "SELECT count(*) FILTER (WHERE pricing_source = '1c__'||branch) FROM $BV WHERE $SCOPE"
assert_eq "O8 pricing LEFT JOIN miss -> NULL pricing" "NULL|NULL" \
  "SELECT coalesce(pricing_source,'NULL')||'|'||coalesce(subtotal_amount::text,'NULL') FROM $BV WHERE order_bk='bitrix__ala__0009925'"

echo
echo "=== marketplace: Wildberries lights up for MSK only ==="
assert_eq "O1 marketplace joined (wb__msk)" "delivered|wb__msk" \
  "SELECT wb_status||'|'||marketplace_source FROM $BV WHERE order_bk='mp__msk__0000001'"
assert_eq "only the 2 msk marketplace orders carry marketplace state" "2" \
  "SELECT count(*) FROM $BV WHERE $SCOPE AND marketplace_source IS NOT NULL"
assert_eq "O3 D2C has no marketplace state" "NULL" \
  "SELECT coalesce(marketplace_source,'NULL') FROM $BV WHERE order_bk='site__msk__0008901'"

echo
echo "=== per-jurisdiction VAT surfaces through pricing ==="
# Integer percent so the assertion does not depend on numeric trailing-zero rendering.
assert_eq "dxb effective VAT rate = 5% (UAE)" "5" \
  "SELECT round(tax_amount/subtotal_amount*100)::int FROM $BV WHERE order_bk='bitrix__dxb__0009851'"
assert_eq "spb effective VAT rate = 20% (RU)" "20" \
  "SELECT round(tax_amount/subtotal_amount*100)::int FROM $BV WHERE order_bk='bitrix__spb__0009541'"

echo
echo "Done. pass=$pass fail=$fail"
[ "$fail" = "0" ]
