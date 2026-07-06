#!/usr/bin/env bash
# Staged loader for rv.bv_order_canonical_mat (plan B of an at-scale dbt OOM
# from a retired at-scale capture — see git history of
# docs/dv2-multi-branch/load-test-baseline.md).
# Per branch, the canonical-order SELECT
# is decomposed into SERIAL stage queries, each materializing one small
# MergeTree helper table (pure GROUP BY, disk-spillable, no joins), and a
# final streaming merge join (`full_sorting_merge`) over the pre-sorted
# helpers. Nothing ever holds the full working set in memory.
#
# Why not one INSERT SELECT per branch (even hash-sliced): all CTE stages of
# a single query execute CONCURRENTLY, so their aggregation states, join
# tables and IN-sets stack; with partial_merge joins the allocator churn then
# drives REAL RSS to ~1.7x the tracked bytes. On the 8 GB demo host that
# produced three distinct MEMORY_LIMIT_EXCEEDED modes (2026-06-06):
#   1. default hash joins -> genuine 4.5 GiB concurrent peak;
#   2. jemalloc retention between queries -> RSS-corrected tracker starves
#      the next query (fixed: SYSTEM JEMALLOC PURGE between statements);
#   3. partial_merge block churn -> 4.35 GiB real RSS from a 0.5M-key slice.
# Serial stages + a merge join over sorted tables avoid all three.
#
# The SELECT mirrors rv.bv_order_canonical exactly, but pinned to one branch:
# satellites are addressed per-branch (sat_order_header__{bitrix,1c}__<b>),
# link aggregations are pre-filtered by the branch's hub keys.
#
# Branch = partition: a failed/partial branch is wiped with DROP PARTITION
# and re-run; completed branches are never touched. Safe to re-run per branch.
#
# Usage: ./load_bv_order_canonical_mat.sh [branch ...]   # default: all 5
# Runs wherever kubectl can reach the dv2 namespace (the demo iMac), or
# falls back to ssh'ing the iMac from the Windows workstation.
set -euo pipefail

BRANCHES=("$@")
[ ${#BRANCHES[@]} -eq 0 ] && BRANCHES=(msk spb ekb dxb ala)

ch() {  # pipe stdin SQL into the cluster clickhouse-client
  if command -v kubectl >/dev/null 2>&1; then
    kubectl exec -i -n dv2 clickhouse-0 -- \
      clickhouse-client --user default --password demo --multiquery
  else
    ssh <user>@<mac-host> 'export PATH=$HOME/lima/bin:$HOME/bin:$PATH; \
      kubectl exec -i -n dv2 clickhouse-0 -- \
      clickhouse-client --user default --password demo --multiquery'
  fi
}

# jemalloc retains freed arenas; without a purge the RSS-corrected server
# tracker starves the next statement (observed on the slice-based loader).
purge() { echo "SYSTEM JEMALLOC PURGE;" | ch; sleep 5; }

kc() {  # kubectl, local or via the iMac
  if command -v kubectl >/dev/null 2>&1; then kubectl "$@"; else
    ssh <user>@<mac-host> "export PATH=\$HOME/lima/bin:\$HOME/bin:\$PATH; kubectl $*"
  fi
}

# Even with honest RSS (MALLOC_CONF muzzy_decay_ms:0) and a live tracker
# correction (memory_worker_period_ms=100), the server accumulates transient
# resident spikes across consecutive spill-heavy queries that no single knob
# fully eliminated across seven instrumented runs — while a freshly booted
# server handles each stage comfortably (every stage query peaks <= 0.9 GiB
# tracked). So isolate branches at the process level: bounce the pod, let
# startup activity settle, and retry the whole (idempotent) branch once if
# the memory governor still objects.
fresh_server() {
  echo "[$(date '+%F %T')] restarting clickhouse-0 for a pristine server"
  # --wait=true: block until the OLD pod is fully gone. With --wait=false the
  # 30s graceful-termination window meant `SELECT 1` (and then the stage
  # queries) were answered by the TERMINATING server — runs 10/11 failed with
  # nonsense 4.5 GiB memory readings from a shutting-down process while the
  # same queries passed on the genuinely new pod.
  kc delete pod clickhouse-0 -n dv2 --wait=true >/dev/null
  until kc wait --for=condition=Ready pod/clickhouse-0 -n dv2 --timeout=10s >/dev/null 2>&1; do
    sleep 5
  done
  until echo "SELECT 1" | ch >/dev/null 2>&1; do sleep 10; done
  # Startup transiently holds GiBs in jemalloc (observed 2026-06-07: tracked
  # 3-4.5 GiB right after boot, decaying to <1 GiB within minutes once
  # startup background work settles and decay purges). A fixed sleep races
  # that decay — wait on the tracker itself, purging to speed it along.
  local i tracked=0
  for i in $(seq 1 60); do
    echo "SYSTEM JEMALLOC PURGE;" | ch >/dev/null 2>&1 || true
    tracked=$(echo "SELECT value FROM system.metrics WHERE metric = 'MemoryTracking'" \
              | ch 2>/dev/null | tr -dc '0-9')
    if [ -n "$tracked" ] && [ "$tracked" -lt 1610612736 ]; then
      echo "[$(date '+%F %T')] server settled: tracked $((tracked / 1048576)) MiB"
      return 0
    fi
    sleep 10
  done
  echo "[$(date '+%F %T')] WARN: tracked still $((tracked / 1048576)) MiB after 10 min — proceeding"
}

# Frugal execution profile shared by every stage query. Spill thresholds sit
# at 768 MiB deliberately: spilling earlier (256 MiB) multiplies fill/spill
# cycles, and that allocator churn — not the tracked bytes — is what pushed
# real RSS past the server cap (jemalloc retains the churned pages; see
# MALLOC_CONF in infrastructure/dv2/clickhouse-sts.yaml for the other half
# of the fix).
FRUGAL="max_threads = 2,
    max_bytes_before_external_group_by = 805306368,
    max_bytes_before_external_sort = 805306368,
    max_memory_usage = 2500000000"

stage_header_sql() {
  local B=$1
  cat <<SQL
DROP TABLE IF EXISTS rv._bvmat_header_${B};
CREATE TABLE rv._bvmat_header_${B} ENGINE = MergeTree ORDER BY order_hk AS
SELECT
    order_hk,
    argMax(order_date, load_ts)    AS order_date,
    argMax(channel, load_ts)       AS channel,
    argMax(order_status, load_ts)  AS order_status,
    argMax(total_amount, load_ts)  AS total_amount
FROM (
    SELECT order_hk, order_date, channel, order_status, total_amount, load_ts
    FROM rv.sat_order_header__bitrix__${B} WHERE is_deleted = 0
    UNION ALL
    SELECT order_hk, order_date, channel, order_status, total_amount, load_ts
    FROM rv.sat_order_header__1c__${B} WHERE is_deleted = 0
)
GROUP BY order_hk
SETTINGS ${FRUGAL};
SQL
}

stage_pricing_sql() {
  local B=$1
  cat <<SQL
DROP TABLE IF EXISTS rv._bvmat_pricing_${B};
CREATE TABLE rv._bvmat_pricing_${B} ENGINE = MergeTree ORDER BY order_hk AS
SELECT
    order_hk,
    argMax(subtotal_amount, load_ts)  AS subtotal_amount,
    argMax(discount_amount, load_ts)  AS discount_amount,
    argMax(tax_amount, load_ts)       AS tax_amount,
    argMax(shipping_cost, load_ts)    AS shipping_cost
FROM rv.sat_order_pricing__1c__${B}
WHERE is_deleted = 0
GROUP BY order_hk
SETTINGS ${FRUGAL};
SQL
}

stage_customer_sql() {
  local B=$1
  cat <<SQL
DROP TABLE IF EXISTS rv._bvmat_customer_${B};
CREATE TABLE rv._bvmat_customer_${B} ENGINE = MergeTree ORDER BY order_hk AS
SELECT order_hk, argMax(customer_hk, load_ts) AS customer_hk
FROM rv.lnk_order_customer
WHERE order_hk IN (
    SELECT order_hk FROM rv.hub_order
    WHERE splitByString('__', record_source)[2] = '${B}')
GROUP BY order_hk
SETTINGS ${FRUGAL};
SQL
}

stage_store_sql() {
  local B=$1
  cat <<SQL
DROP TABLE IF EXISTS rv._bvmat_store_${B};
CREATE TABLE rv._bvmat_store_${B} ENGINE = MergeTree ORDER BY order_hk AS
SELECT order_hk, argMax(store_hk, load_ts) AS store_hk
FROM rv.lnk_order_store
WHERE order_hk IN (
    SELECT order_hk FROM rv.hub_order
    WHERE splitByString('__', record_source)[2] = '${B}')
GROUP BY order_hk
SETTINGS ${FRUGAL};
SQL
}

final_insert_sql() {  # streaming merge join over the sorted helpers
  local B=$1
  cat <<SQL
INSERT INTO rv.bv_order_canonical_mat
    (order_hk, order_bk, branch, customer_hk, store_hk,
     order_date, channel, order_status, total_amount,
     subtotal_amount, discount_amount, tax_amount, shipping_cost,
     wb_status, wb_commission, wb_return_window_until,
     header_source, pricing_source, marketplace_source)
WITH
    order_branch AS (
        -- DISTINCT: hub_order is ReplacingMergeTree; dupes may linger until
        -- merges converge. Keeps mat counts logical regardless of merge state.
        SELECT DISTINCT order_hk, order_bk, '${B}' AS branch
        FROM rv.hub_order
        WHERE splitByString('__', record_source)[2] = '${B}'
    ),
    marketplace AS (
        -- msk-only WB satellite (10K rows), same LEFT JOIN for every branch
        -- as the view.
        SELECT
            order_hk,
            argMax(wb_status, load_ts)           AS wb_status,
            argMax(wb_commission, load_ts)       AS wb_commission,
            argMax(return_window_until, load_ts) AS wb_return_window_until
        FROM rv.sat_order_marketplace__wb__msk
        WHERE is_deleted = 0
        GROUP BY order_hk
    )
SELECT
    o.order_hk           AS order_hk,
    o.order_bk           AS order_bk,
    o.branch             AS branch,
    oc.customer_hk       AS customer_hk,
    os.store_hk          AS store_hk,
    h.order_date         AS order_date,
    h.channel            AS channel,
    h.order_status       AS order_status,
    h.total_amount       AS total_amount,
    p.subtotal_amount    AS subtotal_amount,
    p.discount_amount    AS discount_amount,
    p.tax_amount         AS tax_amount,
    p.shipping_cost      AS shipping_cost,
    m.wb_status          AS wb_status,
    m.wb_commission      AS wb_commission,
    m.wb_return_window_until AS wb_return_window_until,
    if(h.order_hk != toFixedString('', 16), concat('bitrix__', o.branch), NULL) AS header_source,
    if(p.order_hk != toFixedString('', 16), concat('1c__', o.branch), NULL)     AS pricing_source,
    if(m.order_hk != toFixedString('', 16), 'wb__msk', NULL)                    AS marketplace_source
FROM order_branch o
LEFT JOIN rv._bvmat_header_${B}   h  ON o.order_hk = h.order_hk
LEFT JOIN rv._bvmat_pricing_${B}  p  ON o.order_hk = p.order_hk
LEFT JOIN marketplace             m  ON o.order_hk = m.order_hk
LEFT JOIN rv._bvmat_customer_${B} oc ON o.order_hk = oc.order_hk
LEFT JOIN rv._bvmat_store_${B}    os ON o.order_hk = os.order_hk
SETTINGS
    join_algorithm = 'full_sorting_merge',
    ${FRUGAL}
SQL
}

drop_stage_sql() {
  local B=$1
  cat <<SQL
DROP TABLE IF EXISTS rv._bvmat_header_${B};
DROP TABLE IF EXISTS rv._bvmat_pricing_${B};
DROP TABLE IF EXISTS rv._bvmat_customer_${B};
DROP TABLE IF EXISTS rv._bvmat_store_${B};
SQL
}

load_branch() {  # one full idempotent branch pass; nonzero on any failure
  local B=$1
  echo "[$(date '+%F %T')] BRANCH ${B}: drop partition (clean retry)" &&
  echo "ALTER TABLE rv.bv_order_canonical_mat DROP PARTITION '${B}';" | ch || return 1
  local stage
  for stage in header pricing customer store; do
    echo "[$(date '+%F %T')] BRANCH ${B}: stage ${stage}"
    "stage_${stage}_sql" "$B" | ch || return 1
    purge || return 1
  done
  echo "[$(date '+%F %T')] BRANCH ${B}: final merge-join INSERT"
  final_insert_sql "$B" | ch || return 1
  purge
  echo "[$(date '+%F %T')] BRANCH ${B}: drop stage tables"
  drop_stage_sql "$B" | ch || return 1
  echo "[$(date '+%F %T')] BRANCH ${B}: DONE"
}

echo "[$(date '+%F %T')] DDL (idempotent)"
ch < "$(dirname "$0")/bv_order_canonical_mat.sql"

for B in "${BRANCHES[@]}"; do
  fresh_server
  if ! load_branch "$B"; then
    echo "[$(date '+%F %T')] BRANCH ${B}: attempt 1 failed — bounce and retry once"
    fresh_server
    if ! load_branch "$B"; then
      echo "[$(date '+%F %T')] BRANCH ${B}: FAILED after retry"
      echo "MAT_LOAD_FAILED branch=${B}"
      exit 1
    fi
  fi
done

echo "[$(date '+%F %T')] verify: per-branch counts + revenue (mat)"
ch <<'SQL'
SELECT branch, count() AS rows, sum(total_amount) AS revenue
FROM rv.bv_order_canonical_mat
GROUP BY branch ORDER BY branch FORMAT TSVWithNames;
SQL
echo "[$(date '+%F %T')] MAT_LOAD_DONE"
