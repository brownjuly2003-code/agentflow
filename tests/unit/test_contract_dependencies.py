import re
import tomllib
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EDITABLE_INSTALL_PATTERN = re.compile(r"""pip install -e\s+(?:"([^"]+)"|'([^']+)'|([^\s]+))""")


def _load_pyproject() -> dict:
    return tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _load_dependency_contract() -> tuple[dict, list[dict]]:
    pyproject = _load_pyproject()
    contract = pyproject["tool"]["agentflow"]["dependency-profiles"]

    return contract["profiles"], contract["targets"]


def _extract_editable_installs(text: str) -> list[str]:
    installs = []

    for match in EDITABLE_INSTALL_PATTERN.finditer(text):
        installs.append(next(group for group in match.groups() if group))

    return installs


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _workflow_job_editable_installs(workflow_path: Path, job_name: str) -> list[str]:
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    job = workflow["jobs"][job_name]
    installs = []

    for step in job.get("steps", []):
        run = step.get("run")
        if isinstance(run, str):
            installs.extend(_extract_editable_installs(run))

    return _dedupe(installs)


def _workflow_targets_with_editable_installs() -> list[tuple[str, str]]:
    targets = []

    for workflow_path in sorted((PROJECT_ROOT / ".github" / "workflows").glob("*.yml")):
        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))

        for job_name in workflow.get("jobs", {}):
            if _workflow_job_editable_installs(workflow_path, job_name):
                targets.append((workflow_path.relative_to(PROJECT_ROOT).as_posix(), job_name))

    return sorted(targets)


def test_contract_extra_installs_schemathesis():
    pyproject = _load_pyproject()

    contract = pyproject["project"]["optional-dependencies"].get("contract")

    assert contract is not None
    assert any(dependency.startswith("schemathesis") for dependency in contract)


def test_dev_extra_installs_jsonschema_for_helm_schema_tests():
    pyproject = _load_pyproject()

    dev_dependencies = pyproject["project"]["optional-dependencies"].get("dev")

    assert dev_dependencies is not None
    assert any(dependency.startswith("jsonschema") for dependency in dev_dependencies)


def test_contract_workflow_uses_contract_extra():
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "contract.yml").read_text(encoding="utf-8")

    assert 'pip install -e ".[dev,cloud,contract]"' in workflow
    assert "pip install schemathesis" not in workflow


def test_dependency_profiles_reference_declared_extras():
    pyproject = _load_pyproject()
    root_extras = pyproject["project"]["optional-dependencies"]
    integration_extras = tomllib.loads(
        (PROJECT_ROOT / "integrations" / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["optional-dependencies"]
    profiles, _ = _load_dependency_contract()

    assert "runtime" in profiles
    assert "dev-tools" in profiles
    assert "test" in profiles
    assert "test-integrations" in profiles
    assert "perf" in profiles
    assert "contract" in profiles

    for profile_name, profile in profiles.items():
        for install_target in profile["editable-installs"]:
            if install_target == ".":
                continue
            if install_target == "./sdk":
                continue
            if install_target.startswith(".[") and install_target.endswith("]"):
                extras = install_target[2:-1].split(",")
                assert extras
                for extra in extras:
                    assert extra in root_extras, (
                        f"profile {profile_name!r} references unknown root extra {extra!r}"
                    )
                continue
            if install_target.startswith("./integrations[") and install_target.endswith("]"):
                extras = install_target.removeprefix("./integrations[").removesuffix("]").split(",")
                assert extras
                for extra in extras:
                    assert extra in integration_extras, (
                        f"profile {profile_name!r} references unknown integrations extra {extra!r}"
                    )
                continue
            raise AssertionError(
                f"profile {profile_name!r} uses unsupported editable install target {install_target!r}"
            )


def test_runtime_and_sdk_package_identities_are_split():
    root_project = _load_pyproject()["project"]
    sdk_project = tomllib.loads(
        (PROJECT_ROOT / "sdk" / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]
    profiles, _ = _load_dependency_contract()

    assert root_project["name"] == "agentflow-runtime"
    assert sdk_project["name"] == "agentflow-client"
    assert profiles["test-integrations"]["editable-installs"] == [
        ".[dev,cloud]",
        "./sdk",
        "./integrations[mcp]",
    ]


def test_sdk_install_docs_match_split_package_identities():
    sdk_readme = (PROJECT_ROOT / "sdk" / "README.md").read_text(encoding="utf-8")
    product_doc = (PROJECT_ROOT / "docs" / "product.md").read_text(encoding="utf-8")
    integrations_doc = (PROJECT_ROOT / "docs" / "integrations.md").read_text(encoding="utf-8")

    assert "pip install agentflow-client" in sdk_readme
    assert "agentflow-runtime" in sdk_readme
    assert "pip install -e sdk/" not in sdk_readme
    assert "pip install agentflow-client" in product_doc
    assert "pip install -e sdk/" not in product_doc
    assert "pip install agentflow-integrations" in integrations_doc
    assert "pip install -e integrations/" not in integrations_doc


def test_dependency_profile_targets_match_workflow_jobs():
    profiles, targets = _load_dependency_contract()

    workflow_targets = [target for target in targets if target["kind"] == "workflow"]
    assert workflow_targets

    for target in workflow_targets:
        editable_installs = _workflow_job_editable_installs(
            PROJECT_ROOT / target["path"], target["job"]
        )

        assert editable_installs == profiles[target["profile"]]["editable-installs"], (
            f"{target['name']} drifted from profile {target['profile']!r}: {editable_installs!r}"
        )


def test_dependency_profile_matrix_covers_all_workflow_editable_installs():
    _, targets = _load_dependency_contract()

    declared_targets = sorted(
        (target["path"], target["job"]) for target in targets if target["kind"] == "workflow"
    )

    assert declared_targets == _workflow_targets_with_editable_installs()


def test_make_setup_uses_test_integrations_profile():
    profiles, _ = _load_dependency_contract()
    makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")

    assert (
        _dedupe(_extract_editable_installs(makefile))
        == profiles["test-integrations"]["editable-installs"]
    )
    assert ".[dev,integrations,cloud]" not in makefile
