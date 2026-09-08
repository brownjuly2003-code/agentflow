#!/usr/bin/env python3
"""Fail-closed verification and staging evidence for an image promotion packet."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

IMAGE_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
IMAGE_REF_RE = re.compile(
    r"[a-z0-9]+(?:[._-][a-z0-9]+)*(?::[0-9]+)?/"
    r"[a-z0-9]+(?:[._/-][a-z0-9]+)*"
)
SOURCE_SHA_RE = re.compile(r"[0-9a-f]{40}")
RUN_ID_RE = re.compile(r"[1-9][0-9]*")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
HELM_VERSION_RE = re.compile(r"v3\.16\.3(?:\+[0-9A-Za-z.-]+)?")
PYTHON_VERSION_RE = re.compile(r"3\.(?:11|12|13)\.[0-9]+")

PACKET_FILES = frozenset({"image-values.yaml", "helm-deployment.yaml", "promotion.json"})
PACKET_SCOPE = {
    "proves": ["the Helm API deployment references the workflow-built image digest"],
    "does_not_prove": ["staging rollout", "production acceptance"],
}


@dataclass(frozen=True)
class VerifiedPromotion:
    packet_dir: Path
    values_path: Path
    source_sha: str
    build_run_id: str
    image_repository: str
    image_digest: str
    image_subject: str
    manifest_sha256: str
    packet_sha256: str


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON file: {path.name}") from exc


def _object(value: Any, *, name: str, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    actual = set(value)
    if actual != keys:
        raise ValueError(
            f"{name} keys differ: missing={sorted(keys - actual)}, extra={sorted(actual - keys)}"
        )
    return value


def _string(value: Any, *, name: str, pattern: re.Pattern[str] | None = None) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise ValueError(f"{name} has an invalid value")
    return value


def _validate_expected_identity(
    *, expected_run_id: str, expected_source_sha: str, allowed_image_ref: str
) -> None:
    _string(expected_run_id, name="expected_run_id", pattern=RUN_ID_RE)
    _string(expected_source_sha, name="expected_source_sha", pattern=SOURCE_SHA_RE)
    _string(allowed_image_ref, name="allowed_image_ref", pattern=IMAGE_REF_RE)


def _validate_packet_files(packet_dir: Path) -> None:
    if not packet_dir.is_dir():
        raise ValueError(f"packet_dir is not a directory: {packet_dir}")
    entries = {entry.name: entry for entry in packet_dir.iterdir()}
    if set(entries) != PACKET_FILES:
        raise ValueError(
            "promotion packet files differ: "
            f"missing={sorted(PACKET_FILES - set(entries))}, "
            f"extra={sorted(set(entries) - PACKET_FILES)}"
        )
    for name, path in entries.items():
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"promotion packet member must be a regular file: {name}")


def _validate_manifest(manifest_text: str, *, subject: str) -> None:
    try:
        documents = [document for document in yaml.safe_load_all(manifest_text) if document]
    except yaml.YAMLError as exc:
        raise ValueError("helm manifest is not valid YAML") from exc
    if len(documents) != 1 or not isinstance(documents[0], dict):
        raise ValueError("helm manifest must contain exactly one object")
    deployment = documents[0]
    if deployment.get("kind") != "Deployment":
        raise ValueError("helm manifest must contain one Deployment")
    try:
        containers = deployment["spec"]["template"]["spec"]["containers"]
    except (KeyError, TypeError) as exc:
        raise ValueError("helm manifest is missing Deployment containers") from exc
    if not isinstance(containers, list) or len(containers) != 1:
        raise ValueError("helm manifest must contain exactly one API container")
    container = containers[0]
    if not isinstance(container, dict) or container.get("name") != "agentflow":
        raise ValueError("helm manifest API container must be named agentflow")
    if container.get("image") != subject:
        raise ValueError("helm manifest does not reference the exact image subject")


def verify_promotion_packet(
    *,
    packet_dir: Path,
    expected_run_id: str,
    expected_source_sha: str,
    allowed_image_ref: str,
) -> VerifiedPromotion:
    """Validate packet structure and identity without mutating a cluster."""

    _validate_expected_identity(
        expected_run_id=expected_run_id,
        expected_source_sha=expected_source_sha,
        allowed_image_ref=allowed_image_ref,
    )
    packet_dir = packet_dir.resolve()
    _validate_packet_files(packet_dir)

    packet_path = packet_dir / "promotion.json"
    packet_bytes = packet_path.read_bytes()
    packet = _object(
        _load_json(packet_path),
        name="promotion",
        keys={"schema_version", "source", "build", "image", "helm", "generator", "scope"},
    )
    if type(packet["schema_version"]) is not int or packet["schema_version"] != 1:
        raise ValueError("schema_version must be 1")

    source = _object(packet["source"], name="source", keys={"git_sha"})
    source_sha = _string(source["git_sha"], name="source.git_sha", pattern=SOURCE_SHA_RE)
    if source_sha != expected_source_sha:
        raise ValueError("source.git_sha does not match the selected source SHA")

    build = _object(packet["build"], name="build", keys={"workflow", "run_id"})
    workflow = _string(build["workflow"], name="build.workflow")
    if workflow != "container-attestation":
        raise ValueError("build.workflow must be container-attestation")
    build_run_id = _string(build["run_id"], name="build.run_id", pattern=RUN_ID_RE)
    if build_run_id != expected_run_id:
        raise ValueError("build.run_id does not match the selected build run")

    image = _object(packet["image"], name="image", keys={"repository", "digest", "subject"})
    repository = _string(image["repository"], name="image.repository", pattern=IMAGE_REF_RE)
    if repository != allowed_image_ref:
        raise ValueError("image.repository does not match the allowed repository")
    digest = _string(image["digest"], name="image.digest", pattern=IMAGE_DIGEST_RE)
    subject = _string(image["subject"], name="image.subject")
    if subject != f"{repository}@{digest}":
        raise ValueError("image.subject does not match repository@digest")

    helm = _object(
        packet["helm"],
        name="helm",
        keys={"values", "manifest", "manifest_sha256", "version"},
    )
    values_name = _string(helm["values"], name="helm.values")
    manifest_name = _string(helm["manifest"], name="helm.manifest")
    if values_name != "image-values.yaml":
        raise ValueError("helm.values must be image-values.yaml")
    if manifest_name != "helm-deployment.yaml":
        raise ValueError("helm.manifest must be helm-deployment.yaml")
    manifest_sha256 = _string(
        helm["manifest_sha256"], name="helm.manifest_sha256", pattern=SHA256_RE
    )
    _string(helm["version"], name="helm.version", pattern=HELM_VERSION_RE)

    generator = _object(packet["generator"], name="generator", keys={"python"})
    _string(generator["python"], name="generator.python", pattern=PYTHON_VERSION_RE)
    if packet["scope"] != PACKET_SCOPE:
        raise ValueError("scope differs from the promotion packet contract")

    values_path = packet_dir / values_name
    expected_values = (
        f"image:\n  repository: {json.dumps(repository)}\n  digest: {json.dumps(digest)}\n"
    )
    if values_path.read_text(encoding="utf-8") != expected_values:
        raise ValueError("image values do not contain only the exact repository and digest")

    manifest_path = packet_dir / manifest_name
    manifest_bytes = manifest_path.read_bytes()
    if _sha256_bytes(manifest_bytes) != manifest_sha256:
        raise ValueError("helm manifest SHA-256 does not match promotion.json")
    try:
        manifest_text = manifest_bytes.decode("utf-8")
    except UnicodeError as exc:
        raise ValueError("helm manifest is not UTF-8") from exc
    _validate_manifest(manifest_text, subject=subject)

    return VerifiedPromotion(
        packet_dir=packet_dir,
        values_path=values_path.resolve(),
        source_sha=source_sha,
        build_run_id=build_run_id,
        image_repository=repository,
        image_digest=digest,
        image_subject=subject,
        manifest_sha256=manifest_sha256,
        packet_sha256=_sha256_bytes(packet_bytes),
    )


def emit_github_outputs(verified: VerifiedPromotion, output_path: Path) -> None:
    lines = [
        f"image_subject={verified.image_subject}",
        f"image_repository={verified.image_repository}",
        f"image_digest={verified.image_digest}",
        f"promotion_values_file={verified.values_path}",
        f"promotion_packet_sha256={verified.packet_sha256}",
    ]
    with output_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")


def _verified_json_result(path: Path, *, name: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{name} result must be a regular file")
    content = path.read_bytes()
    parsed = _load_json(path)
    if not isinstance(parsed, list) or not parsed:
        raise ValueError(f"{name} result must be a non-empty JSON array")
    return content


def write_staging_promotion_evidence(
    *,
    verified: VerifiedPromotion,
    staging_run_id: str,
    cosign_result_path: Path,
    provenance_result_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    _string(staging_run_id, name="staging_run_id", pattern=RUN_ID_RE)
    cosign_bytes = _verified_json_result(cosign_result_path, name="cosign")
    provenance_bytes = _verified_json_result(provenance_result_path, name="provenance")

    evidence: dict[str, Any] = {
        "schema_version": 1,
        "source": {"git_sha": verified.source_sha},
        "build": {"workflow": "container-attestation", "run_id": verified.build_run_id},
        "image": {
            "repository": verified.image_repository,
            "digest": verified.image_digest,
            "subject": verified.image_subject,
        },
        "promotion_packet": {
            "sha256": verified.packet_sha256,
            "manifest_sha256": verified.manifest_sha256,
        },
        "verification": {
            "cosign": {
                "file": cosign_result_path.name,
                "sha256": _sha256_bytes(cosign_bytes),
            },
            "github_build_provenance": {
                "file": provenance_result_path.name,
                "sha256": _sha256_bytes(provenance_bytes),
            },
        },
        "staging": {
            "workflow": "staging-deploy",
            "run_id": staging_run_id,
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
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return evidence


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an immutable image promotion packet.")
    parser.add_argument("--packet-dir", type=Path, required=True)
    parser.add_argument("--expected-run-id", required=True)
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--allowed-image-ref", required=True)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--staging-run-id")
    parser.add_argument("--cosign-result", type=Path)
    parser.add_argument("--provenance-result", type=Path)
    parser.add_argument("--evidence-output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    verified = verify_promotion_packet(
        packet_dir=args.packet_dir,
        expected_run_id=args.expected_run_id,
        expected_source_sha=args.expected_source_sha,
        allowed_image_ref=args.allowed_image_ref,
    )
    if args.github_output is not None:
        emit_github_outputs(verified, args.github_output)

    evidence_arguments = (
        args.staging_run_id,
        args.cosign_result,
        args.provenance_result,
        args.evidence_output,
    )
    if any(argument is not None for argument in evidence_arguments):
        if any(argument is None for argument in evidence_arguments):
            raise ValueError("all staging evidence arguments must be provided together")
        write_staging_promotion_evidence(
            verified=verified,
            staging_run_id=args.staging_run_id,
            cosign_result_path=args.cosign_result,
            provenance_result_path=args.provenance_result,
            output_path=args.evidence_output,
        )

    print(verified.image_subject)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
