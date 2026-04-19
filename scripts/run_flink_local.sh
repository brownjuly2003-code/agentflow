#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/.." && pwd)"
cd "${repo_root}"

compose_args=(-f docker-compose.yml -f docker-compose.flink.yml)

cleanup() {
  docker compose "${compose_args[@]}" down
}

trap cleanup EXIT

echo "Starting AgentFlow Flink locally via Docker..."
docker compose "${compose_args[@]}" up --build -d flink-job-runner
echo "Flink Web UI: http://localhost:8081"
echo "Following flink-job-runner logs. Press Ctrl+C to stop and tear down the stack."
docker compose "${compose_args[@]}" logs -f flink-job-runner
