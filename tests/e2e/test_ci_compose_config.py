from __future__ import annotations

import ast
import importlib.util
import json
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


def _extract_e2e_workflow_inline_python() -> str:
    workflow = yaml.safe_load(
        (PROJECT_ROOT / ".github" / "workflows" / "e2e.yml").read_text(encoding="utf-8")
    )
    start_step = next(
        step for step in workflow["jobs"]["e2e"]["steps"] if step.get("name") == "Start E2E stack"
    )
    run_script = start_step["run"]
    _, marker, inline_python = run_script.partition("python - <<'PY'\n")

    assert marker

    inline_python, marker, _ = inline_python.partition("\nPY")

    assert marker

    return inline_python


def _load_compose_ps_parser():
    workflow_ast = ast.parse(_extract_e2e_workflow_inline_python())
    parser_function = next(
        node
        for node in workflow_ast.body
        if isinstance(node, ast.FunctionDef) and node.name == "parse_compose_ps_output"
    )
    parser_module = ast.Module(body=[parser_function], type_ignores=[])
    namespace = {"json": json}

    exec(compile(parser_module, filename="<e2e-workflow>", mode="exec"), namespace)  # noqa: S102  # AST-compiled local module; inputs not user-controlled

    return namespace["parse_compose_ps_output"]


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


def test_e2e_workflow_parses_compose_ps_ndjson_output():
    parse_compose_ps_output = _load_compose_ps_parser()

    entries = parse_compose_ps_output(
        "\n".join(
            [
                '{"Service":"redis","State":"running","Health":"healthy"}',
                '{"Service":"postgres","State":"running","Health":"healthy"}',
            ]
        )
    )

    assert [entry["Service"] for entry in entries] == ["redis", "postgres"]


def test_e2e_workflow_targets_lite_compose_stack():
    workflow_text = (PROJECT_ROOT / ".github" / "workflows" / "e2e.yml").read_text(encoding="utf-8")

    assert "timeout-minutes: 12" in workflow_text
    assert "docker-compose.e2e.yml" in workflow_text
    assert "docker-compose.prod.yml" not in workflow_text
    assert '"ps", "--format", "json"' in workflow_text
    assert "parse_compose_ps_output" in workflow_text
    assert "docker compose -f docker-compose.e2e.yml logs --tail=500" in workflow_text
