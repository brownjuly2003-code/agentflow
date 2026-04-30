from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


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
