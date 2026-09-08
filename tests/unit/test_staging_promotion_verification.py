import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.verify_staging_promotion import (
    emit_production_github_outputs,
    verify_staging_promotion,
)

IMAGE_REF = "ghcr.io/example/agentflow-api"
IMAGE_DIGEST = "sha256:" + "d" * 64
IMAGE_SUBJECT = f"{IMAGE_REF}@{IMAGE_DIGEST}"
SOURCE_SHA = "c" * 40
BUILD_RUN_ID = "123456"
STAGING_RUN_ID = "654321"
GITHUB_REPOSITORY = "example/agentflow"
SIGNER = (
    "https://github.com/example/agentflow/"
    ".github/workflows/container-attestation.yml@refs/heads/main"
)
ARTIFACT_NAME = f"agentflow-staging-promotion-{SOURCE_SHA}-{STAGING_RUN_ID}"
ARTIFACT_DIGEST = "sha256:" + "a" * 64
ARTIFACT_EXPIRES_AT = "2026-09-09T19:29:48Z"
VERIFICATION_TIME = datetime(2026, 8, 26, 19, 30, tzinfo=UTC)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _cosign_result() -> list[dict[str, object]]:
    return [
        {
            "critical": {
                "identity": {"docker-reference": IMAGE_REF},
                "image": {"docker-manifest-digest": IMAGE_DIGEST},
                "type": "cosign container image signature",
            },
            "optional": {
                "Issuer": "https://token.actions.githubusercontent.com",
                "Subject": SIGNER,
                "githubWorkflowName": "Container Attestation",
                "githubWorkflowRef": "refs/heads/main",
                "githubWorkflowRepository": GITHUB_REPOSITORY,
                "githubWorkflowSha": SOURCE_SHA,
                "githubWorkflowTrigger": "workflow_dispatch",
            },
        }
    ]


def _provenance_result() -> list[dict[str, object]]:
    repository_url = f"https://github.com/{GITHUB_REPOSITORY}"
    invocation = f"{repository_url}/actions/runs/{BUILD_RUN_ID}/attempts/1"
    workflow = {
        "path": ".github/workflows/container-attestation.yml",
        "ref": "refs/heads/main",
        "repository": repository_url,
    }
    return [
        {
            "verificationResult": {
                "signature": {
                    "certificate": {
                        "subjectAlternativeName": SIGNER,
                        "issuer": "https://token.actions.githubusercontent.com",
                        "githubWorkflowTrigger": "workflow_dispatch",
                        "githubWorkflowSHA": SOURCE_SHA,
                        "githubWorkflowName": "Container Attestation",
                        "githubWorkflowRepository": GITHUB_REPOSITORY,
                        "githubWorkflowRef": "refs/heads/main",
                        "buildSignerURI": SIGNER,
                        "buildSignerDigest": SOURCE_SHA,
                        "runnerEnvironment": "github-hosted",
                        "sourceRepositoryURI": repository_url,
                        "sourceRepositoryDigest": SOURCE_SHA,
                        "sourceRepositoryRef": "refs/heads/main",
                        "buildConfigURI": SIGNER,
                        "buildConfigDigest": SOURCE_SHA,
                        "buildTrigger": "workflow_dispatch",
                        "runInvocationURI": invocation,
                    }
                },
                "statement": {
                    "_type": "https://in-toto.io/Statement/v1",
                    "subject": [
                        {
                            "name": IMAGE_REF,
                            "digest": {"sha256": IMAGE_DIGEST.removeprefix("sha256:")},
                        }
                    ],
                    "predicateType": "https://slsa.dev/provenance/v1",
                    "predicate": {
                        "buildDefinition": {
                            "buildType": "https://actions.github.io/buildtypes/workflow/v1",
                            "externalParameters": {"workflow": workflow},
                            "internalParameters": {
                                "github": {
                                    "event_name": "workflow_dispatch",
                                    "runner_environment": "github-hosted",
                                }
                            },
                            "resolvedDependencies": [
                                {
                                    "uri": (f"git+{repository_url}@refs/heads/main"),
                                    "digest": {"gitCommit": SOURCE_SHA},
                                }
                            ],
                        },
                        "runDetails": {
                            "builder": {"id": SIGNER},
                            "metadata": {"invocationId": invocation},
                        },
                    },
                },
            }
        }
    ]


def _evidence(cosign_path: Path, provenance_path: Path) -> dict[str, object]:
    return {
        "schema_version": 1,
        "source": {"git_sha": SOURCE_SHA},
        "build": {"workflow": "container-attestation", "run_id": BUILD_RUN_ID},
        "image": {
            "repository": IMAGE_REF,
            "digest": IMAGE_DIGEST,
            "subject": IMAGE_SUBJECT,
        },
        "promotion_packet": {
            "sha256": "b" * 64,
            "manifest_sha256": "e" * 64,
        },
        "verification": {
            "cosign": {"file": cosign_path.name, "sha256": _sha256(cosign_path)},
            "github_build_provenance": {
                "file": provenance_path.name,
                "sha256": _sha256(provenance_path),
            },
        },
        "staging": {
            "workflow": "staging-deploy",
            "run_id": STAGING_RUN_ID,
            "result": "smoke_and_e2e_passed",
        },
        "scope": {
            "proves": ["the selected digest passed the staging smoke and E2E gates"],
            "does_not_prove": [
                "production rollout",
                "production acceptance",
                "complete F-19 closure",
            ],
        },
    }


def _write_evidence(
    directory: Path,
    *,
    cosign: list[dict[str, object]] | None = None,
    provenance: list[dict[str, object]] | None = None,
) -> None:
    directory.mkdir()
    cosign_path = directory / "cosign-verify.json"
    provenance_path = directory / "github-attestation.json"
    _write_json(cosign_path, cosign if cosign is not None else _cosign_result())
    _write_json(
        provenance_path,
        provenance if provenance is not None else _provenance_result(),
    )
    _write_json(directory / "staging-promotion.json", _evidence(cosign_path, provenance_path))


def _verify(directory: Path, **patch: object):
    arguments = {
        "evidence_dir": directory,
        "expected_staging_run_id": STAGING_RUN_ID,
        "expected_source_sha": SOURCE_SHA,
        "allowed_image_ref": IMAGE_REF,
        "expected_github_repository": GITHUB_REPOSITORY,
        "artifact_name": ARTIFACT_NAME,
        "artifact_digest": ARTIFACT_DIGEST,
        "artifact_expires_at": ARTIFACT_EXPIRES_AT,
        "verification_time": VERIFICATION_TIME,
    }
    arguments.update(patch)
    return verify_staging_promotion(**arguments)


def test_verifies_exact_staging_evidence_and_emits_sanitized_outputs(
    tmp_path: Path,
) -> None:
    evidence_dir = tmp_path / "evidence"
    _write_evidence(evidence_dir)

    verified = _verify(evidence_dir)
    github_output = tmp_path / "github-output.txt"
    emit_production_github_outputs(verified, github_output)

    assert verified.staging_run_id == STAGING_RUN_ID
    assert verified.build_run_id == BUILD_RUN_ID
    assert verified.image_subject == IMAGE_SUBJECT
    assert verified.artifact_digest == ARTIFACT_DIGEST
    assert verified.evidence_sha256 == _sha256(evidence_dir / "staging-promotion.json")
    assert github_output.read_text(encoding="utf-8").splitlines() == [
        f"build_run_id={BUILD_RUN_ID}",
        f"image_subject={IMAGE_SUBJECT}",
        f"image_repository={IMAGE_REF}",
        f"image_digest={IMAGE_DIGEST}",
        f"cosign_result_file={(evidence_dir / 'cosign-verify.json').resolve()}",
        f"provenance_result_file={(evidence_dir / 'github-attestation.json').resolve()}",
        f"staging_evidence_sha256={verified.evidence_sha256}",
    ]


@pytest.mark.parametrize(
    ("field_path", "value", "message"),
    [
        (("schema_version",), 2, "schema_version"),
        (("source", "git_sha"), "a" * 40, "source.git_sha"),
        (("build", "workflow"), "other", "build.workflow"),
        (("build", "run_id"), "0", "build.run_id"),
        (("image", "repository"), "ghcr.io/attacker/image", "image.repository"),
        (("image", "digest"), "sha256:ABC", "image.digest"),
        (("image", "subject"), f"{IMAGE_REF}@sha256:{'f' * 64}", "image.subject"),
        (("promotion_packet", "sha256"), "invalid", "promotion_packet.sha256"),
        (("verification", "cosign", "file"), "../cosign.json", "cosign.file"),
        (("staging", "workflow"), "other", "staging.workflow"),
        (("staging", "run_id"), "999", "staging.run_id"),
        (("staging", "result"), "failed", "staging.result"),
        (("scope", "proves"), ["production rollout"], "scope"),
    ],
)
def test_rejects_staging_identity_schema_or_scope_drift(
    tmp_path: Path,
    field_path: tuple[str, ...],
    value: object,
    message: str,
) -> None:
    evidence_dir = tmp_path / "evidence"
    _write_evidence(evidence_dir)
    evidence_path = evidence_dir / "staging-promotion.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    target = evidence
    for key in field_path[:-1]:
        target = target[key]
    target[field_path[-1]] = value
    _write_json(evidence_path, evidence)

    with pytest.raises(ValueError, match=message):
        _verify(evidence_dir)


@pytest.mark.parametrize(
    "tamper",
    ["cosign-bytes", "provenance-bytes", "extra-file", "missing-file", "duplicate-key"],
)
def test_rejects_staging_evidence_file_tampering(tmp_path: Path, tamper: str) -> None:
    evidence_dir = tmp_path / "evidence"
    _write_evidence(evidence_dir)

    if tamper == "cosign-bytes":
        path = evidence_dir / "cosign-verify.json"
        path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    elif tamper == "provenance-bytes":
        path = evidence_dir / "github-attestation.json"
        path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    elif tamper == "extra-file":
        (evidence_dir / "unexpected.txt").write_text("unexpected\n", encoding="utf-8")
    elif tamper == "missing-file":
        (evidence_dir / "cosign-verify.json").unlink()
    else:
        path = evidence_dir / "staging-promotion.json"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                '"schema_version": 1,',
                '"schema_version": 1,\n  "schema_version": 1,',
            ),
            encoding="utf-8",
            newline="\n",
        )

    with pytest.raises(ValueError):
        _verify(evidence_dir)


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("cosign-digest", "cosign image digest"),
        ("cosign-signer", "cosign signer"),
        ("cosign-source", "cosign source SHA"),
        ("provenance-digest", "provenance subject"),
        ("provenance-workflow", "provenance workflow"),
        ("provenance-runner", "provenance runner"),
        ("provenance-run", "provenance invocation"),
    ],
)
def test_rejects_unbound_cosign_or_provenance_result(
    tmp_path: Path,
    case: str,
    message: str,
) -> None:
    cosign = _cosign_result()
    provenance = _provenance_result()
    if case == "cosign-digest":
        cosign[0]["critical"]["image"]["docker-manifest-digest"] = "sha256:" + "f" * 64
    elif case == "cosign-signer":
        cosign[0]["optional"]["Subject"] = "https://github.com/attacker/workflow"
    elif case == "cosign-source":
        cosign[0]["optional"]["githubWorkflowSha"] = "a" * 40
    elif case == "provenance-digest":
        provenance[0]["verificationResult"]["statement"]["subject"][0]["digest"]["sha256"] = (
            "f" * 64
        )
    elif case == "provenance-workflow":
        provenance[0]["verificationResult"]["statement"]["predicate"]["buildDefinition"][
            "externalParameters"
        ]["workflow"]["path"] = ".github/workflows/other.yml"
    elif case == "provenance-runner":
        provenance[0]["verificationResult"]["signature"]["certificate"]["runnerEnvironment"] = (
            "self-hosted"
        )
    else:
        provenance[0]["verificationResult"]["signature"]["certificate"]["runInvocationURI"] = (
            "https://github.com/example/agentflow/actions/runs/999/attempts/1"
        )

    evidence_dir = tmp_path / "evidence"
    _write_evidence(evidence_dir, cosign=cosign, provenance=provenance)

    with pytest.raises(ValueError, match=message):
        _verify(evidence_dir)


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ({"artifact_name": "other"}, "artifact_name"),
        ({"artifact_digest": "sha256:ABC"}, "artifact_digest"),
        ({"artifact_expires_at": "not-a-time"}, "artifact_expires_at"),
        ({"artifact_expires_at": "2026-08-26T19:29:59Z"}, "expired"),
        ({"expected_staging_run_id": "0"}, "expected_staging_run_id"),
        ({"expected_github_repository": "not-a-repository"}, "repository"),
    ],
)
def test_rejects_unverifiable_artifact_or_expected_identity(
    tmp_path: Path,
    patch: dict[str, object],
    message: str,
) -> None:
    evidence_dir = tmp_path / "evidence"
    _write_evidence(evidence_dir)

    with pytest.raises(ValueError, match=message):
        _verify(evidence_dir, **patch)
