from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TRIVY_ARTIFACT_DIR = ".artifacts/trivy"
TRIVY_ACTION_PREFIX = "aquasecurity/trivy-action@"
EVALUATOR = "scripts/evaluate_trivy_policy.py"
CANONICAL_TRIVY_OUTPUTS = {
    f"{TRIVY_ARTIFACT_DIR}/agentflow-api.cdx.json",
    f"{TRIVY_ARTIFACT_DIR}/agentflow-flink.cdx.json",
    f"{TRIVY_ARTIFACT_DIR}/trivy-api.json",
    f"{TRIVY_ARTIFACT_DIR}/trivy-flink.json",
    f"{TRIVY_ARTIFACT_DIR}/trivy-api.sarif",
    f"{TRIVY_ARTIFACT_DIR}/trivy-flink.sarif",
    f"{TRIVY_ARTIFACT_DIR}/trivy-api-policy.json",
    f"{TRIVY_ARTIFACT_DIR}/trivy-flink-policy.json",
    f"{TRIVY_ARTIFACT_DIR}/trivy-iac.sarif",
}


def _load_security_workflow() -> dict:
    workflow_path = PROJECT_ROOT / ".github" / "workflows" / "security.yml"
    return yaml.safe_load(workflow_path.read_text(encoding="utf-8"))


def _job(name: str) -> dict:
    return _load_security_workflow()["jobs"][name]


def _is_trivy_writer(step: dict) -> bool:
    uses = str(step.get("uses", ""))
    if uses.startswith(TRIVY_ACTION_PREFIX):
        return True
    run = step.get("run")
    return isinstance(run, str) and EVALUATOR in run


def _prepare_step_indexes(steps: list[dict]) -> list[int]:
    return [
        index
        for index, step in enumerate(steps)
        if isinstance(step.get("run"), str) and "mkdir -p .artifacts/trivy" in step["run"]
    ]


def test_trivy_job_generates_cyclonedx_sbom_artifact() -> None:
    workflow = _load_security_workflow()
    steps = workflow["jobs"]["trivy"]["steps"]

    sbom_step = next(
        (step for step in steps if step.get("name") == "Generate CycloneDX SBOM"),
        None,
    )
    assert sbom_step is not None
    assert str(sbom_step["uses"]).startswith("aquasecurity/trivy-action@")
    assert sbom_step["with"] == {
        "image-ref": "agentflow-api:security-scan",
        "format": "cyclonedx",
        "output": ".artifacts/trivy/agentflow-api.cdx.json",
    }

    upload_step = next(
        (step for step in steps if step.get("name") == "Upload CycloneDX SBOM"),
        None,
    )
    assert upload_step is not None
    assert str(upload_step["uses"]).startswith("actions/upload-artifact@")
    assert upload_step["with"]["name"] == "agentflow-api-sbom-cyclonedx"
    assert upload_step["with"]["path"] == ".artifacts/trivy/agentflow-api.cdx.json"
    assert upload_step["with"]["if-no-files-found"] == "error"


def test_trivy_and_iac_jobs_prepare_canonical_artifact_directory() -> None:
    for job_name in ("trivy", "iac"):
        steps = _job(job_name)["steps"]
        prepare = _prepare_step_indexes(steps)
        assert prepare, f"{job_name} must create {TRIVY_ARTIFACT_DIR} before writers"
        writer = next(index for index, step in enumerate(steps) if _is_trivy_writer(step))
        assert prepare[0] < writer, f"{job_name} must mkdir before the first Trivy writer"


def test_all_trivy_outputs_and_consumers_live_under_canonical_directory() -> None:
    found: set[str] = set()
    for job_name in ("trivy", "iac"):
        for step in _job(job_name)["steps"]:
            with_block = step.get("with") or {}
            uses = str(step.get("uses", ""))
            if uses.startswith(TRIVY_ACTION_PREFIX) and "output" in with_block:
                found.add(with_block["output"])
            if uses.startswith("actions/upload-artifact@") and "path" in with_block:
                found.add(with_block["path"])
            if uses.startswith("github/codeql-action/upload-sarif@") and "sarif_file" in with_block:
                found.add(with_block["sarif_file"])
            run = step.get("run")
            if not isinstance(run, str) or EVALUATOR not in run:
                continue
            for token in run.split():
                if token.startswith(f"{TRIVY_ARTIFACT_DIR}/") or token.endswith(
                    (
                        "trivy-api.json",
                        "trivy-flink.json",
                        "trivy-api-policy.json",
                        "trivy-flink-policy.json",
                    )
                ):
                    found.add(token)

    assert found == CANONICAL_TRIVY_OUTPUTS
    assert all(path.startswith(f"{TRIVY_ARTIFACT_DIR}/") for path in found)
