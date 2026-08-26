#!/usr/bin/env python3
"""Fail-closed verification of staging promotion evidence for production use."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

IMAGE_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
IMAGE_REF_RE = re.compile(
    r"[a-z0-9]+(?:[._-][a-z0-9]+)*(?::[0-9]+)?/"
    r"[a-z0-9]+(?:[._/-][a-z0-9]+)*"
)
SOURCE_SHA_RE = re.compile(r"[0-9a-f]{40}")
RUN_ID_RE = re.compile(r"[1-9][0-9]*")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
GITHUB_REPOSITORY_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
ARTIFACT_EXPIRES_AT_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")

EVIDENCE_FILES = frozenset(
    {"staging-promotion.json", "cosign-verify.json", "github-attestation.json"}
)
STAGING_SCOPE = {
    "proves": ["the selected digest passed the staging smoke and E2E gates"],
    "does_not_prove": [
        "production rollout",
        "production acceptance",
        "complete F-19 closure",
    ],
}
OIDC_ISSUER = "https://token.actions.githubusercontent.com"
WORKFLOW_PATH = ".github/workflows/container-attestation.yml"
WORKFLOW_REF = "refs/heads/main"
WORKFLOW_NAME = "Container Attestation"


@dataclass(frozen=True)
class VerifiedStagingPromotion:
    evidence_dir: Path
    evidence_path: Path
    cosign_result_path: Path
    provenance_result_path: Path
    source_sha: str
    staging_run_id: str
    build_run_id: str
    image_repository: str
    image_digest: str
    image_subject: str
    artifact_name: str
    artifact_digest: str
    artifact_expires_at: str
    evidence_sha256: str


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


def _object(value: Any, *, name: str, keys: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    if keys is not None:
        actual = set(value)
        if actual != keys:
            raise ValueError(
                f"{name} keys differ: "
                f"missing={sorted(keys - actual)}, extra={sorted(actual - keys)}"
            )
    return value


def _string(value: Any, *, name: str, pattern: re.Pattern[str] | None = None) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise ValueError(f"{name} has an invalid value")
    return value


def _value(parent: dict[str, Any], key: str, *, name: str) -> Any:
    if key not in parent:
        raise ValueError(f"{name} is missing")
    return parent[key]


def _parse_expiry(value: str) -> datetime:
    _string(value, name="artifact_expires_at", pattern=ARTIFACT_EXPIRES_AT_RE)
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise ValueError("artifact_expires_at has an invalid value") from exc


def _validate_expected_identity(
    *,
    expected_staging_run_id: str,
    expected_source_sha: str,
    allowed_image_ref: str,
    expected_github_repository: str,
    artifact_name: str,
    artifact_digest: str,
    artifact_expires_at: str,
    verification_time: datetime,
) -> None:
    _string(
        expected_staging_run_id,
        name="expected_staging_run_id",
        pattern=RUN_ID_RE,
    )
    _string(expected_source_sha, name="expected_source_sha", pattern=SOURCE_SHA_RE)
    _string(allowed_image_ref, name="allowed_image_ref", pattern=IMAGE_REF_RE)
    _string(
        expected_github_repository,
        name="expected_github_repository",
        pattern=GITHUB_REPOSITORY_RE,
    )
    expected_artifact_name = (
        f"agentflow-staging-promotion-{expected_source_sha}-{expected_staging_run_id}"
    )
    if artifact_name != expected_artifact_name:
        raise ValueError("artifact_name does not match the selected staging run and source SHA")
    _string(artifact_digest, name="artifact_digest", pattern=IMAGE_DIGEST_RE)
    expiry = _parse_expiry(artifact_expires_at)
    if verification_time.tzinfo is None or verification_time.utcoffset() is None:
        raise ValueError("verification_time must be timezone-aware")
    if expiry <= verification_time.astimezone(UTC):
        raise ValueError("staging promotion artifact is expired")


def _validate_evidence_files(evidence_dir: Path) -> Path:
    if evidence_dir.is_symlink() or not evidence_dir.is_dir():
        raise ValueError(f"evidence_dir is not a regular directory: {evidence_dir}")
    evidence_dir = evidence_dir.resolve()
    entries = {entry.name: entry for entry in evidence_dir.iterdir()}
    if set(entries) != EVIDENCE_FILES:
        raise ValueError(
            "staging evidence files differ: "
            f"missing={sorted(EVIDENCE_FILES - set(entries))}, "
            f"extra={sorted(set(entries) - EVIDENCE_FILES)}"
        )
    for name, path in entries.items():
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"staging evidence member must be a regular file: {name}")
    return evidence_dir


def _verify_cosign_result(
    path: Path,
    *,
    image_repository: str,
    image_digest: str,
    source_sha: str,
    github_repository: str,
    signer: str,
) -> None:
    result = _load_json(path)
    if not isinstance(result, list) or len(result) != 1:
        raise ValueError("cosign result must contain exactly one verification record")
    record = _object(result[0], name="cosign record")
    critical = _object(_value(record, "critical", name="cosign critical"), name="cosign critical")
    identity = _object(_value(critical, "identity", name="cosign identity"), name="cosign identity")
    if identity.get("docker-reference") != image_repository:
        raise ValueError("cosign image repository does not match staging evidence")
    image = _object(_value(critical, "image", name="cosign image"), name="cosign image")
    if image.get("docker-manifest-digest") != image_digest:
        raise ValueError("cosign image digest does not match staging evidence")
    if critical.get("type") != "cosign container image signature":
        raise ValueError("cosign signature type is invalid")

    optional = _object(_value(record, "optional", name="cosign optional"), name="cosign optional")
    if optional.get("Issuer") != OIDC_ISSUER:
        raise ValueError("cosign issuer does not match the GitHub OIDC issuer")
    if optional.get("Subject") != signer:
        raise ValueError("cosign signer does not match the build workflow")
    if optional.get("githubWorkflowSha") != source_sha:
        raise ValueError("cosign source SHA does not match staging evidence")
    expected = {
        "githubWorkflowName": WORKFLOW_NAME,
        "githubWorkflowRef": WORKFLOW_REF,
        "githubWorkflowRepository": github_repository,
        "githubWorkflowTrigger": "workflow_dispatch",
    }
    for key, value in expected.items():
        if optional.get(key) != value:
            raise ValueError(f"cosign {key} does not match the build workflow")


def _verify_provenance_result(
    path: Path,
    *,
    image_repository: str,
    image_digest: str,
    source_sha: str,
    build_run_id: str,
    github_repository: str,
    signer: str,
) -> None:
    result = _load_json(path)
    if not isinstance(result, list) or len(result) != 1:
        raise ValueError("provenance result must contain exactly one verification record")
    record = _object(result[0], name="provenance record")
    verification = _object(
        _value(record, "verificationResult", name="provenance verificationResult"),
        name="provenance verificationResult",
    )
    signature = _object(
        _value(verification, "signature", name="provenance signature"),
        name="provenance signature",
    )
    certificate = _object(
        _value(signature, "certificate", name="provenance certificate"),
        name="provenance certificate",
    )
    repository_url = f"https://github.com/{github_repository}"
    invocation_pattern = re.compile(
        re.escape(f"{repository_url}/actions/runs/{build_run_id}/attempts/") + r"[1-9][0-9]*"
    )
    if certificate.get("runnerEnvironment") != "github-hosted":
        raise ValueError("provenance runner must be github-hosted")
    invocation = certificate.get("runInvocationURI")
    if not isinstance(invocation, str) or invocation_pattern.fullmatch(invocation) is None:
        raise ValueError("provenance invocation does not match the build run")
    certificate_expected = {
        "subjectAlternativeName": signer,
        "issuer": OIDC_ISSUER,
        "githubWorkflowTrigger": "workflow_dispatch",
        "githubWorkflowSHA": source_sha,
        "githubWorkflowName": WORKFLOW_NAME,
        "githubWorkflowRepository": github_repository,
        "githubWorkflowRef": WORKFLOW_REF,
        "buildSignerURI": signer,
        "buildSignerDigest": source_sha,
        "sourceRepositoryURI": repository_url,
        "sourceRepositoryDigest": source_sha,
        "sourceRepositoryRef": WORKFLOW_REF,
        "buildConfigURI": signer,
        "buildConfigDigest": source_sha,
        "buildTrigger": "workflow_dispatch",
    }
    for key, value in certificate_expected.items():
        if certificate.get(key) != value:
            raise ValueError(f"provenance certificate {key} does not match the build")

    statement = _object(
        _value(verification, "statement", name="provenance statement"),
        name="provenance statement",
    )
    if statement.get("_type") != "https://in-toto.io/Statement/v1":
        raise ValueError("provenance statement type is invalid")
    if statement.get("predicateType") != "https://slsa.dev/provenance/v1":
        raise ValueError("provenance predicate type is invalid")
    subjects = statement.get("subject")
    if not isinstance(subjects, list) or len(subjects) != 1:
        raise ValueError("provenance subject must contain exactly one image")
    subject = _object(subjects[0], name="provenance subject")
    if subject.get("name") != image_repository or subject.get("digest") != {
        "sha256": image_digest.removeprefix("sha256:")
    }:
        raise ValueError("provenance subject does not match staging evidence")

    predicate = _object(
        _value(statement, "predicate", name="provenance predicate"),
        name="provenance predicate",
    )
    build_definition = _object(
        _value(predicate, "buildDefinition", name="provenance buildDefinition"),
        name="provenance buildDefinition",
    )
    if build_definition.get("buildType") != "https://actions.github.io/buildtypes/workflow/v1":
        raise ValueError("provenance build type is invalid")
    external = _object(
        _value(build_definition, "externalParameters", name="provenance externalParameters"),
        name="provenance externalParameters",
    )
    workflow = _object(
        _value(external, "workflow", name="provenance workflow"), name="provenance workflow"
    )
    expected_workflow = {
        "path": WORKFLOW_PATH,
        "ref": WORKFLOW_REF,
        "repository": repository_url,
    }
    if workflow != expected_workflow:
        raise ValueError("provenance workflow does not match the build workflow")
    internal = _object(
        _value(build_definition, "internalParameters", name="provenance internalParameters"),
        name="provenance internalParameters",
    )
    github = _object(_value(internal, "github", name="provenance github"), name="provenance github")
    if github.get("event_name") != "workflow_dispatch":
        raise ValueError("provenance build event is invalid")
    if github.get("runner_environment") != "github-hosted":
        raise ValueError("provenance runner must be github-hosted")
    dependencies = build_definition.get("resolvedDependencies")
    expected_dependency = {
        "uri": f"git+{repository_url}@{WORKFLOW_REF}",
        "digest": {"gitCommit": source_sha},
    }
    if dependencies != [expected_dependency]:
        raise ValueError("provenance source dependency does not match the selected source SHA")
    run_details = _object(
        _value(predicate, "runDetails", name="provenance runDetails"),
        name="provenance runDetails",
    )
    if run_details.get("builder") != {"id": signer}:
        raise ValueError("provenance builder does not match the build workflow")
    metadata = _object(
        _value(run_details, "metadata", name="provenance metadata"),
        name="provenance metadata",
    )
    metadata_invocation = metadata.get("invocationId")
    if (
        not isinstance(metadata_invocation, str)
        or invocation_pattern.fullmatch(metadata_invocation) is None
    ):
        raise ValueError("provenance invocation does not match the build run")


def verify_staging_promotion(
    *,
    evidence_dir: Path,
    expected_staging_run_id: str,
    expected_source_sha: str,
    allowed_image_ref: str,
    expected_github_repository: str,
    artifact_name: str,
    artifact_digest: str,
    artifact_expires_at: str,
    verification_time: datetime | None = None,
) -> VerifiedStagingPromotion:
    """Validate one downloaded staging artifact without cluster mutation."""

    now = verification_time or datetime.now(UTC)
    _validate_expected_identity(
        expected_staging_run_id=expected_staging_run_id,
        expected_source_sha=expected_source_sha,
        allowed_image_ref=allowed_image_ref,
        expected_github_repository=expected_github_repository,
        artifact_name=artifact_name,
        artifact_digest=artifact_digest,
        artifact_expires_at=artifact_expires_at,
        verification_time=now,
    )
    evidence_dir = _validate_evidence_files(evidence_dir)
    evidence_path = evidence_dir / "staging-promotion.json"
    evidence_bytes = evidence_path.read_bytes()
    evidence = _object(
        _load_json(evidence_path),
        name="staging evidence",
        keys={
            "schema_version",
            "source",
            "build",
            "image",
            "promotion_packet",
            "verification",
            "staging",
            "scope",
        },
    )
    if type(evidence["schema_version"]) is not int or evidence["schema_version"] != 1:
        raise ValueError("schema_version must be 1")

    source = _object(evidence["source"], name="source", keys={"git_sha"})
    source_sha = _string(source["git_sha"], name="source.git_sha", pattern=SOURCE_SHA_RE)
    if source_sha != expected_source_sha:
        raise ValueError("source.git_sha does not match the selected source SHA")

    build = _object(evidence["build"], name="build", keys={"workflow", "run_id"})
    if _string(build["workflow"], name="build.workflow") != "container-attestation":
        raise ValueError("build.workflow must be container-attestation")
    build_run_id = _string(build["run_id"], name="build.run_id", pattern=RUN_ID_RE)

    image = _object(evidence["image"], name="image", keys={"repository", "digest", "subject"})
    image_repository = _string(image["repository"], name="image.repository", pattern=IMAGE_REF_RE)
    if image_repository != allowed_image_ref:
        raise ValueError("image.repository does not match the allowed repository")
    image_digest = _string(image["digest"], name="image.digest", pattern=IMAGE_DIGEST_RE)
    image_subject = _string(image["subject"], name="image.subject")
    if image_subject != f"{image_repository}@{image_digest}":
        raise ValueError("image.subject does not match repository@digest")

    packet = _object(
        evidence["promotion_packet"],
        name="promotion_packet",
        keys={"sha256", "manifest_sha256"},
    )
    _string(packet["sha256"], name="promotion_packet.sha256", pattern=SHA256_RE)
    _string(
        packet["manifest_sha256"],
        name="promotion_packet.manifest_sha256",
        pattern=SHA256_RE,
    )

    verification = _object(
        evidence["verification"],
        name="verification",
        keys={"cosign", "github_build_provenance"},
    )
    cosign = _object(verification["cosign"], name="cosign", keys={"file", "sha256"})
    provenance = _object(
        verification["github_build_provenance"],
        name="github_build_provenance",
        keys={"file", "sha256"},
    )
    cosign_name = _string(cosign["file"], name="cosign.file")
    provenance_name = _string(provenance["file"], name="github_build_provenance.file")
    if cosign_name != "cosign-verify.json":
        raise ValueError("cosign.file must be cosign-verify.json")
    if provenance_name != "github-attestation.json":
        raise ValueError("github_build_provenance.file must be github-attestation.json")
    cosign_hash = _string(cosign["sha256"], name="cosign.sha256", pattern=SHA256_RE)
    provenance_hash = _string(
        provenance["sha256"], name="github_build_provenance.sha256", pattern=SHA256_RE
    )
    cosign_path = evidence_dir / cosign_name
    provenance_path = evidence_dir / provenance_name
    if _sha256_bytes(cosign_path.read_bytes()) != cosign_hash:
        raise ValueError("cosign result SHA-256 does not match staging evidence")
    if _sha256_bytes(provenance_path.read_bytes()) != provenance_hash:
        raise ValueError("provenance result SHA-256 does not match staging evidence")

    staging = _object(evidence["staging"], name="staging", keys={"workflow", "run_id", "result"})
    if _string(staging["workflow"], name="staging.workflow") != "staging-deploy":
        raise ValueError("staging.workflow must be staging-deploy")
    staging_run_id = _string(staging["run_id"], name="staging.run_id", pattern=RUN_ID_RE)
    if staging_run_id != expected_staging_run_id:
        raise ValueError("staging.run_id does not match the selected staging run")
    if _string(staging["result"], name="staging.result") != "smoke_and_e2e_passed":
        raise ValueError("staging.result must be smoke_and_e2e_passed")
    if evidence["scope"] != STAGING_SCOPE:
        raise ValueError("scope differs from the staging promotion contract")

    signer = f"https://github.com/{expected_github_repository}/{WORKFLOW_PATH}@{WORKFLOW_REF}"
    _verify_cosign_result(
        cosign_path,
        image_repository=image_repository,
        image_digest=image_digest,
        source_sha=source_sha,
        github_repository=expected_github_repository,
        signer=signer,
    )
    _verify_provenance_result(
        provenance_path,
        image_repository=image_repository,
        image_digest=image_digest,
        source_sha=source_sha,
        build_run_id=build_run_id,
        github_repository=expected_github_repository,
        signer=signer,
    )

    return VerifiedStagingPromotion(
        evidence_dir=evidence_dir,
        evidence_path=evidence_path.resolve(),
        cosign_result_path=cosign_path.resolve(),
        provenance_result_path=provenance_path.resolve(),
        source_sha=source_sha,
        staging_run_id=staging_run_id,
        build_run_id=build_run_id,
        image_repository=image_repository,
        image_digest=image_digest,
        image_subject=image_subject,
        artifact_name=artifact_name,
        artifact_digest=artifact_digest,
        artifact_expires_at=artifact_expires_at,
        evidence_sha256=_sha256_bytes(evidence_bytes),
    )


def emit_production_github_outputs(verified: VerifiedStagingPromotion, output_path: Path) -> None:
    lines = [
        f"build_run_id={verified.build_run_id}",
        f"image_subject={verified.image_subject}",
        f"image_repository={verified.image_repository}",
        f"image_digest={verified.image_digest}",
        f"cosign_result_file={verified.cosign_result_path}",
        f"provenance_result_file={verified.provenance_result_path}",
        f"staging_evidence_sha256={verified.evidence_sha256}",
    ]
    with output_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify staging promotion evidence for production consumption."
    )
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--expected-staging-run-id", required=True)
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--allowed-image-ref", required=True)
    parser.add_argument("--expected-github-repository", required=True)
    parser.add_argument("--artifact-name", required=True)
    parser.add_argument("--artifact-digest", required=True)
    parser.add_argument("--artifact-expires-at", required=True)
    parser.add_argument("--github-output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    verified = verify_staging_promotion(
        evidence_dir=args.evidence_dir,
        expected_staging_run_id=args.expected_staging_run_id,
        expected_source_sha=args.expected_source_sha,
        allowed_image_ref=args.allowed_image_ref,
        expected_github_repository=args.expected_github_repository,
        artifact_name=args.artifact_name,
        artifact_digest=args.artifact_digest,
        artifact_expires_at=args.artifact_expires_at,
    )
    if args.github_output is not None:
        emit_production_github_outputs(verified, args.github_output)
    print(verified.image_subject)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
