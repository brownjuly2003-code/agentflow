#!/usr/bin/env python3
"""Repair the Flink Operator 1.15 CRD enum for the Flink 2.3 runtime."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from typing import Any

CRD_NAME = "flinkdeployments.flink.apache.org"
CRD_VERSION = "v1beta1"
TARGET_FLINK_VERSION = "v2_3"
UPSTREAM_1_15_ENUM = [
    "v1_13",
    "v1_14",
    "v1_15",
    "v1_16",
    "v1_17",
    "v1_18",
    "v1_19",
    "v1_20",
    "v2_0",
    "v2_1",
    "v2_2",
]


def build_flinkdeployment_crd_patch(crd: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a fail-closed JSON Patch for the published Operator 1.15 CRD."""
    versions = crd.get("spec", {}).get("versions")
    if not isinstance(versions, list):
        raise ValueError("FlinkDeployment CRD has no spec.versions list")

    matching_indexes = [
        index
        for index, version in enumerate(versions)
        if isinstance(version, dict) and version.get("name") == CRD_VERSION
    ]
    if len(matching_indexes) != 1:
        raise ValueError(f"expected exactly one {CRD_VERSION} CRD version")

    version_index = matching_indexes[0]
    version = versions[version_index]
    try:
        flink_versions = version["schema"]["openAPIV3Schema"]["properties"]["spec"]["properties"][
            "flinkVersion"
        ]["enum"]
    except (KeyError, TypeError) as error:
        raise ValueError("FlinkDeployment CRD has no flinkVersion enum") from error

    compatible_enum = [*UPSTREAM_1_15_ENUM, TARGET_FLINK_VERSION]
    if flink_versions == compatible_enum:
        return []
    if flink_versions != UPSTREAM_1_15_ENUM:
        raise ValueError(f"unexpected FlinkVersion enum: {flink_versions!r}")

    enum_path = (
        f"/spec/versions/{version_index}/schema/openAPIV3Schema"
        "/properties/spec/properties/flinkVersion/enum"
    )
    return [
        {
            "op": "test",
            "path": f"/spec/versions/{version_index}/name",
            "value": CRD_VERSION,
        },
        {"op": "test", "path": enum_path, "value": UPSTREAM_1_15_ENUM},
        {"op": "add", "path": f"{enum_path}/-", "value": TARGET_FLINK_VERSION},
    ]


def _run_kubectl(kubectl: str, arguments: Sequence[str]) -> str:
    result = subprocess.run(
        [kubectl, *arguments],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"kubectl {' '.join(arguments)} failed: {detail}")
    return result.stdout


def _load_crd(kubectl: str) -> dict[str, Any]:
    payload = json.loads(_run_kubectl(kubectl, ["get", "crd", CRD_NAME, "-o", "json"]))
    if not isinstance(payload, dict):
        raise ValueError("kubectl returned a non-object CRD")
    return payload


def patch_flinkdeployment_crd(kubectl: str) -> dict[str, str]:
    patch = build_flinkdeployment_crd_patch(_load_crd(kubectl))
    if not patch:
        status = "already-compatible"
    else:
        _run_kubectl(
            kubectl,
            [
                "patch",
                "crd",
                CRD_NAME,
                "--type=json",
                "-p",
                json.dumps(patch, separators=(",", ":")),
            ],
        )
        if build_flinkdeployment_crd_patch(_load_crd(kubectl)):
            raise RuntimeError("FlinkDeployment CRD patch did not persist")
        status = "patched"

    return {
        "crd": CRD_NAME,
        "flink_version": TARGET_FLINK_VERSION,
        "status": status,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kubectl", default="kubectl")
    arguments = parser.parse_args(argv)

    try:
        result = patch_flinkdeployment_crd(arguments.kubectl)
    except (json.JSONDecodeError, OSError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
