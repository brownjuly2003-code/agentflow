#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-agentflow-staging}"
NAMESPACE="${NAMESPACE:-agentflow}"
RELEASE_NAME="${RELEASE_NAME:-agentflow}"

if ! command -v kind >/dev/null 2>&1; then
  echo "Missing required command: kind" >&2
  exit 1
fi

if kind get clusters | grep -qx "$CLUSTER_NAME"; then
  if command -v helm >/dev/null 2>&1; then
    helm uninstall "$RELEASE_NAME" --namespace "$NAMESPACE" --wait >/dev/null 2>&1 || true
  fi
  kind delete cluster --name "$CLUSTER_NAME"
else
  echo "==> kind cluster $CLUSTER_NAME is not running"
fi
