from __future__ import annotations

import json
import re
import shlex
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TRIVY_ACTION_PIN = "aquasecurity/trivy-action@ed142fd0673e97e23eac54620cfb913e5ce36c25"
WAIVERS_PATH = "security/trivy-waivers.json"
EVALUATOR = "scripts/evaluate_trivy_policy.py"
API_IMAGE = "agentflow-api:security-scan"
FLINK_IMAGE = "agentflow-flink:security-scan"
API_SCOPE = "api-runtime"
FLINK_SCOPE = "flink-runtime"
REQUIRED_EVALUATOR_FLAGS = ("--report", "--waivers", "--scope", "--output")
TRIVY_ARTIFACT_DIR = ".artifacts/trivy"
API_SBOM = f"{TRIVY_ARTIFACT_DIR}/agentflow-api.cdx.json"
FLINK_SBOM = f"{TRIVY_ARTIFACT_DIR}/agentflow-flink.cdx.json"
API_JSON = f"{TRIVY_ARTIFACT_DIR}/trivy-api.json"
FLINK_JSON = f"{TRIVY_ARTIFACT_DIR}/trivy-flink.json"
API_SARIF = f"{TRIVY_ARTIFACT_DIR}/trivy-api.sarif"
FLINK_SARIF = f"{TRIVY_ARTIFACT_DIR}/trivy-flink.sarif"
API_POLICY = f"{TRIVY_ARTIFACT_DIR}/trivy-api-policy.json"
FLINK_POLICY = f"{TRIVY_ARTIFACT_DIR}/trivy-flink-policy.json"
IAC_SARIF = f"{TRIVY_ARTIFACT_DIR}/trivy-iac.sarif"


def _load_security_workflow() -> dict[str, Any]:
    workflow_path = PROJECT_ROOT / ".github" / "workflows" / "security.yml"
    return yaml.safe_load(workflow_path.read_text(encoding="utf-8"))


def _trivy_steps() -> list[dict[str, Any]]:
    return list(_load_security_workflow()["jobs"]["trivy"]["steps"])


def _step_blob(step: dict[str, Any]) -> str:
    return yaml.dump(step, sort_keys=False)


def _trivy_action_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        step for step in steps if str(step.get("uses", "")).startswith("aquasecurity/trivy-action@")
    ]


def _image_trivy_steps(steps: list[dict[str, Any]], fmt: str) -> list[dict[str, Any]]:
    return [
        step
        for step in _trivy_action_steps(steps)
        if step.get("with", {}).get("format") == fmt and "image-ref" in step.get("with", {})
    ]


def _evaluator_commands(steps: list[dict[str, Any]]) -> list[list[str]]:
    commands: list[list[str]] = []
    for step in steps:
        run = step.get("run")
        if not isinstance(run, str) or EVALUATOR not in run:
            continue
        for line in run.splitlines():
            stripped = line.strip()
            if EVALUATOR not in stripped:
                continue
            commands.append(shlex.split(stripped))
    return commands


def _flag_map(argv: list[str]) -> dict[str, str]:
    flags: dict[str, str] = {}
    index = 2
    while index < len(argv):
        key = argv[index]
        assert key.startswith("--"), argv
        assert index + 1 < len(argv), argv
        flags[key] = argv[index + 1]
        index += 2
    return flags


def _makefile_text() -> str:
    return (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")


def _makefile_recipe(target: str) -> str:
    lines = _makefile_text().splitlines()
    collecting = False
    recipe: list[str] = []
    for line in lines:
        if collecting:
            if line.startswith("\t") or line.startswith("#") or line.strip() == "":
                recipe.append(line)
                continue
            break
        name = line.split(":", 1)[0]
        if name == target:
            collecting = True
    assert collecting, f"Make target {target!r} is missing"
    return "\n".join(recipe)


def _policy() -> dict[str, Any]:
    return json.loads((PROJECT_ROOT / WAIVERS_PATH).read_text(encoding="utf-8"))


def test_shipping_image_set_is_exactly_api_and_flink() -> None:
    steps = _trivy_steps()
    image_refs = {
        step["with"]["image-ref"]
        for step in _trivy_action_steps(steps)
        if "image-ref" in step.get("with", {})
    }
    assert image_refs == {API_IMAGE, FLINK_IMAGE}

    joined_runs = "\n".join(str(step.get("run", "")) for step in steps)
    assert "docker compose -f docker-compose.prod.yml build agentflow-api" in joined_runs
    assert f"docker tag agentflow-security-agentflow-api:latest {API_IMAGE}" in joined_runs
    assert (
        "docker compose -f docker-compose.yml -f docker-compose.flink.yml build flink-job-runner"
        in joined_runs
    )
    assert "agentflow-flink-local:latest" in joined_runs
    assert f"docker tag agentflow-flink-local:latest {FLINK_IMAGE}" in joined_runs


def test_each_shipping_image_has_filtered_json_sarif_sbom_and_unique_artifact() -> None:
    steps = _trivy_steps()
    json_steps = _image_trivy_steps(steps, "json")
    sarif_steps = _image_trivy_steps(steps, "sarif")
    sbom_steps = _image_trivy_steps(steps, "cyclonedx")

    for group in (json_steps, sarif_steps, sbom_steps):
        assert {step["with"]["image-ref"] for step in group} == {API_IMAGE, FLINK_IMAGE}

    json_outputs = [step["with"]["output"] for step in json_steps]
    sarif_outputs = [step["with"]["output"] for step in sarif_steps]
    sbom_outputs = [step["with"]["output"] for step in sbom_steps]
    assert len(set(json_outputs)) == 2
    assert len(set(sarif_outputs)) == 2
    assert len(set(sbom_outputs)) == 2

    for step in json_steps + sarif_steps:
        assert step["with"]["severity"] == "HIGH,CRITICAL"
        assert step["with"]["ignore-unfixed"] is True

    for step in sarif_steps:
        assert step["with"]["limit-severities-for-sarif"] is True

    uploads = [
        step for step in steps if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    ]
    artifact_names = [step["with"]["name"] for step in uploads]
    artifact_paths = [step["with"]["path"] for step in uploads]
    assert len(set(artifact_names)) == 2
    assert set(artifact_paths) == set(sbom_outputs)
    assert all(step["with"]["if-no-files-found"] == "error" for step in uploads)

    api_sbom = next(step for step in steps if step.get("name") == "Generate CycloneDX SBOM")
    assert api_sbom["with"] == {
        "image-ref": API_IMAGE,
        "format": "cyclonedx",
        "output": API_SBOM,
    }
    api_upload = next(step for step in steps if step.get("name") == "Upload CycloneDX SBOM")
    assert api_upload["with"]["name"] == "agentflow-api-sbom-cyclonedx"
    assert api_upload["with"]["path"] == API_SBOM
    assert set(json_outputs) == {API_JSON, FLINK_JSON}
    assert set(sarif_outputs) == {API_SARIF, FLINK_SARIF}
    assert set(sbom_outputs) == {API_SBOM, FLINK_SBOM}


def test_evaluator_calls_use_exact_cli_and_valid_scopes() -> None:
    commands = _evaluator_commands(_trivy_steps())
    assert len(commands) == 2

    parsed: dict[str, dict[str, str]] = {}
    for argv in commands:
        assert argv[0] in {"python", "python3"}
        assert argv[1] == EVALUATOR
        flags = _flag_map(argv)
        assert tuple(flags) == REQUIRED_EVALUATOR_FLAGS
        assert flags["--waivers"] == WAIVERS_PATH
        parsed[flags["--scope"]] = flags

    assert set(parsed) == {API_SCOPE, FLINK_SCOPE}

    json_by_image = {
        step["with"]["image-ref"]: step["with"]["output"]
        for step in _image_trivy_steps(_trivy_steps(), "json")
    }
    assert parsed[API_SCOPE]["--report"] == json_by_image[API_IMAGE] == API_JSON
    assert parsed[FLINK_SCOPE]["--report"] == json_by_image[FLINK_IMAGE] == FLINK_JSON
    assert parsed[API_SCOPE]["--output"] == API_POLICY
    assert parsed[FLINK_SCOPE]["--output"] == FLINK_POLICY
    assert parsed[API_SCOPE]["--output"] != parsed[FLINK_SCOPE]["--output"]

    policy_scopes = set(_policy()["scopes"])
    assert {API_SCOPE, FLINK_SCOPE} <= policy_scopes


def test_sarif_outputs_and_categories_are_unique_per_image() -> None:
    steps = _trivy_steps()
    sarif_steps = _image_trivy_steps(steps, "sarif")
    output_by_image = {step["with"]["image-ref"]: step["with"]["output"] for step in sarif_steps}
    assert len(set(output_by_image.values())) == 2

    uploads = [
        step
        for step in steps
        if str(step.get("uses", "")).startswith("github/codeql-action/upload-sarif@")
    ]
    category_by_file = {step["with"]["sarif_file"]: step["with"]["category"] for step in uploads}
    assert category_by_file[output_by_image[API_IMAGE]] == "trivy-api-image"
    assert category_by_file[output_by_image[FLINK_IMAGE]] == "trivy-flink-image"
    assert output_by_image[API_IMAGE] == API_SARIF
    assert output_by_image[FLINK_IMAGE] == FLINK_SARIF
    assert len(set(category_by_file.values())) == 2


def test_api_empty_scope_exists_and_flink_waivers_remain() -> None:
    policy = _policy()
    api = policy["scopes"][API_SCOPE]
    assert api["image"] == "agentflow-api"
    assert api["owner"] == "security"
    assert api["upstream_constraints"] == []
    assert api["waivers"] == []

    flink = policy["scopes"][FLINK_SCOPE]
    assert flink["image"] == "agentflow-flink"
    assert flink["owner"] == "security"
    assert flink["upstream_constraints"] == [
        "apache-flink==2.3.0 requires apache-beam>=2.54.0,<=2.61.0",
        "apache-beam==2.61.0 requires pyarrow>=3.0.0,<17.0.0",
        "apache-beam==2.61.0 requires httplib2>=0.8,<0.23.0",
    ]
    assert {
        (
            waiver["id"],
            waiver["package"],
            waiver["installed_version"],
            waiver["fixed_version"],
        )
        for waiver in flink["waivers"]
    } == {
        ("CVE-2026-59939", "httplib2", "0.22.0", "0.32.0"),
        ("CVE-2026-25087", "pyarrow", "16.1.0", "23.0.1"),
    }


def test_scan_and_policy_steps_are_unconditional_and_fail_closed() -> None:
    steps = _trivy_steps()
    for step in steps:
        blob = _step_blob(step)
        is_image_scan = str(step.get("uses", "")).startswith(
            "aquasecurity/trivy-action@"
        ) and "image-ref" in step.get("with", {})
        is_policy = EVALUATOR in str(step.get("run", ""))
        is_image_build = "docker compose" in str(step.get("run", "")) and "build" in str(
            step.get("run", "")
        )
        if not (is_image_scan or is_policy or is_image_build):
            continue
        assert step.get("continue-on-error") in (None, False), blob
        assert "if" not in step, blob
        if is_image_scan and step["with"].get("format") in {"json", "sarif"}:
            assert str(step["with"].get("exit-code", "0")) != "1", blob


def test_make_trivy_policy_invokes_both_scopes_without_suppressing_failure() -> None:
    makefile = _makefile_text()
    assert re.search(r"^\.PHONY:.*\btrivy-policy\b", makefile, flags=re.MULTILINE)
    recipe = _makefile_recipe("trivy-policy")
    assert "docker" not in recipe.lower()
    assert EVALUATOR in recipe
    assert f"--scope {API_SCOPE}" in recipe
    assert f"--scope {FLINK_SCOPE}" in recipe
    assert "--waivers security/trivy-waivers.json" in recipe
    assert "$(TRIVY_API_REPORT)" in recipe
    assert "$(TRIVY_FLINK_REPORT)" in recipe
    assert "$(TRIVY_API_POLICY_SUMMARY)" in recipe
    assert "$(TRIVY_FLINK_POLICY_SUMMARY)" in recipe
    for line in recipe.splitlines():
        if not line.startswith("\t"):
            continue
        body = line[1:].lstrip()
        assert not body.startswith("-"), line
        assert "|| true" not in body
        assert "|| exit 0" not in body
        assert "2>/dev/null" not in body


def test_makefile_trivy_path_defaults_use_canonical_artifacts_directory() -> None:
    makefile = _makefile_text()
    assert "TRIVY_API_REPORT ?= .artifacts/trivy/trivy-api.json" in makefile
    assert "TRIVY_FLINK_REPORT ?= .artifacts/trivy/trivy-flink.json" in makefile
    assert "TRIVY_API_POLICY_SUMMARY ?= .artifacts/trivy/trivy-api-policy.json" in makefile
    assert "TRIVY_FLINK_POLICY_SUMMARY ?= .artifacts/trivy/trivy-flink-policy.json" in makefile


def test_trivy_and_iac_jobs_prepare_canonical_directory_before_writers() -> None:
    workflow = _load_security_workflow()
    iac_steps = workflow["jobs"]["iac"]["steps"]
    iac_outputs = [
        step["with"]["output"]
        for step in iac_steps
        if str(step.get("uses", "")).startswith("aquasecurity/trivy-action@")
    ]
    iac_uploads = [
        step["with"]["sarif_file"]
        for step in iac_steps
        if str(step.get("uses", "")).startswith("github/codeql-action/upload-sarif@")
    ]
    assert iac_outputs == [IAC_SARIF]
    assert iac_uploads == [IAC_SARIF]

    for job_name in ("trivy", "iac"):
        steps = workflow["jobs"][job_name]["steps"]
        prepare = [
            index
            for index, step in enumerate(steps)
            if isinstance(step.get("run"), str) and "mkdir -p .artifacts/trivy" in step["run"]
        ]
        writer = next(
            index
            for index, step in enumerate(steps)
            if str(step.get("uses", "")).startswith("aquasecurity/trivy-action@")
            or EVALUATOR in str(step.get("run", ""))
        )
        assert prepare, f"{job_name} must create {TRIVY_ARTIFACT_DIR}"
        assert prepare[0] < writer


def test_pinned_trivy_action_sha_is_shared_across_image_scan_and_sbom_steps() -> None:
    pins = [
        step["uses"]
        for step in _trivy_action_steps(_trivy_steps())
        if "image-ref" in step.get("with", {})
    ]
    assert pins
    assert set(pins) == {TRIVY_ACTION_PIN}
