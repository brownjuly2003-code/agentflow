from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_workflow() -> dict:
    path = PROJECT_ROOT / ".github" / "workflows" / "container-attestation.yml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_container_attestation_workflow_signs_images_by_digest_only():
    workflow = _load_workflow()
    job = workflow["jobs"]["attest-and-sign"]
    validation = next(step for step in job["steps"] if step.get("name") == "Validate digest inputs")
    validation_script = validation["run"]
    steps_text = yaml.safe_dump(job["steps"])

    assert job["permissions"]["id-token"] == "write"
    assert "attestations" not in job["permissions"]
    assert job["env"] == {
        "IMAGE_REF": "${{ inputs.image_ref }}",
        "IMAGE_DIGEST": "${{ inputs.image_digest }}",
        "ALLOWED_IMAGE_REF": "ghcr.io/${{ github.repository_owner }}/agentflow-api",
    }
    assert workflow["on"]["workflow_dispatch"]["inputs"]["mode"]["required"] is True
    assert workflow["on"]["workflow_dispatch"]["inputs"]["image_digest"]["required"] is False
    assert "^sha256:[0-9a-f]{64}$" in validation_script
    assert "image_ref is required" in steps_text
    assert 'case "$IMAGE_REF"' in validation_script
    assert "*@*)" in validation_script
    assert "*:latest)" in validation_script
    assert '[[ "$IMAGE_REF" != "$ALLOWED_IMAGE_REF" ]]' in validation_script
    assert 'cosign sign --yes "${IMAGE_REF}@${IMAGE_DIGEST}"' in steps_text
    assert "${IMAGE_REF}:${" not in steps_text


def test_existing_digest_job_does_not_claim_build_provenance():
    workflow = _load_workflow()
    steps = workflow["jobs"]["attest-and-sign"]["steps"]
    workflow_text = (
        PROJECT_ROOT / ".github" / "workflows" / "container-attestation.yml"
    ).read_text(encoding="utf-8")

    assert not any(
        str(step.get("uses", "")).startswith("actions/attest-build-provenance@") for step in steps
    )
    assert "did not build" in workflow_text
    assert "must not create build provenance" in workflow_text


def test_workflow_dispatch_inputs_never_enter_shell_source():
    workflow = _load_workflow()

    for job in workflow["jobs"].values():
        for step in job.get("steps", []):
            if isinstance(step, dict) and "run" in step:
                assert "${{ inputs." not in step["run"]


def test_operator_signing_jobs_require_protected_production_environment():
    workflow = _load_workflow()

    for job_name in ("build-push-sign-attest", "attest-and-sign"):
        assert workflow["jobs"][job_name]["environment"] == "production"


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
    # Write scopes live only on operator-dispatched jobs. Build provenance is
    # additionally limited to the job that actually builds the image.
    workflow = _load_workflow()
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["jobs"]["build-push-sign-attest"]["permissions"] == {
        "contents": "read",
        "packages": "write",
        "id-token": "write",
        "attestations": "write",
    }
    assert workflow["jobs"]["attest-and-sign"]["permissions"] == {
        "contents": "read",
        "packages": "write",
        "id-token": "write",
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


def test_built_digest_becomes_checksumed_helm_promotion_evidence():
    workflow = _load_workflow()
    build_job = workflow["jobs"]["build-push-sign-attest"]
    external_job = workflow["jobs"]["attest-and-sign"]
    steps = build_job["steps"]

    setup_helm = next(
        step for step in steps if str(step.get("uses", "")).startswith("azure/setup-helm@")
    )
    generate = next(
        step for step in steps if step.get("name") == "Create immutable Helm promotion evidence"
    )
    upload = next(
        step for step in steps if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    )
    attest = next(
        step
        for step in steps
        if str(step.get("uses", "")).startswith("actions/attest-build-provenance@")
    )

    assert setup_helm["with"]["version"] == "v3.16.3"
    assert generate["env"] == {
        "IMAGE_REF": "${{ env.IMAGE_REF }}",
        "IMAGE_DIGEST": "${{ steps.build.outputs.digest }}",
        "SOURCE_SHA": "${{ github.sha }}",
        "BUILD_RUN_ID": "${{ github.run_id }}",
    }
    assert "scripts/write_image_promotion_evidence.py" in generate["run"]
    assert "${{ inputs." not in generate["run"]
    assert upload["with"] == {
        "name": "agentflow-image-promotion-${{ github.sha }}",
        "path": ".artifacts/image-promotion/",
        "if-no-files-found": "error",
        "retention-days": 14,
    }
    assert steps.index(attest) < steps.index(generate) < steps.index(upload)
    assert not any(
        str(step.get("uses", "")).startswith("actions/upload-artifact@")
        for step in external_job["steps"]
    )
