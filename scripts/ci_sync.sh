#!/usr/bin/env bash
# One auditable installer for every GitHub Actions Python dependency profile.
#
# Audit F-05: CI jobs used to `pip install -e ".[...]"`, resolving fresh
# ranges on every run while uv.lock pinned a different developer
# environment — a green job could test versions no one develops or ships
# against, and a new upstream release could turn CI red with no repo change.
# Every profile now syncs the exact frozen resolution from uv.lock. Editable
# sub-packages (sdk, integrations) install with --no-deps so their
# dependencies also come from the lock; the root extras mirror them
# (integrations mirrors integrations/pyproject.toml, including [mcp]).
#
# Usage: bash scripts/ci_sync.sh <profile>
#
# The uv pin below must stay in lockstep with the lock-check job in
# .github/workflows/ci.yml: a different uv may rewrite the lock format.
set -euo pipefail

profile="${1:?usage: ci_sync.sh <profile>}"
uv_pin="uv==0.8.23"

# Profile names come from [tool.agentflow.dependency-profiles] in
# pyproject.toml; tests/unit/test_contract_dependencies.py checks both that
# every workflow job calls the profile the contract declares for it and that
# the extras/editables below match the contract's editable-installs. The
# "./integrations[mcp]" contract entry maps to the root `integrations` extra
# (which mirrors the mcp pin into uv.lock) plus an editable --no-deps
# install of ./integrations.
extras=()
editables=()
case "$profile" in
  runtime)           ;;
  dev-tools)         extras=(dev) ;;
  test)              extras=(dev cloud) ;;
  test-sdk)          extras=(dev cloud postgres); editables=(sdk) ;;
  test-integrations) extras=(dev cloud integrations); editables=(sdk integrations) ;;
  load)              extras=(load cloud) ;;
  perf)              extras=(dev load cloud) ;;
  contract)          extras=(dev cloud contract); editables=(sdk) ;;
  e2e)               extras=(dev); editables=(sdk) ;;
  *)
    echo "ci_sync.sh: unknown profile '$profile'" >&2
    exit 2
    ;;
esac

python -m pip install --quiet "$uv_pin"

args=()
for extra in "${extras[@]}"; do
  args+=(--extra "$extra")
done
uv sync --frozen "${args[@]}"

for pkg in "${editables[@]}"; do
  uv pip install --no-deps --editable "./$pkg"
done

# Later workflow steps invoke python/pytest/ruff directly; put the synced
# venv first on PATH for the rest of the job.
if [ -n "${GITHUB_PATH:-}" ]; then
  echo "$PWD/.venv/bin" >> "$GITHUB_PATH"
fi
