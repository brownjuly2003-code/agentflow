#!/usr/bin/env python3
"""Render a Helm promotion packet for one workflow-built image digest."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

IMAGE_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
IMAGE_REF_RE = re.compile(
    r"[a-z0-9]+(?:[._-][a-z0-9]+)*(?::[0-9]+)?/"
    r"[a-z0-9]+(?:[._/-][a-z0-9]+)*"
)
SOURCE_SHA_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
RUN_ID_RE = re.compile(r"[1-9][0-9]*")


def _validate_identity(
    *,
    image_ref: str,
    image_digest: str,
    source_sha: str,
    run_id: str,
) -> None:
    if IMAGE_REF_RE.fullmatch(image_ref) is None:
        raise ValueError("image_ref must be a lowercase registry/repository without tag or digest")
    if IMAGE_DIGEST_RE.fullmatch(image_digest) is None:
        raise ValueError("image_digest must match sha256 followed by 64 lowercase hex characters")
    if SOURCE_SHA_RE.fullmatch(source_sha) is None:
        raise ValueError("source_sha must be a 40- or 64-character lowercase Git object id")
    if RUN_ID_RE.fullmatch(run_id) is None:
        raise ValueError("run_id must be a positive decimal GitHub Actions run id")


def _resolve_helm(executable: str) -> str:
    resolved = shutil.which(executable)
    if resolved is None:
        raise RuntimeError(f"Helm executable not found: {executable}")
    return resolved


def _run_helm(command: list[str], *, description: str) -> str:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no output"
        raise RuntimeError(f"{description} failed: {detail}")
    return result.stdout


def build_promotion_evidence(
    *,
    image_ref: str,
    image_digest: str,
    source_sha: str,
    run_id: str,
    chart_path: Path,
    output_dir: Path,
    helm_executable: str = "helm",
) -> dict[str, Any]:
    """Write values, a digest-bound Deployment manifest, and its metadata."""

    _validate_identity(
        image_ref=image_ref,
        image_digest=image_digest,
        source_sha=source_sha,
        run_id=run_id,
    )
    chart_path = chart_path.resolve()
    if not (chart_path / "Chart.yaml").is_file():
        raise ValueError(f"chart_path is not a Helm chart: {chart_path}")
    helm = _resolve_helm(helm_executable)

    output_dir.mkdir(parents=True, exist_ok=True)
    values_path = output_dir / "image-values.yaml"
    manifest_path = output_dir / "helm-deployment.yaml"
    packet_path = output_dir / "promotion.json"

    values_text = (
        f"image:\n  repository: {json.dumps(image_ref)}\n  digest: {json.dumps(image_digest)}\n"
    )
    values_path.write_text(values_text, encoding="utf-8", newline="\n")

    helm_version = _run_helm([helm, "version", "--short"], description="helm version").strip()
    manifest = _run_helm(
        [
            helm,
            "template",
            "agentflow",
            str(chart_path),
            "--values",
            str(values_path),
            "--show-only",
            "templates/deployment.yaml",
        ],
        description="helm promotion render",
    )
    subject = f"{image_ref}@{image_digest}"
    if f'image: "{subject}"' not in manifest:
        raise RuntimeError("Helm promotion render did not contain the requested repository@digest")
    manifest_path.write_text(manifest, encoding="utf-8", newline="\n")

    packet: dict[str, Any] = {
        "schema_version": 1,
        "source": {"git_sha": source_sha},
        "build": {
            "workflow": "container-attestation",
            "run_id": run_id,
        },
        "image": {
            "repository": image_ref,
            "digest": image_digest,
            "subject": subject,
        },
        "helm": {
            "values": values_path.name,
            "manifest": manifest_path.name,
            "manifest_sha256": hashlib.sha256(manifest.encode("utf-8")).hexdigest(),
            "version": helm_version,
        },
        "generator": {"python": platform.python_version()},
        "scope": {
            "proves": ["the Helm API deployment references the workflow-built image digest"],
            "does_not_prove": ["staging rollout", "production acceptance"],
        },
    }
    packet_path.write_text(
        json.dumps(packet, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return packet


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render machine-readable Helm evidence for a built image digest."
    )
    parser.add_argument("--image-ref", required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--chart", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--helm", default="helm")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    packet = build_promotion_evidence(
        image_ref=args.image_ref,
        image_digest=args.image_digest,
        source_sha=args.source_sha,
        run_id=args.run_id,
        chart_path=args.chart,
        output_dir=args.output_dir,
        helm_executable=args.helm,
    )
    print(packet["image"]["subject"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
