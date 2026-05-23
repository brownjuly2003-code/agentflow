#!/usr/bin/env bash
# DV2.0 multi-branch demo cluster — bootstrap from a clean host.
#
# Prereqs on the host (macOS/Linux):
#   - Docker daemon reachable (e.g. via lima + 'limactl start docker' on macOS)
#   - kind >= 0.30 in PATH
#   - kubectl >= 1.34 in PATH
#   - python3 (for satellite generation)
#
# Re-running is idempotent: existing cluster + DDL are reused via IF NOT EXISTS.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
DV2_SQL="$REPO_ROOT/warehouse/agentflow/dv2"
CLUSTER_NAME="${CLUSTER_NAME:-hq-demo}"

echo "==> Ensuring kind cluster '${CLUSTER_NAME}' exists"
if ! kind get clusters | grep -qx "$CLUSTER_NAME"; then
  kind create cluster --name "$CLUSTER_NAME" --config "$HERE/kind-hq-demo.yaml"
else
  echo "    cluster already exists, skipping create"
fi

echo "==> Waiting for nodes to be Ready"
kubectl wait --for=condition=Ready nodes --all --timeout=180s

echo "==> Applying namespace + workloads"
kubectl apply -f "$HERE/namespace.yaml"
kubectl apply -f "$HERE/secret.example.yaml"
kubectl apply -f "$HERE/clickhouse-sts.yaml"
kubectl apply -f "$HERE/postgres-sts.yaml"

echo "==> Waiting for clickhouse + postgres pods"
kubectl wait --for=condition=Ready pod/clickhouse-0 -n dv2 --timeout=180s
kubectl wait --for=condition=Ready pod/postgres-0 -n dv2 --timeout=180s

echo "==> Generating satellite DDL (idempotent)"
if [[ -d "$DV2_SQL/raw_vault/satellites" ]] && compgen -G "$DV2_SQL/raw_vault/satellites/*.sql" >/dev/null; then
  echo "    satellites already present, skipping generation"
else
  ( cd "$DV2_SQL" && python3 generate_satellites.py --out-dir raw_vault/satellites )
fi

echo "==> Applying DV2.0 DDL to ClickHouse"
ch_exec() {
  kubectl exec -i -n dv2 clickhouse-0 -- \
    clickhouse-client --user default --password demo --multiquery
}

cat "$DV2_SQL/__init.sql" | ch_exec
for f in "$DV2_SQL"/raw_vault/hubs/*.sql; do cat "$f" | ch_exec; done
for f in "$DV2_SQL"/raw_vault/links/*.sql; do cat "$f" | ch_exec; done
for f in "$DV2_SQL"/raw_vault/satellites/*.sql; do cat "$f" | ch_exec; done

if [[ "${SEED:-1}" == "1" ]]; then
  echo "==> Seeding synthetic multi-branch data"
  cat "$DV2_SQL/synthetic_seed.sql" | ch_exec
fi

echo "==> Cluster ready. Quick check:"
kubectl get nodes --show-labels
kubectl get pods,svc,pvc -n dv2
