from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tests.load.run_load_test import load_profile_from_env

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _health_check_weight(env_value: str | None) -> int:
    env = os.environ.copy()
    if env_value is None:
        env.pop("AGENTFLOW_LOAD_HEALTH_CHECK_WEIGHT", None)
    else:
        env["AGENTFLOW_LOAD_HEALTH_CHECK_WEIGHT"] = env_value

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import tests.load.locustfile as locustfile; "
                "print(locustfile.AgentUser.health_check.locust_task_weight)"
            ),
        ],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return int(result.stdout.strip())


def test_health_check_weight_defaults_to_realistic_profile(monkeypatch):
    monkeypatch.delenv("AGENTFLOW_LOAD_HEALTH_CHECK_WEIGHT", raising=False)

    assert _health_check_weight(None) == 1


def test_health_check_weight_can_be_disabled_for_ci_smoke_gate(monkeypatch):
    monkeypatch.setenv("AGENTFLOW_LOAD_HEALTH_CHECK_WEIGHT", "0")

    assert _health_check_weight("0") == 0


def test_load_profile_defaults_to_threshold_profile(monkeypatch):
    monkeypatch.delenv("AGENTFLOW_LOAD_USERS", raising=False)
    monkeypatch.delenv("AGENTFLOW_LOAD_SPAWN_RATE", raising=False)
    monkeypatch.delenv("AGENTFLOW_LOAD_RUN_TIME", raising=False)

    assert load_profile_from_env() == {
        "users": 50,
        "spawn_rate": 10,
        "run_time": "60s",
    }


def test_load_profile_can_be_reduced_for_ci_smoke_gate(monkeypatch):
    monkeypatch.setenv("AGENTFLOW_LOAD_USERS", "15")
    monkeypatch.setenv("AGENTFLOW_LOAD_SPAWN_RATE", "5")
    monkeypatch.setenv("AGENTFLOW_LOAD_RUN_TIME", "45s")

    assert load_profile_from_env() == {
        "users": 15,
        "spawn_rate": 5,
        "run_time": "45s",
    }
