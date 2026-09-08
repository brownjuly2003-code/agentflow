import hashlib
import json
from pathlib import Path

import pytest

from scripts.verify_image_promotion import (
    emit_github_outputs,
    verify_promotion_packet,
    write_staging_promotion_evidence,
)

IMAGE_REF = "ghcr.io/example/agentflow-api"
IMAGE_DIGEST = "sha256:" + "d" * 64
IMAGE_SUBJECT = f"{IMAGE_REF}@{IMAGE_DIGEST}"
SOURCE_SHA = "c" * 40
BUILD_RUN_ID = "123456"


def _manifest(subject: str = IMAGE_SUBJECT) -> str:
    return f"""---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: agentflow
spec:
  template:
    spec:
      containers:
        - name: agentflow
          image: \"{subject}\"
"""


def _packet(manifest: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "source": {"git_sha": SOURCE_SHA},
        "build": {"workflow": "container-attestation", "run_id": BUILD_RUN_ID},
        "image": {
            "repository": IMAGE_REF,
            "digest": IMAGE_DIGEST,
            "subject": IMAGE_SUBJECT,
        },
        "helm": {
            "values": "image-values.yaml",
            "manifest": "helm-deployment.yaml",
            "manifest_sha256": hashlib.sha256(manifest.encode("utf-8")).hexdigest(),
            "version": "v3.16.3+gcfd07493f46ef3b4e2d5cb15ae14401cc50a0937",
        },
        "generator": {"python": "3.11.9"},
        "scope": {
            "proves": ["the Helm API deployment references the workflow-built image digest"],
            "does_not_prove": ["staging rollout", "production acceptance"],
        },
    }


def _write_packet(directory: Path) -> None:
    manifest = _manifest()
    directory.mkdir()
    (directory / "image-values.yaml").write_text(
        f'image:\n  repository: "{IMAGE_REF}"\n  digest: "{IMAGE_DIGEST}"\n',
        encoding="utf-8",
        newline="\n",
    )
    (directory / "helm-deployment.yaml").write_text(
        manifest,
        encoding="utf-8",
        newline="\n",
    )
    (directory / "promotion.json").write_text(
        json.dumps(_packet(manifest), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _verify(directory: Path):
    return verify_promotion_packet(
        packet_dir=directory,
        expected_run_id=BUILD_RUN_ID,
        expected_source_sha=SOURCE_SHA,
        allowed_image_ref=IMAGE_REF,
    )


def test_verifies_exact_three_file_packet_and_emits_sanitized_outputs(tmp_path: Path) -> None:
    packet_dir = tmp_path / "packet"
    _write_packet(packet_dir)

    verified = _verify(packet_dir)
    github_output = tmp_path / "github-output.txt"
    emit_github_outputs(verified, github_output)

    assert verified.image_subject == IMAGE_SUBJECT
    assert verified.values_path == (packet_dir / "image-values.yaml").resolve()
    assert verified.manifest_sha256 == _packet(_manifest())["helm"]["manifest_sha256"]
    assert (
        verified.packet_sha256
        == hashlib.sha256((packet_dir / "promotion.json").read_bytes()).hexdigest()
    )
    assert github_output.read_text(encoding="utf-8").splitlines() == [
        f"image_subject={IMAGE_SUBJECT}",
        f"image_repository={IMAGE_REF}",
        f"image_digest={IMAGE_DIGEST}",
        f"promotion_values_file={(packet_dir / 'image-values.yaml').resolve()}",
        f"promotion_packet_sha256={verified.packet_sha256}",
    ]


@pytest.mark.parametrize(
    ("field_path", "value", "message"),
    [
        (("schema_version",), 2, "schema_version"),
        (("build", "workflow"), "other-workflow", "workflow"),
        (("build", "run_id"), "999", "run_id"),
        (("source", "git_sha"), "a" * 40, "git_sha"),
        (("image", "repository"), "ghcr.io/attacker/image", "repository"),
        (("image", "digest"), "sha256:ABC", "digest"),
        (("image", "subject"), f"{IMAGE_REF}@sha256:{'e' * 64}", "subject"),
        (("helm", "values"), "../image-values.yaml", "values"),
        (("helm", "manifest"), "other.yaml", "manifest"),
        (("helm", "version"), "v3.17.0", "version"),
    ],
)
def test_rejects_packet_identity_or_schema_drift(
    tmp_path: Path,
    field_path: tuple[str, ...],
    value: object,
    message: str,
) -> None:
    packet_dir = tmp_path / "packet"
    _write_packet(packet_dir)
    packet_path = packet_dir / "promotion.json"
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    target = packet
    for key in field_path[:-1]:
        target = target[key]
    target[field_path[-1]] = value
    packet_path.write_text(
        json.dumps(packet, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    with pytest.raises(ValueError, match=message):
        _verify(packet_dir)


@pytest.mark.parametrize("tamper", ["manifest", "values", "extra-file", "duplicate-key"])
def test_rejects_packet_file_tampering(tmp_path: Path, tamper: str) -> None:
    packet_dir = tmp_path / "packet"
    _write_packet(packet_dir)

    if tamper == "manifest":
        (packet_dir / "helm-deployment.yaml").write_text(
            _manifest(f"{IMAGE_REF}@sha256:{'e' * 64}"), encoding="utf-8", newline="\n"
        )
    elif tamper == "values":
        (packet_dir / "image-values.yaml").write_text(
            f'image:\n  repository: "{IMAGE_REF}"\n  digest: "{IMAGE_DIGEST}"\n  tag: latest\n',
            encoding="utf-8",
            newline="\n",
        )
    elif tamper == "extra-file":
        (packet_dir / "unexpected.txt").write_text("unexpected\n", encoding="utf-8")
    else:
        packet_path = packet_dir / "promotion.json"
        packet_path.write_text(
            packet_path.read_text(encoding="utf-8").replace(
                '"schema_version": 1,', '"schema_version": 1,\n  "schema_version": 1,'
            ),
            encoding="utf-8",
            newline="\n",
        )

    with pytest.raises(ValueError):
        _verify(packet_dir)


def test_staging_evidence_hashes_external_verification_and_stays_staging_only(
    tmp_path: Path,
) -> None:
    packet_dir = tmp_path / "packet"
    _write_packet(packet_dir)
    verified = _verify(packet_dir)
    cosign_result = tmp_path / "cosign-verify.json"
    provenance_result = tmp_path / "github-attestation.json"
    cosign_result.write_text('[{"critical": {"identity": {}}}]\n', encoding="utf-8")
    provenance_result.write_text(
        '[{"verificationResult": {"statement": {"predicateType": '
        '"https://slsa.dev/provenance/v1"}}}]\n',
        encoding="utf-8",
    )

    evidence_path = tmp_path / "staging-promotion.json"
    evidence = write_staging_promotion_evidence(
        verified=verified,
        staging_run_id="654321",
        cosign_result_path=cosign_result,
        provenance_result_path=provenance_result,
        output_path=evidence_path,
    )

    assert json.loads(evidence_path.read_text(encoding="utf-8")) == evidence
    assert evidence["image"]["subject"] == IMAGE_SUBJECT
    assert evidence["staging"] == {
        "workflow": "staging-deploy",
        "run_id": "654321",
        "result": "smoke_and_e2e_passed",
    }
    assert (
        evidence["verification"]["cosign"]["sha256"]
        == hashlib.sha256(cosign_result.read_bytes()).hexdigest()
    )
    assert (
        evidence["verification"]["github_build_provenance"]["sha256"]
        == hashlib.sha256(provenance_result.read_bytes()).hexdigest()
    )
    assert "production rollout" in evidence["scope"]["does_not_prove"]
    assert "production acceptance" in evidence["scope"]["does_not_prove"]
    assert "complete F-19 closure" in evidence["scope"]["does_not_prove"]
