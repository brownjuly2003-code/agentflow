"""No-Docker local demo runner contract."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

from scripts import demo_local


def test_local_environment_selects_file_backed_duckdb(tmp_path: Path) -> None:
    db_path = tmp_path / "demo.duckdb"

    environment = demo_local.build_environment(
        db_path,
        base_environment={
            "KEEP_ME": "yes",
            "SERVING_BACKEND": "clickhouse",
            "AGENTFLOW_AUTH_DISABLED": "false",
            "AGENTFLOW_PROFILE": "production",
            "AGENTFLOW_SERVING_BRIDGE_ENABLED": "true",
            "AGENTFLOW_CONTROLPLANE_STORE": "postgres",
            "AGENTFLOW_CONTROLPLANE_PG_DSN": "postgresql://remote/agentflow",
            "AGENTFLOW_PROCESS_ROLE": "worker",
            "AGENTFLOW_NODE_ROLE": "edge",
            "AGENTFLOW_NODE_EMITTER_ENABLED": "true",
            "AGENTFLOW_NODE_CENTER_URL": "https://remote.example",
            "AGENTFLOW_NODE_TOKEN": "parent-token",
            "REDIS_URL": "redis://remote.example:6379",
            "OTEL_SDK_DISABLED": "false",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "https://otel.example",
        },
    )

    assert environment["KEEP_ME"] == "yes"
    assert environment["SERVING_BACKEND"] == "duckdb"
    assert environment["DUCKDB_PATH"] == str(db_path.resolve())
    assert environment["AGENTFLOW_AUTH_DISABLED"] == "true"
    assert environment["AGENTFLOW_LOCAL_ONLY"] == "true"
    assert environment["AGENTFLOW_PROFILE"] == "dev"
    assert environment["AGENTFLOW_SERVING_BRIDGE_ENABLED"] == "false"
    assert environment["AGENTFLOW_CONTROLPLANE_STORE"] == "embedded"
    assert environment["AGENTFLOW_PROCESS_ROLE"] == "all"
    assert environment["AGENTFLOW_NODE_ROLE"] == "standalone"
    assert environment["AGENTFLOW_NODE_EMITTER_ENABLED"] == "false"
    assert environment["OTEL_SDK_DISABLED"] == "true"
    assert "AGENTFLOW_CONTROLPLANE_PG_DSN" not in environment
    assert "AGENTFLOW_NODE_CENTER_URL" not in environment
    assert "AGENTFLOW_NODE_TOKEN" not in environment
    assert "REDIS_URL" not in environment
    assert "OTEL_EXPORTER_OTLP_ENDPOINT" not in environment


def test_prepare_demo_uses_python_modules_without_docker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def record_run(command: list[str], **kwargs: object) -> None:
        calls.append((command, kwargs))

    monkeypatch.setattr(demo_local.subprocess, "run", record_run)
    environment = {"SERVING_BACKEND": "duckdb"}

    demo_local.prepare_demo(environment, burst=25)

    assert [command for command, _ in calls] == [
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
            "25",
            "--no-iceberg",
        ],
    ]
    assert all(
        kwargs == {"check": True, "cwd": demo_local.REPO_ROOT, "env": environment}
        for _, kwargs in calls
    )
    assert "docker" not in " ".join(part for command, _ in calls for part in command).lower()


def test_prepare_only_does_not_start_api(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prepared: list[tuple[dict[str, str], int]] = []
    served: list[object] = []

    monkeypatch.setattr(
        demo_local,
        "prepare_demo",
        lambda environment, burst: prepared.append((environment, burst)),
    )
    monkeypatch.setattr(
        demo_local,
        "serve_demo",
        lambda *args, **kwargs: served.append((args, kwargs)),
    )

    exit_code = demo_local.main(
        [
            "--db-path",
            str(tmp_path / "demo.duckdb"),
            "--burst",
            "10",
            "--prepare-only",
        ]
    )

    assert exit_code == 0
    assert prepared[0][0]["SERVING_BACKEND"] == "duckdb"
    assert prepared[0][1] == 10
    assert served == []


def test_ci_smokes_fresh_checkout_local_only_duckdb() -> None:
    workflow_path = demo_local.REPO_ROOT / ".github" / "workflows" / "ci.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    job = workflow["jobs"]["local-duckdb-smoke"]

    assert job["runs-on"] == "ubuntu-latest"
    assert 0 < job["timeout-minutes"] <= 20
    assert "services" not in job
    assert job["env"] == {
        "SERVING_BACKEND": "clickhouse",
        "DUCKDB_PATH": "ci-must-ignore.duckdb",
        "AGENTFLOW_LOCAL_ONLY": "false",
        "AGENTFLOW_SERVING_BRIDGE_ENABLED": "true",
        "AGENTFLOW_CONTROLPLANE_PG_DSN": "postgresql://ci-must-not-connect.invalid/agentflow",
        "AGENTFLOW_NODE_CENTER_URL": "https://ci-must-not-connect.invalid",
        "AGENTFLOW_NODE_TOKEN": "ci-must-ignore",
        "AGENTFLOW_ICEBERG_CONFIG": "s3://ci-must-not-connect.invalid/catalog",
        "KAFKA_BOOTSTRAP_SERVERS": "ci-must-not-connect.invalid:9092",
        "FLINK_JOBMANAGER_URL": "http://ci-must-not-connect.invalid:8081",
        "REDIS_URL": "redis://ci-must-not-connect.invalid:6379/0",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "https://ci-must-not-connect.invalid:4317",
    }

    steps = job["steps"]
    assert any(step.get("uses", "").startswith("actions/checkout@") for step in steps)
    assert any(
        step.get("uses", "").startswith("actions/setup-python@")
        and step.get("with", {}).get("python-version") == "3.11"
        for step in steps
    )

    commands = "\n".join(step.get("run", "") for step in steps)
    assert "bash scripts/ci_sync.sh runtime" in commands
    assert "test ! -e .env" in commands
    assert (
        'python scripts/demo_local.py --db-path "${RUNNER_TEMP}/local-duckdb-smoke.duckdb" '
        "--burst 20 --prepare-only"
    ) in commands
    assert "setsid python -c" in commands
    assert "demo_local import build_environment, serve_demo" in commands
    assert 'kill -TERM -- "-${server_pid}"' in commands
    assert 'kill -0 -- "-${server_pid}"' in commands
    assert 'kill -KILL -- "-${server_pid}"' in commands
    assert "${base_url}/v1/health" in commands
    assert "${base_url}/v1/entity/order/ORD-20260404-1001" in commands
    assert "${base_url}/v1/query" in commands
    assert "Show me top 3 products" in commands
    assert "docker" not in commands.lower()
