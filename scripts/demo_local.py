"""Run the AgentFlow demo locally with DuckDB and no Docker services."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def build_environment(
    db_path: Path,
    *,
    base_environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return a child environment pinned to the no-Docker demo profile."""
    environment = dict(os.environ if base_environment is None else base_environment)
    for external_setting in (
        "AGENTFLOW_CONTROLPLANE_PG_DSN",
        "AGENTFLOW_NODE_BRANCH",
        "AGENTFLOW_NODE_CENTER_URL",
        "AGENTFLOW_NODE_TOKEN",
        "AGENTFLOW_ICEBERG_CONFIG",
        "KAFKA_BOOTSTRAP_SERVERS",
        "FLINK_JOBMANAGER_URL",
        "REDIS_URL",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
    ):
        environment.pop(external_setting, None)
    environment.update(
        {
            "SERVING_BACKEND": "duckdb",
            "DUCKDB_PATH": str(db_path.resolve()),
            "AGENTFLOW_AUTH_DISABLED": "true",
            "AGENTFLOW_LOCAL_ONLY": "true",
            "AGENTFLOW_PROFILE": "dev",
            "AGENTFLOW_DEMO_MODE": "false",
            "AGENTFLOW_SEED_ON_BOOT": "false",
            "AGENTFLOW_SERVING_BRIDGE_ENABLED": "false",
            "AGENTFLOW_CONTROLPLANE_STORE": "embedded",
            "AGENTFLOW_PROCESS_ROLE": "all",
            "AGENTFLOW_NODE_ROLE": "standalone",
            "AGENTFLOW_NODE_EMITTER_ENABLED": "false",
            "OTEL_SDK_DISABLED": "true",
        }
    )
    return environment


def prepare_demo(environment: dict[str, str], *, burst: int) -> None:
    """Provision demo rows and pass synthetic events through the local pipeline."""
    commands = (
        [
            sys.executable,
            "-m",
            "agentflow_runtime.serving.provision",
            "--schema",
            "--seed",
        ],
        [
            sys.executable,
            "-m",
            "agentflow_runtime.processing.local_pipeline",
            "--burst",
            str(burst),
            "--no-iceberg",
        ],
    )
    for command in commands:
        subprocess.run(command, check=True, cwd=REPO_ROOT, env=environment)


def serve_demo(
    environment: dict[str, str],
    *,
    host: str,
    port: int,
) -> None:
    """Run the local API in the foreground until the user stops it."""
    subprocess.run(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "agentflow_runtime.serving.api.main:app",
            "--host",
            host,
            "--port",
            str(port),
        ],
        check=True,
        cwd=REPO_ROOT,
        env=environment,
    )


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare and run the no-Docker AgentFlow demo on DuckDB."
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=REPO_ROOT / "agentflow_demo.duckdb",
        help="Persistent DuckDB file (default: agentflow_demo.duckdb).",
    )
    parser.add_argument(
        "--burst",
        type=_positive_int,
        default=500,
        help="Synthetic events to process before serving (default: 500).",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=_positive_int, default=8000)
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Provision and seed the database, then exit without starting the API.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    environment = build_environment(args.db_path)

    print(f"Preparing no-Docker demo database: {environment['DUCKDB_PATH']}")
    prepare_demo(environment, burst=args.burst)
    if args.prepare_only:
        print("Local demo database is ready.")
        return 0

    print(f"Starting AgentFlow at http://{args.host}:{args.port}")
    print("API docs: append /docs. Press Ctrl+C to stop.")
    try:
        serve_demo(environment, host=args.host, port=args.port)
    except KeyboardInterrupt:
        print("\nAgentFlow local demo stopped.")
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
