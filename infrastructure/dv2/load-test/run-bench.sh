#!/usr/bin/env bash
# DV2.0 ClickHouse load test — runs inside the clickhouse-server image as a
# Kubernetes Job. Sweeps a set of analytical scenarios over a range of client
# concurrency levels using `clickhouse-benchmark`, parses the text report, and
# gates p99 against per-class budgets.
#
# Scenario classes (by filename):
#   *point*  -> point-lookup budget     (P99_MS_POINT, default 200 ms)
#   *adhoc*  -> raw-vault ad-hoc budget  (P99_MS_ADHOC, default 2000 ms)
#   *        -> heavy/analytical budget  (P99_MS_HEAVY, default 1000 ms)
#
# The *adhoc* scenario runs against rv.bv_order_canonical, which recomputes the
# full Data Vault business view on every call (UNION ALL across 5 branches +
# argMax SCD2 collapse + 5 LEFT JOINs). That recompute is sub-second at low
# concurrency but degrades as parallel clients pile up on 2 vCPU -- which is the
# whole reason the serving path is the materialized mart (06_branch_pnl_mart),
# not the live view. The load test exists to make that boundary measurable.
set -uo pipefail

HOST=${CH_HOST:-clickhouse}
PORT=${CH_PORT:-9000}
USER=${CH_USER:-default}
PASS=${CH_PASSWORD:-demo}
LEVELS=${CONCURRENCY_LEVELS:-1 4 8}
ITER=${ITERATIONS:-60}
ITER_ADHOC=${ITERATIONS_ADHOC:-2}
QDIR=${QUERY_DIR:-/work}
P99_HEAVY=${P99_MS_HEAVY:-1000}
P99_POINT=${P99_MS_POINT:-200}
P99_ADHOC=${P99_MS_ADHOC:-2000}

echo "DV2 ClickHouse load test"
echo "target=${HOST}:${PORT}  levels=[${LEVELS}]  iterations/level=${ITER}"
echo "budgets: heavy p99<=${P99_HEAVY}ms  point p99<=${P99_POINT}ms  adhoc p99<=${P99_ADHOC}ms"
echo

fail=0
printf '%-24s %-5s %10s %9s %9s %9s   %s\n' SCENARIO CONC QPS p50_ms p90_ms p99_ms VERDICT
printf '%.0s-' $(seq 1 86); echo

for f in $(ls "$QDIR"/*.sql 2>/dev/null | sort); do
  name=$(basename "$f" .sql)
  # gating=1 -> a budget breach fails the whole run (serving SLO paths).
  # gating=0 -> informational only: reported but never fails the run. The
  # raw-vault live-view recompute is a capacity reference, not an SLO — its
  # serving counterpart is the materialized mart (06_branch_pnl_mart).
  gating=1
  levels=$LEVELS
  iter=$ITER
  case "$name" in
    *point*) budget=$P99_POINT ;;
    # At large raw-vault volumes a single live-view recompute can run for
    # minutes on the 2-vCPU demo host — adhoc scenarios therefore sweep
    # c=1 only, with their own (small) iteration count.
    *adhoc*) budget=$P99_ADHOC; gating=0; levels=1; iter=$ITER_ADHOC ;;
    *)       budget=$P99_HEAVY ;;
  esac
  for c in $levels; do
    out=$(clickhouse-benchmark --host "$HOST" --port "$PORT" --user "$USER" \
          --password "$PASS" -c "$c" -i "$iter" -d 0 < "$f" 2>&1)
    if echo "$out" | grep -qiE 'exception|DB::'; then
      if [ "$gating" -eq 1 ]; then ev="ERROR"; fail=1; else ev="INFO-ERR"; fi
      printf '%-24s %-5s %10s %9s %9s %9s   %s\n' "$name" "$c" "-" "-" "-" "-" "$ev"
      echo "$out" | grep -iE 'exception|DB::' | head -1
      continue
    fi
    qps=$(echo "$out" | grep -oE 'QPS: [0-9.]+' | tail -1 | awk '{print $2}')
    p50=$(echo "$out" | awk '/^50%/   {v=$2} END{print v+0}')
    p90=$(echo "$out" | awk '/^90%/   {v=$2} END{print v+0}')
    p99=$(echo "$out" | awk '/^99%/   {v=$2} END{print v+0}')
    p50ms=$(awk "BEGIN{printf \"%.0f\", $p50*1000}")
    p90ms=$(awk "BEGIN{printf \"%.0f\", $p90*1000}")
    p99ms=$(awk "BEGIN{printf \"%.0f\", $p99*1000}")
    verdict=PASS
    if [ "$p99ms" -gt "$budget" ]; then
      if [ "$gating" -eq 1 ]; then verdict="FAIL(>${budget})"; fail=1; else verdict="INFO(>${budget})"; fi
    fi
    printf '%-24s %-5s %10s %9s %9s %9s   %s\n' \
      "$name" "$c" "${qps:-?}" "$p50ms" "$p90ms" "$p99ms" "$verdict"
  done
done

printf '%.0s-' $(seq 1 86); echo
if [ "$fail" -ne 0 ]; then
  echo "LOAD TEST: FAIL"
  exit 1
fi
echo "LOAD TEST: PASS"
