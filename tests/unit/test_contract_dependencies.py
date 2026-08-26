import re
import tomllib
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EDITABLE_INSTALL_PATTERN = re.compile(r"""pip install -e\s+(?:"([^"]+)"|'([^']+)'|([^\s]+))""")
CI_SYNC_PATTERN = re.compile(r"bash scripts/ci_sync\.sh\s+([a-z][a-z0-9-]*)")


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


def _workflow_job_sync_profiles(workflow_path: Path, job_name: str) -> list[str]:
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    job = workflow["jobs"][job_name]
    profiles = []

    for step in job.get("steps", []):
        run = step.get("run")
        if isinstance(run, str):
            profiles.extend(CI_SYNC_PATTERN.findall(run))

    return _dedupe(profiles)


def _workflow_targets_with_sync_calls() -> list[tuple[str, str]]:
    targets = []

    for workflow_path in sorted((PROJECT_ROOT / ".github" / "workflows").glob("*.yml")):
        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))

        for job_name in workflow.get("jobs", {}):
            if _workflow_job_sync_profiles(workflow_path, job_name):
                targets.append((workflow_path.relative_to(PROJECT_ROOT).as_posix(), job_name))

    return sorted(targets)


def _expected_sync_environment(editable_installs: list[str]) -> tuple[list[str], list[str]]:
    """Map a contract profile's editable-installs to ci_sync.sh extras/editables.

    Audit F-05: CI installs run through scripts/ci_sync.sh (uv sync --frozen)
    instead of raw `pip install -e` range resolution. The contract keeps its
    editable-installs vocabulary; this derives the frozen equivalent:
    "./integrations[mcp]" becomes the root `integrations` extra (which mirrors
    the mcp pin into uv.lock) plus a --no-deps editable install.
    """
    extras: list[str] = []
    editables: list[str] = []

    for install_target in editable_installs:
        if install_target == ".":
            continue
        if install_target.startswith(".[") and install_target.endswith("]"):
            extras.extend(install_target[2:-1].split(","))
            continue
        if install_target == "./sdk":
            editables.append("sdk")
            continue
        if install_target == "./integrations[mcp]":
            extras.append("integrations")
            editables.append("integrations")
            continue
        raise AssertionError(f"unsupported editable install target {install_target!r}")

    return extras, editables


def _ci_sync_profiles() -> dict[str, tuple[list[str], list[str]]]:
    script = (PROJECT_ROOT / "scripts" / "ci_sync.sh").read_text(encoding="utf-8")
    arm_pattern = re.compile(
        r"^\s{2}([a-z][a-z0-9-]*)\)\s*"
        r"(?:extras=\(([^)]*)\))?;?\s*"
        r"(?:editables=\(([^)]*)\))?\s*;;",
        re.MULTILINE,
    )
    profiles = {}

    for name, extras, editables in arm_pattern.findall(script):
        profiles[name] = (
            extras.split() if extras else [],
            editables.split() if editables else [],
        )

    return profiles


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


def test_runtime_and_docker_image_include_redis_client():
    pyproject = _load_pyproject()
    runtime_dependencies = pyproject["project"]["dependencies"]
    docker_lock = (PROJECT_ROOT / "requirements-docker.lock").read_text(encoding="utf-8")

    assert any(dependency.startswith("redis") for dependency in runtime_dependencies)
    assert "redis==" in docker_lock


def test_cloud_extra_uses_python_313_compatible_pyiceberg_core():
    """Iceberg writes need native transforms without reintroducing the cp313 break.

    PyIceberg 0.11 requires ``pyiceberg-core`` for partition transforms and
    table appends. Core 0.8 excludes Python 3.13, while 0.7 ships a compatible
    stable-ABI wheel for every supported interpreter.
    """
    pyproject = _load_pyproject()
    cloud = pyproject["project"]["optional-dependencies"]["cloud"]
    docker_lock = (PROJECT_ROOT / "requirements-docker.lock").read_text(encoding="utf-8")

    assert any(
        dependency == "pyiceberg>=0.7,<1" or dependency.startswith("pyiceberg>=")
        for dependency in cloud
    ), cloud
    assert not any("[pyiceberg-core]" in dependency for dependency in cloud), cloud
    assert "pyiceberg-core>=0.7,<0.8" in cloud
    assert "pyiceberg==" in docker_lock
    assert "pyiceberg-core==0.7.0" in docker_lock


def test_mcp_integration_rejects_breaking_major_versions():
    integrations = tomllib.loads(
        (PROJECT_ROOT / "integrations" / "pyproject.toml").read_text(encoding="utf-8")
    )
    mcp_dependencies = integrations["project"]["optional-dependencies"]["mcp"]

    assert "mcp>=1.0,<2" in mcp_dependencies


def test_contract_workflow_uses_contract_extra():
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "contract.yml").read_text(encoding="utf-8")

    assert "bash scripts/ci_sync.sh contract" in workflow
    assert "pip install schemathesis" not in workflow


def test_pytest_uses_stable_local_test_environment():
    pyproject = _load_pyproject()
    pytest_options = pyproject["tool"]["pytest"]["ini_options"]

    addopts = pytest_options.get("addopts", [])

    assert "-p" in addopts
    assert "no:schemathesis" in addopts
    assert not any(option.startswith("--basetemp") for option in addopts)
    assert pytest_options.get("cache_dir") == ".tmp/pytest-cache"


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
    assert root_project.get("readme") == "README.md"
    assert sdk_project["name"] == "agentflow-client"
    assert profiles["test-integrations"]["editable-installs"] == [
        ".[dev,cloud]",
        "./sdk",
        "./integrations[mcp]",
    ]


def test_api_dockerfile_prepares_root_package_metadata():
    text = (PROJECT_ROOT / "Dockerfile.api").read_text(encoding="utf-8")

    assert "COPY README.md /build/README.md" in text
    assert "python -m build --wheel" in text
    assert "pip install --no-cache-dir -e" not in text
    assert "setuptools==82.0.1" in text
    assert "wheel==0.47.0" in text
    assert "COPY contracts /app/contracts" in text
    assert "AGENTFLOW_ENTITY_CONTRACTS_DIR=/app/contracts/entities" in text
    # Audit P1-3: third-party packages come only from the hash-pinned
    # export of uv.lock; the project wheel installs with --no-deps and
    # pip check proves the environment is consistent.
    assert "--require-hashes -r /tmp/requirements-docker.lock" in text
    assert 'pip install --no-cache-dir --no-deps "${wheel}"' in text
    assert "pip check" in text
    # Runtime image must not ship installer tooling: Trivy SBOM tied
    # GHSA-6v7p-g79w-8964 (msgpack via pip vendor) and CVE-2025-47273
    # (setuptools) to the final-layer pip/setuptools/wheel tree, not
    # to requirements-docker.lock. Uninstall only after installs and
    # pip check so the hash-locked environment is still verified.
    final_stage = text.rsplit("FROM ", maxsplit=1)[-1]
    uninstall = "python -m pip uninstall --yes pip setuptools wheel"
    assert uninstall in final_stage
    assert final_stage.index("pip check") < final_stage.index(uninstall)
    # Q0.2 / S9: scale profile needs the Postgres control-plane driver
    # baked in. The wheel installs --no-deps, so the guarantee now lives
    # in the lock export the image installs from — pool included (audit P1-1).
    lock_text = (PROJECT_ROOT / "requirements-docker.lock").read_text(encoding="utf-8")
    assert "psycopg==" in lock_text
    assert "psycopg-pool==" in lock_text
    assert "boto3==" in lock_text  # the cloud extra is in the export too


def test_prod_compose_api_build_reuses_dockerfile_api():
    compose = yaml.safe_load((PROJECT_ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8"))
    build = compose["services"]["agentflow-api"]["build"]

    assert build["context"] == "."
    assert build["dockerfile"] == "Dockerfile.api"
    assert "dockerfile_inline" not in build


def test_prod_compose_default_duckdb_config_has_no_required_secret_interpolation():
    compose_text = (PROJECT_ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")

    assert "GF_SECURITY_ADMIN_USER: ${GF_SECURITY_ADMIN_USER:-}" in compose_text
    assert "GF_SECURITY_ADMIN_PASSWORD: ${GF_SECURITY_ADMIN_PASSWORD:-}" in compose_text
    assert "agentflow-local" not in compose_text
    assert "${GF_SECURITY_ADMIN_USER:?" not in compose_text
    assert "${GF_SECURITY_ADMIN_PASSWORD:?" not in compose_text


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


def test_publication_checklist_uses_reproducible_npm_release_install():
    checklist = (PROJECT_ROOT / "docs" / "operations" / "publication-checklist.md").read_text(
        encoding="utf-8"
    )

    assert "npm ci" in checklist
    assert "python scripts/check_release_artifacts.py dist/* sdk/dist/*" in checklist
    assert "npm install --package-lock=false" not in checklist


def test_dependency_profile_targets_match_workflow_jobs():
    _, targets = _load_dependency_contract()

    workflow_targets = [target for target in targets if target["kind"] == "workflow"]
    assert workflow_targets

    for target in workflow_targets:
        sync_profiles = _workflow_job_sync_profiles(PROJECT_ROOT / target["path"], target["job"])

        assert sync_profiles == [target["profile"]], (
            f"{target['name']} drifted from profile {target['profile']!r}: {sync_profiles!r}"
        )


def test_dependency_profile_matrix_covers_all_workflow_sync_calls():
    _, targets = _load_dependency_contract()

    declared_targets = sorted(
        (target["path"], target["job"]) for target in targets if target["kind"] == "workflow"
    )

    assert declared_targets == _workflow_targets_with_sync_calls()


def test_workflows_never_use_raw_editable_installs():
    # Audit F-05: a raw `pip install -e ".[...]"` resolves fresh ranges on
    # every run; every CI job must install through scripts/ci_sync.sh so the
    # frozen uv.lock resolution is the only dependency source.
    for workflow_path in sorted((PROJECT_ROOT / ".github" / "workflows").glob("*.yml")):
        text = workflow_path.read_text(encoding="utf-8")

        assert not _extract_editable_installs(text), (
            f"{workflow_path.name} bypasses scripts/ci_sync.sh with a raw editable install"
        )


def test_ci_sync_profiles_match_dependency_contract():
    profiles, _ = _load_dependency_contract()
    sync_profiles = _ci_sync_profiles()

    assert set(sync_profiles) == set(profiles), (
        "scripts/ci_sync.sh profile arms must mirror the dependency contract"
    )

    for profile_name, profile in profiles.items():
        expected = _expected_sync_environment(profile["editable-installs"])

        assert sync_profiles[profile_name] == expected, (
            f"ci_sync.sh profile {profile_name!r} drifted from the contract: "
            f"{sync_profiles[profile_name]!r} != {expected!r}"
        )


def test_make_setup_uses_test_integrations_profile():
    profiles, _ = _load_dependency_contract()
    makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")

    assert (
        _dedupe(_extract_editable_installs(makefile))
        == profiles["test-integrations"]["editable-installs"]
    )
    assert ".[dev,integrations,cloud]" not in makefile


def test_make_demo_explicitly_uses_local_open_auth_mode():
    makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")

    assert "AGENTFLOW_AUTH_DISABLED=true DUCKDB_PATH=agentflow_demo.duckdb uvicorn" in makefile


def test_pytest_workflows_prepare_tmp_parent_directory():
    workflow_paths = sorted((PROJECT_ROOT / ".github" / "workflows").glob("*.yml"))

    pytest_workflows = [
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in workflow_paths
        if "pytest" in path.read_text(encoding="utf-8")
    ]

    assert pytest_workflows
    for relative_path in pytest_workflows:
        workflow_text = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        assert "mkdir -p .tmp" in workflow_text, (
            f"{relative_path} must create .tmp before pytest uses cache_dir=.tmp/..."
        )
