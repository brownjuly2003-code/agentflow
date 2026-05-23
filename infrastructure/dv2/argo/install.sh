#!/usr/bin/env bash
# Idempotent Argo Workflows install for the DV2.0 demo cluster.
# Requires: kubectl context pointing at the `hq-demo` kind cluster
# (or any cluster with `dv2` namespace already created).

set -euo pipefail

ARGO_VERSION="${ARGO_VERSION:-v3.5.10}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> creating argo namespace"
kubectl create namespace argo --dry-run=client -o yaml | kubectl apply -f -

echo "==> installing argo workflows ${ARGO_VERSION}"
kubectl apply -n argo \
  -f "https://github.com/argoproj/argo-workflows/releases/download/${ARGO_VERSION}/install.yaml"

echo "==> waiting for argo deployments to be ready (180s)"
kubectl wait -n argo --for=condition=Available deployment/workflow-controller --timeout=180s
kubectl wait -n argo --for=condition=Available deployment/argo-server         --timeout=180s

echo "==> applying dv2 RBAC + WorkflowTemplate"
kubectl apply -f "${SCRIPT_DIR}/rbac.yaml"
kubectl apply -f "${SCRIPT_DIR}/workflow-template.yaml"

echo "==> done"
echo
echo "Submit a run:"
echo "  kubectl create -n dv2 -f - <<EOF"
echo "  apiVersion: argoproj.io/v1alpha1"
echo "  kind: Workflow"
echo "  metadata:"
echo "    generateName: dv2-refresh-"
echo "  spec:"
echo "    workflowTemplateRef:"
echo "      name: dv2-refresh"
echo "  EOF"
