#!/usr/bin/env bash
# Apply and run the DV2 ClickHouse load test as a Kubernetes Job.
# Run from a machine with kubectl pointed at the hq-demo cluster.
#
#   bash infrastructure/dv2/load-test/apply.sh
#
# Re-runnable: recreates the ConfigMap from local files and the Job each time.
set -euo pipefail
NS=dv2
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==> (re)creating ConfigMap dv2-load-test (script + ${DIR}/queries/*.sql)"
kubectl -n "$NS" create configmap dv2-load-test \
  --from-file="$DIR/run-bench.sh" \
  --from-file="$DIR/queries" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "==> (re)creating Job dv2-load-test"
kubectl -n "$NS" delete job dv2-load-test --ignore-not-found --wait=true
kubectl -n "$NS" apply -f "$DIR/job.yaml"

echo "==> waiting for Job to finish (timeout 600s)"
kubectl -n "$NS" wait --for=condition=complete --timeout=600s job/dv2-load-test 2>/dev/null \
  || kubectl -n "$NS" wait --for=condition=failed --timeout=5s job/dv2-load-test 2>/dev/null || true

echo "==> Job output:"
kubectl -n "$NS" logs job/dv2-load-test
