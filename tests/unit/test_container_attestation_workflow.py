from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_workflow() -> dict:
    path = PROJECT_ROOT / ".github" / "workflows" / "container-attestation.yml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_container_attestation_workflow_signs_images_by_digest_only():
    workflow = _load_workflow()
    job = workflow["jobs"]["attest-and-sign"]
    steps_text = yaml.safe_dump(job["steps"])

    assert workflow["permissions"]["id-token"] == "write"
    assert workflow["permissions"]["attestations"] == "write"
    assert workflow["on"]["workflow_dispatch"]["inputs"]["mode"]["required"] is True
    assert workflow["on"]["workflow_dispatch"]["inputs"]["image_digest"]["required"] is False
    assert "sha256:" in steps_text
    assert "image_ref is required" in steps_text
    assert "cosign sign --yes ${IMAGE_REF}@${IMAGE_DIGEST}" in steps_text
    assert "${IMAGE_REF}:${" not in steps_text


def test_container_attestation_workflow_emits_github_attestation_for_digest():
    workflow = _load_workflow()
    steps = workflow["jobs"]["attest-and-sign"]["steps"]
    attest = next(
        step for step in steps if step.get("uses") == "actions/attest-build-provenance@v2"
    )

    assert attest["with"]["subject-name"] == "${{ inputs.image_ref }}"
    assert attest["with"]["subject-digest"] == "${{ inputs.image_digest }}"
    assert attest["with"]["push-to-registry"] is False


def test_container_attestation_workflow_builds_and_pushes_ghcr_image():
    workflow = _load_workflow()
    job = workflow["jobs"]["build-push-sign-attest"]
    workflow_text = yaml.safe_dump(workflow)
    steps_text = yaml.safe_dump(job["steps"])

    assert workflow["permissions"]["packages"] == "write"
    assert "ghcr.io/${{ github.repository_owner }}/agentflow-api" in workflow_text
    assert "docker/login-action@v3" in steps_text
    assert "docker/build-push-action@v6" in steps_text
    assert "Dockerfile.api" in steps_text
    assert "push: true" in steps_text
    assert "${{ github.sha }}" in steps_text
    assert ":latest" not in steps_text


def test_container_attestation_workflow_signs_and_attests_pushed_digest():
    workflow = _load_workflow()
    steps = workflow["jobs"]["build-push-sign-attest"]["steps"]
    steps_text = yaml.safe_dump(steps)
    attest = next(
        step for step in steps if step.get("uses") == "actions/attest-build-provenance@v2"
    )

    assert "cosign sign --yes ${IMAGE_REF}@${IMAGE_DIGEST}" in steps_text
    assert attest["with"]["subject-name"] == "${{ env.IMAGE_REF }}"
    assert attest["with"]["subject-digest"] == "${{ steps.build.outputs.digest }}"
    assert attest["with"]["push-to-registry"] is True
