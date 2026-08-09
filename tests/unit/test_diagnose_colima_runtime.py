"""Contract tests for the bounded, read-only Colima diagnostic runner."""

from __future__ import annotations

import importlib.util
import re
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "diagnose_colima_runtime.py"


def _load_module():
    assert SCRIPT_PATH.exists(), f"missing diagnostic runner at {SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location("diagnose_colima_runtime_under_test", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ssh_timeout_is_returned_as_data(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    observed: dict[str, object] = {}

    def raise_timeout(command: list[str], **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        raise subprocess.TimeoutExpired(command, kwargs["timeout"], output="partial")

    monkeypatch.setattr(module.subprocess, "run", raise_timeout)
    client = module.ReadOnlySshClient(
        host="deproject-mac",
        timeout_seconds=7,
        executable="ssh",
    )

    result = client.run("host_time", "date -u +%s")

    assert result.name == "host_time"
    assert result.status == "timeout"
    assert result.returncode == 124
    assert result.stdout == "partial"
    assert observed["command"][-2:] == ["deproject-mac", "date -u +%s"]
    assert observed["kwargs"]["timeout"] == 12
    assert "shell" not in observed["kwargs"]


def test_collection_continues_after_timeout_and_marks_partial() -> None:
    module = _load_module()
    config = module.DiagnosticConfig(
        ssh_host="deproject-mac",
        colima_profile="agentflow-fc5-7113966",
        timeout_seconds=15,
    )

    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def run(self, name: str, command: str):
            self.calls.append((name, command))
            if name == "host_time":
                return module.CheckResult(name, "timeout", 124, "", "timed out", 15000)
            if name == "kind_node":
                return module.CheckResult(
                    name,
                    "pass",
                    0,
                    "agentflow-reverify-ed03fc47-control-plane\n",
                    "",
                    5,
                )
            return module.CheckResult(name, "pass", 0, "ok\n", "", 5)

    client = FakeClient()

    payload = module.collect_diagnostics(
        config,
        client,
        captured_at="2026-08-09T12:00:00Z",
    )

    assert payload["status"] == "partial"
    assert payload["captured_at"] == "2026-08-09T12:00:00Z"
    assert [item["name"] for item in payload["checks"]] == [
        spec.name
        for spec in (
            *module.build_base_checks(config),
            *module.build_guest_checks(
                config,
                "agentflow-reverify-ed03fc47-control-plane",
            ),
        )
    ]
    assert payload["checks"][0]["status"] == "timeout"
    assert len(client.calls) == len(payload["checks"])


def test_generated_commands_are_read_only() -> None:
    module = _load_module()
    config = module.DiagnosticConfig(
        ssh_host="deproject-mac",
        colima_profile="agentflow-fc5-7113966",
        timeout_seconds=15,
    )
    specs = (
        *module.build_base_checks(config),
        *module.build_guest_checks(config, "agentflow-reverify-ed03fc47-control-plane"),
    )
    forbidden = re.compile(
        r"\b(?:apply|create|delete|exec\s+[^\n]*\brm\b|patch|prune|restart|start|stop)\b",
        re.IGNORECASE,
    )

    assert specs
    for spec in specs:
        assert not forbidden.search(spec.command), (spec.name, spec.command)
        assert "kubectl" not in spec.command


def test_unsafe_profile_and_node_names_are_rejected() -> None:
    module = _load_module()

    with pytest.raises(ValueError, match="colima profile"):
        module.DiagnosticConfig(
            ssh_host="deproject-mac",
            colima_profile="profile; colima stop",
            timeout_seconds=15,
        )

    config = module.DiagnosticConfig(
        ssh_host="deproject-mac",
        colima_profile="agentflow-fc5-7113966",
        timeout_seconds=15,
    )
    with pytest.raises(ValueError, match="kind node"):
        module.build_guest_checks(config, "node; docker rm victim")
