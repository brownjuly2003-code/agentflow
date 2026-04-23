from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_e2e_runtime_uses_lite_compose_file():
    conftest_module = _load_module(PROJECT_ROOT / "tests" / "e2e" / "conftest.py", "e2e_conftest")

    assert conftest_module.COMPOSE_FILE == PROJECT_ROOT / "docker-compose.e2e.yml"


def test_lite_compose_contains_only_required_services():
    compose_path = PROJECT_ROOT / "docker-compose.e2e.yml"

    assert compose_path.exists()

    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

    assert set(compose["services"]) == {"agentflow-api", "redis", "kafka", "postgres"}


def test_lite_compose_mounts_contracts_for_api_startup():
    compose = yaml.safe_load((PROJECT_ROOT / "docker-compose.e2e.yml").read_text(encoding="utf-8"))

    assert "./contracts:/app/contracts:ro" in compose["services"]["agentflow-api"]["volumes"]


def test_e2e_workflow_targets_lite_compose_stack():
    workflow_text = (PROJECT_ROOT / ".github" / "workflows" / "e2e.yml").read_text(encoding="utf-8")

    assert "timeout-minutes: 12" in workflow_text
    assert "docker-compose.e2e.yml" in workflow_text
    assert "docker-compose.prod.yml" not in workflow_text
    assert "ps --format json" in workflow_text
    assert "docker compose -f docker-compose.e2e.yml logs --tail=500" in workflow_text
