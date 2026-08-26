from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_workflow() -> dict:
    path = PROJECT_ROOT / ".github" / "workflows" / "staging-deploy.yml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_staging_requires_an_explicit_successful_container_build_run() -> None:
    workflow = _load_workflow()
    dispatch = workflow["on"]["workflow_dispatch"]
    inputs = dispatch["inputs"]
    job = workflow["jobs"]["staging"]
    validate = next(
        step for step in job["steps"] if step.get("name") == "Validate selected build run"
    )
    script = validate["with"]["script"]

    assert "push" not in workflow["on"]
    for name in ("build_run_id", "source_sha", "confirm"):
        assert inputs[name]["required"] is True
    assert job["if"] == "${{ inputs.confirm == 'PROMOTE' }}"
    assert job["environment"] == "staging"
    assert workflow["permissions"] == {
        "actions": "read",
        "attestations": "read",
        "contents": "read",
        "packages": "read",
    }
    assert validate["env"] == {
        "BUILD_RUN_ID": "${{ inputs.build_run_id }}",
        "SOURCE_SHA": "${{ inputs.source_sha }}",
    }
    for contract in (
        "getWorkflowRun",
        "listJobsForWorkflowRun",
        "workflow_dispatch",
        ".github/workflows/container-attestation.yml",
        "completed",
        "success",
        "head_sha",
        "head_branch",
        "main",
        "build-push-sign-attest",
    ):
        assert contract in script
    assert "${{ inputs." not in script


def test_staging_downloads_and_verifies_the_exact_packet_before_kind() -> None:
    workflow = _load_workflow()
    steps = workflow["jobs"]["staging"]["steps"]
    validate_run = next(step for step in steps if step.get("name") == "Validate selected build run")
    checkout = next(
        step for step in steps if str(step.get("uses", "")).startswith("actions/checkout@")
    )
    download = next(
        step for step in steps if str(step.get("uses", "")).startswith("actions/download-artifact@")
    )
    verify_packet = next(step for step in steps if step.get("name") == "Validate promotion packet")
    verify_subject = next(
        step for step in steps if step.get("name") == "Verify image signature and build provenance"
    )
    kind = next(step for step in steps if str(step.get("uses", "")).startswith("helm/kind-action@"))

    assert checkout["with"]["ref"] == "${{ inputs.source_sha }}"
    assert download["with"] == {
        "name": "agentflow-image-promotion-${{ inputs.source_sha }}",
        "path": ".artifacts/image-promotion",
        "github-token": "${{ github.token }}",
        "run-id": "${{ inputs.build_run_id }}",
    }
    assert verify_packet["id"] == "promotion"
    assert verify_packet["env"] == {
        "ALLOWED_IMAGE_REF": "ghcr.io/${{ github.repository_owner }}/agentflow-api",
        "BUILD_RUN_ID": "${{ inputs.build_run_id }}",
        "SOURCE_SHA": "${{ inputs.source_sha }}",
    }
    assert "scripts/verify_image_promotion.py" in verify_packet["run"]
    assert "${{ inputs." not in verify_packet["run"]

    signature_script = verify_subject["run"]
    assert "cosign verify" in signature_script
    assert "--certificate-identity" in signature_script
    assert "gh attestation verify" in signature_script
    assert "--signer-workflow" in signature_script
    assert "--source-digest" in signature_script
    assert "--source-ref" in signature_script
    assert "--deny-self-hosted-runners" in signature_script
    assert "${{ inputs." not in signature_script

    assert steps.index(validate_run) < steps.index(checkout)
    assert steps.index(checkout) < steps.index(download) < steps.index(verify_packet)
    assert steps.index(verify_packet) < steps.index(verify_subject) < steps.index(kind)


def test_staging_deploys_promotion_values_without_rebuild_and_keeps_e2e_evidence() -> None:
    workflow = _load_workflow()
    job = workflow["jobs"]["staging"]
    steps = job["steps"]
    deploy = next(step for step in steps if step.get("name") == "Deploy promoted digest to staging")
    record = next(step for step in steps if step.get("name") == "Record staging promotion evidence")
    upload = next(
        step for step in steps if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    )
    teardown = next(step for step in steps if step.get("name") == "Tear down staging")
    steps_text = yaml.safe_dump(steps)

    assert deploy["env"] == {
        "PROMOTION_VALUES_FILE": "${{ steps.promotion.outputs.promotion_values_file }}"
    }
    assert deploy["run"] == "bash scripts/k8s_staging_up.sh"
    assert "docker build" not in steps_text
    assert "kind load" not in steps_text
    assert "test_rate_limit_returns_429_after_threshold" in steps_text
    assert "not test_rate_limit_returns_429_after_threshold" in steps_text
    assert teardown["if"] == "always()"
    assert steps.index(teardown) < steps.index(record) < steps.index(upload)
    assert "scripts/verify_image_promotion.py" in record["run"]
    assert "--staging-run-id" in record["run"]
    assert upload["with"]["name"] == (
        "agentflow-staging-promotion-${{ inputs.source_sha }}-${{ github.run_id }}"
    )
    assert upload["with"]["if-no-files-found"] == "error"


def test_workflow_dispatch_inputs_never_enter_shell_source() -> None:
    workflow = _load_workflow()

    for step in workflow["jobs"]["staging"]["steps"]:
        if "run" in step:
            assert "${{ inputs." not in step["run"]
