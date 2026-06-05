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

    assert job["permissions"]["id-token"] == "write"
    assert job["permissions"]["attestations"] == "write"
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
        step
        for step in steps
        if str(step.get("uses", "")).startswith("actions/attest-build-provenance@")
    )

    assert attest["with"]["subject-name"] == "${{ inputs.image_ref }}"
    assert attest["with"]["subject-digest"] == "${{ inputs.image_digest }}"
    assert attest["with"]["push-to-registry"] is False


def test_container_attestation_workflow_builds_and_pushes_ghcr_image():
    workflow = _load_workflow()
    job = workflow["jobs"]["build-push-sign-attest"]
    workflow_text = yaml.safe_dump(workflow)
    steps_text = yaml.safe_dump(job["steps"])

    assert job["permissions"]["packages"] == "write"
    assert "ghcr.io/${{ github.repository_owner }}/agentflow-api" in workflow_text
    assert "docker/login-action@" in steps_text
    assert "docker/build-push-action@" in steps_text
    assert "Dockerfile.api" in steps_text
    assert "push: true" in steps_text
    assert "${{ github.sha }}" in steps_text
    assert ":latest" not in steps_text

    build_step = next(
        step
        for step in job["steps"]
        if isinstance(step.get("uses"), str)
        and step["uses"].startswith("docker/build-push-action@")
    )
    assert build_step["id"] == "build", (
        "downstream sigstore/attest-build-provenance steps reference steps.build.outputs.digest"
    )
    inputs = build_step["with"]
    assert inputs["context"] == "."
    assert inputs["file"] == "Dockerfile.api"
    assert inputs["push"] is True
    assert "${{ env.IMAGE_REF }}:${{ github.sha }}" in inputs["tags"]
    assert "${{ env.IMAGE_REF }}:audit-${{ github.run_id }}" in inputs["tags"]


def test_container_attestation_top_level_token_is_read_only():
    # The write scopes (packages/id-token/attestations) live on the two
    # operator-dispatched signing jobs only; the every-PR build-smoke job —
    # and anything added later by default — runs with a read-only token
    # (Scorecard Token-Permissions posture).
    workflow = _load_workflow()
    assert workflow["permissions"] == {"contents": "read"}
    for job_name in ("build-push-sign-attest", "attest-and-sign"):
        assert workflow["jobs"][job_name]["permissions"] == {
            "contents": "read",
            "packages": "write",
            "id-token": "write",
            "attestations": "write",
        }
    assert "permissions" not in workflow["jobs"]["build-smoke"]


def test_container_attestation_workflow_runs_smoke_on_pull_request():
    workflow = _load_workflow()
    assert "pull_request" in workflow["on"], (
        "container-attestation must run on PR to catch broken Dockerfiles before merge"
    )
    # build-smoke is a required branch-protection check, so the workflow must
    # trigger on EVERY pull request: a `paths:` filter here would leave
    # non-Docker PRs stuck forever on "Expected — waiting for status" (the
    # `contract` Lessons 1/4 trap). Path-gating lives INSIDE the job instead.
    pr_trigger = workflow["on"]["pull_request"]
    assert not (isinstance(pr_trigger, dict) and "paths" in pr_trigger), (
        "pull_request must not be paths-filtered; a required check has to "
        "complete on every PR — gate the docker build inside the job"
    )

    smoke_job = workflow["jobs"]["build-smoke"]
    assert smoke_job["name"] == "build-smoke", (
        "required-check branch protection depends on a stable PR job context"
    )
    assert "github.event_name == 'pull_request'" in smoke_job["if"]

    steps = smoke_job["steps"]
    changes_step = next(step for step in steps if step.get("id") == "changes")
    run_text = changes_step["run"]
    for tracked in ("Dockerfile", "pyproject", "requirements", "container-attestation"):
        assert tracked in run_text, f"the change-detection step must inspect {tracked!r} paths"
    assert "GITHUB_OUTPUT" in run_text, (
        "change detection must publish a step output the build steps key off"
    )

    build_step = next(
        step
        for step in steps
        if isinstance(step.get("uses"), str)
        and step["uses"].startswith("docker/build-push-action@")
    )
    assert build_step.get("if") == "steps.changes.outputs.docker == 'true'", (
        "the docker build must be conditional so docker-free PRs complete "
        "as an instant skip-success"
    )
    buildx_step = next(
        step
        for step in steps
        if isinstance(step.get("uses"), str)
        and step["uses"].startswith("docker/setup-buildx-action@")
    )
    assert buildx_step.get("if") == "steps.changes.outputs.docker == 'true'", (
        "buildx setup is wasted work on docker-free PRs"
    )

    inputs = build_step["with"]
    assert inputs["push"] is False, "PR smoke must not push to ghcr.io"
    assert inputs["file"] == "Dockerfile.api"
    assert inputs["context"] == "."
    assert "load" in inputs, "load: true is needed so the image lands in the local docker engine"
    assert inputs["load"] is True, "load must literally be True, not a truthy string"


def test_container_attestation_workflow_signs_and_attests_pushed_digest():
    workflow = _load_workflow()
    steps = workflow["jobs"]["build-push-sign-attest"]["steps"]
    steps_text = yaml.safe_dump(steps)
    attest = next(
        step
        for step in steps
        if str(step.get("uses", "")).startswith("actions/attest-build-provenance@")
    )

    assert "cosign sign --yes ${IMAGE_REF}@${IMAGE_DIGEST}" in steps_text
    assert attest["with"]["subject-name"] == "${{ env.IMAGE_REF }}"
    assert attest["with"]["subject-digest"] == "${{ steps.build.outputs.digest }}"
    assert attest["with"]["push-to-registry"] is True
