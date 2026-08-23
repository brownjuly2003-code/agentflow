"""Validate public project claims against their machine-readable source."""

from __future__ import annotations

import argparse
import ast
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _load_manifest(root: Path) -> dict[str, Any]:
    path = root / "config" / "project_claims.toml"
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"cannot load {path.relative_to(root).as_posix()}: {exc}") from exc


def _validate_documents(root: Path, manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for document in manifest.get("documents", []):
        relative = str(document["path"])
        path = root / relative
        if not path.is_file():
            errors.append(f"{relative}: document is missing")
            continue
        text = path.read_text(encoding="utf-8")
        normalized_text = " ".join(text.split())
        for fragment in document.get("required", []):
            if " ".join(fragment.split()) not in normalized_text:
                errors.append(f"{relative}: missing required claim fragment {fragment!r}")
        for fragment in document.get("forbidden", []):
            if " ".join(fragment.split()) in normalized_text:
                errors.append(f"{relative}: contains forbidden stale claim {fragment!r}")
    return errors


def _validate_runtime(root: Path, manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    production = manifest["production"]
    version = str(production["flink_version"])

    requirements = (
        root / "src" / "agentflow_runtime" / "processing" / "flink_jobs" / "requirements.txt"
    ).read_text(encoding="utf-8")
    expected_requirement = f"apache-flink=={version}"
    if expected_requirement not in requirements:
        errors.append(
            "src/agentflow_runtime/processing/flink_jobs/requirements.txt: "
            f"missing runtime pin {expected_requirement!r}"
        )

    dockerfile = (root / production["artifact_definition"]).read_text(encoding="utf-8")
    expected_base = f"FROM {production['base_image']}"
    if not dockerfile.startswith(f"{expected_base}\n"):
        errors.append(
            f"{production['artifact_definition']}: official Flink base image "
            f"must be {production['base_image']!r}"
        )
    expected_arg = f"ARG FLINK_VERSION={version}"
    if expected_arg not in dockerfile:
        errors.append(
            f"{production['artifact_definition']}: missing runtime declaration {expected_arg!r}"
        )

    helm_values_path = root / "helm" / "agentflow" / "values.yaml"
    helm_values = yaml.safe_load(helm_values_path.read_text(encoding="utf-8"))
    flink_job = helm_values.get("flinkJob", {})
    if str(flink_job.get("image", {}).get("tag")) != version:
        errors.append(
            "helm/agentflow/values.yaml: flinkJob.image.tag "
            f"must match production Flink version {version!r}"
        )
    expected_enum = "v" + version.rsplit(".", 1)[0].replace(".", "_")
    if flink_job.get("flinkVersion") != expected_enum:
        errors.append(
            f"helm/agentflow/values.yaml: flinkJob.flinkVersion must be {expected_enum!r}"
        )

    flink_template_path = root / "helm" / "agentflow" / "templates" / "flinkdeployment.yaml"
    flink_template = flink_template_path.read_text(encoding="utf-8")
    expected_python_jar = f"flink-python-{version}.jar"
    if expected_python_jar not in flink_template:
        errors.append(
            "helm/agentflow/templates/flinkdeployment.yaml: "
            f"missing PyFlink driver artifact {expected_python_jar!r}"
        )

    return errors


def _validate_python_versions(root: Path, manifest: dict[str, Any]) -> list[str]:
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    declared = set(manifest["python"]["declared_versions"])
    environments = pyproject.get("tool", {}).get("uv", {}).get("environments", [])
    resolved = {
        match.group(1)
        for value in environments
        if (match := re.fullmatch(r"python_version == '([^']+)'", value))
    }
    errors: list[str] = []
    if resolved != declared:
        errors.append(
            "pyproject.toml: [tool.uv].environments versions "
            f"{sorted(resolved)!r} != claims {sorted(declared)!r}"
        )

    workflow = yaml.safe_load(
        (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    matrix_versions = {
        str(version)
        for version in workflow["jobs"]["python-compat"]["strategy"]["matrix"]["python-version"]
    }
    claimed_smoke = set(manifest["python"]["ci_smoke_versions"])
    if matrix_versions != claimed_smoke:
        errors.append(
            ".github/workflows/ci.yml: python-compat matrix "
            f"{sorted(matrix_versions)!r} != claims {sorted(claimed_smoke)!r}"
        )
    return errors


def _validate_quality_gates(root: Path, manifest: dict[str, Any]) -> list[str]:
    quality = manifest["quality"]
    project_floor = int(quality["project_coverage_floor_percent"])
    patch_floor = int(quality["patch_coverage_floor_percent"])
    critical_floor = int(quality["critical_module_coverage_floor_percent"])
    workflow_path = root / ".github" / "workflows" / "ci.yml"
    workflow = workflow_path.read_text(encoding="utf-8")
    errors: list[str] = []

    expected_fragments = (
        (
            f"--cov-fail-under={project_floor}",
            f"project coverage floor {project_floor}",
        ),
        (
            f"diff-cover coverage.xml --compare-branch=origin/main --fail-under={patch_floor}",
            f"patch coverage floor {patch_floor}",
        ),
        (
            f"--fail-under={critical_floor}",
            f"critical-module coverage floor {critical_floor}",
        ),
    )
    for fragment, description in expected_fragments:
        if fragment not in workflow:
            errors.append(f".github/workflows/ci.yml: missing claimed {description} gate")

    if quality.get("strict_documentation_build") and "mkdocs build --strict" not in workflow:
        errors.append(".github/workflows/ci.yml: missing claimed strict documentation gate")

    codecov = yaml.safe_load((root / "codecov.yml").read_text(encoding="utf-8"))
    codecov_patch = int(codecov["coverage"]["status"]["patch"]["default"]["target"].rstrip("%"))
    if codecov_patch != patch_floor:
        errors.append(f"codecov.yml: patch coverage target {codecov_patch} != claims {patch_floor}")
    return errors


def _render_sdk_capabilities(manifest: dict[str, Any]) -> str:
    rows = [
        "# SDK capability contract",
        "",
        "Generated from [`config/project_claims.toml`](../config/project_claims.toml). "
        "Edit the manifest, not this table.",
        "",
        "| Capability | Python methods | TypeScript methods |",
        "| --- | --- | --- |",
    ]
    for capability in manifest["sdk"].get("capability", []):
        python_methods = ", ".join(f"`{name}`" for name in capability["python_methods"])
        typescript_methods = ", ".join(f"`{name}`" for name in capability["typescript_methods"])
        rows.append(f"| {capability['name']} | {python_methods} | {typescript_methods} |")
    rows.append("")
    return "\n".join(rows)


def _validate_sdk_capabilities(root: Path, manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    python_path = root / "sdk" / "agentflow" / "client.py"
    python_tree = ast.parse(python_path.read_text(encoding="utf-8"))
    client_class = next(
        (
            node
            for node in python_tree.body
            if isinstance(node, ast.ClassDef) and node.name == "AgentFlowClient"
        ),
        None,
    )
    python_methods = (
        {
            node.name
            for node in client_class.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not node.name.startswith("_")
        }
        if client_class is not None
        else set()
    )

    typescript_path = root / "sdk-ts" / "src" / "client.ts"
    typescript_text = typescript_path.read_text(encoding="utf-8")
    typescript_methods = set(
        re.findall(
            r"^  (?:async\s+)?\*?([A-Za-z][A-Za-z0-9_]*)(?:<.*>)?\s*\(",
            typescript_text,
            flags=re.MULTILINE,
        )
    )

    for capability in manifest["sdk"].get("capability", []):
        for method in capability["python_methods"]:
            if method not in python_methods:
                errors.append(
                    f"sdk/agentflow/client.py: capability {capability['name']!r} "
                    f"requires public method {method!r}"
                )
        for method in capability["typescript_methods"]:
            if method not in typescript_methods:
                errors.append(
                    f"sdk-ts/src/client.ts: capability {capability['name']!r} "
                    f"requires public method {method!r}"
                )

    docs_path = root / "docs" / "sdk-capabilities.md"
    expected_docs = _render_sdk_capabilities(manifest)
    if not docs_path.is_file():
        errors.append("docs/sdk-capabilities.md: generated capability table is missing")
    elif docs_path.read_text(encoding="utf-8") != expected_docs:
        errors.append(
            "docs/sdk-capabilities.md: generated capability table is stale; "
            "render it from config/project_claims.toml"
        )
    return errors


def validate_repository(root: Path = ROOT) -> list[str]:
    """Return every project-claim inconsistency under *root*."""

    root = root.resolve()
    try:
        manifest = _load_manifest(root)
    except ValueError as exc:
        return [str(exc)]

    errors = _validate_documents(root, manifest)
    errors.extend(_validate_runtime(root, manifest))
    errors.extend(_validate_python_versions(root, manifest))
    errors.extend(_validate_quality_gates(root, manifest))
    errors.extend(_validate_sdk_capabilities(root, manifest))

    for relative in manifest.get("required_evidence", []):
        if not (root / relative).is_file():
            errors.append(f"{relative}: required evidence is missing")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)

    errors = validate_repository(args.root)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("project claims: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
