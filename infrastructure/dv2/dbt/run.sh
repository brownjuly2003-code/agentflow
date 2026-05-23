#!/usr/bin/env bash
# Packages the dbt project into a ConfigMap and submits the dbt-run-marts Job.
# Idempotent: rebuilds the ConfigMap from the latest files and replaces the
# Job (any prior run is deleted first).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")"/../../.. && pwd)"
DBT_DIR="${REPO_ROOT}/warehouse/agentflow/dv2/dbt"
INFRA_DIR="${REPO_ROOT}/infrastructure/dv2/dbt"

echo "==> staging tarball from ${DBT_DIR}"
TMP_TAR=$(mktemp -t dbt-project.XXXX.tar.gz)
trap 'rm -f "$TMP_TAR"' EXIT
tar -C "$DBT_DIR" -czf "$TMP_TAR" \
  dbt_project.yml \
  profiles.example.yml \
  models \
  README.md

echo "==> creating/updating ConfigMap dbt-project (key: project.tar.gz)"
kubectl create configmap dbt-project -n dv2 \
  --from-file=project.tar.gz="$TMP_TAR" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "==> (re)submitting Job"
kubectl delete job dbt-run-marts -n dv2 --ignore-not-found
kubectl apply -f "${INFRA_DIR}/dbt-run-job.yaml"

echo
echo "==> follow logs:"
echo "    kubectl logs -n dv2 -f job/dbt-run-marts"
