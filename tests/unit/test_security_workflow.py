from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_security_workflow() -> dict:
    workflow_path = PROJECT_ROOT / ".github" / "workflows" / "security.yml"
    return yaml.safe_load(workflow_path.read_text(encoding="utf-8"))


def test_trivy_job_generates_cyclonedx_sbom_artifact() -> None:
    workflow = _load_security_workflow()
    steps = workflow["jobs"]["trivy"]["steps"]

    sbom_step = next(
        (step for step in steps if step.get("name") == "Generate CycloneDX SBOM"),
        None,
    )
    assert sbom_step is not None
    assert sbom_step["uses"] == "aquasecurity/trivy-action@v0.36.0"
    assert sbom_step["with"] == {
        "image-ref": "agentflow-api:security-scan",
        "format": "cyclonedx",
        "output": "agentflow-api.cdx.json",
    }

    upload_step = next(
        (step for step in steps if step.get("name") == "Upload CycloneDX SBOM"),
        None,
    )
    assert upload_step is not None
    assert upload_step["uses"] == "actions/upload-artifact@v4"
    assert upload_step["with"]["name"] == "agentflow-api-sbom-cyclonedx"
    assert upload_step["with"]["path"] == "agentflow-api.cdx.json"
    assert upload_step["with"]["if-no-files-found"] == "error"
