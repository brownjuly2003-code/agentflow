"""Generate a ci-soak attempt bundle from one typed schema (audit F-10).

The r12 preflight failed at ``output_marker_hash_mismatch`` because a
hand-assembled wrapper carried the r12 marker text next to the r11 marker
hash. This generator removes that failure class by construction:

- every identity, path, marker text, and hash derives from one
  ``AttemptSpec``; the schema has no hash field, so an expected hash can
  never be typed in by hand;
- the generated bundle is self-verified before anything is transferred:
  ``verify`` re-derives every field from the recorded spec and recomputes
  the marker hash from the marker file bytes, so any manual edit — hash
  included — fails closed;
- consumed attempt rounds (r12 and earlier) are rejected, matching the
  resume boundary in docs/operations/ci-soak-next-session-runbook.md.

Wrapper builders must source every identity and expected hash from the
generated ``wrapper-inputs.env`` / ``attempt-manifest.json`` instead of
copying values between attempts.

Usage:
    python scripts/golden_soak/gen_attempt_bundle.py generate \
        --head <40-hex HEAD> --round 13 --date 20260822 --seq 01 \
        --out .codex-grok-tasks/ci-soak-<short>-r13-20260822-01
    python scripts/golden_soak/gen_attempt_bundle.py verify --bundle <dir>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# r9-r12 identities are consumed evidence; a fresh external attempt starts at
# r13 or later (AGENT_STATE.md, ci-soak-next-session-runbook.md).
MIN_ROUND = 13

MANIFEST_NAME = "attempt-manifest.json"
MARKER_NAME = "marker.txt"
ENV_NAME = "wrapper-inputs.env"

_HEAD_RE = re.compile(r"^[0-9a-f]{40}$")
_DATE_RE = re.compile(r"^\d{8}$")
_SEQ_RE = re.compile(r"^\d{2}$")


class BundleError(ValueError):
    """A spec or bundle failed validation."""


@dataclass(frozen=True)
class AttemptSpec:
    """The single typed input. Hashes are always derived, never supplied."""

    head: str
    round_number: int
    date: str
    sequence: str

    def validate(self) -> None:
        if not _HEAD_RE.fullmatch(self.head):
            raise BundleError(f"head must be 40 lowercase hex chars, got {self.head!r}")
        if self.round_number < MIN_ROUND:
            raise BundleError(
                f"round r{self.round_number} is consumed evidence; "
                f"new attempts start at r{MIN_ROUND} or later"
            )
        if not _DATE_RE.fullmatch(self.date):
            raise BundleError(f"date must be YYYYMMDD, got {self.date!r}")
        if not _SEQ_RE.fullmatch(self.sequence):
            raise BundleError(f"sequence must be two digits, got {self.sequence!r}")


def derive_fields(spec: AttemptSpec) -> dict[str, str]:
    """Every attempt identity, path, and expected hash from the spec alone.

    The marker hash is SHA-256 over the bare marker text with no trailing
    newline — the exact convention the r12 evidence recorded
    (ci-soak-r12-preflight-fail-20260821-01.md).
    """
    short = spec.head[:7]
    rnd = f"r{spec.round_number}"
    attempt_id = f"ci-soak-{short}-{rnd}"
    stamp = f"{spec.date}-{spec.sequence}"
    marker_text = f"ci-soak-output-{short}-{rnd}"

    return {
        "head": spec.head,
        "short_head": short,
        "round": rnd,
        "attempt_id": attempt_id,
        "preflight_attempt_id": f"{attempt_id}-preflight",
        "snapshot_id": f"{attempt_id}-snapshot-{stamp}",
        "control_id": f"{attempt_id}-control-{stamp}",
        "output_id": f"{attempt_id}-output-{stamp}",
        "local_control_dir": f".codex-grok-tasks/{attempt_id}-{stamp}",
        # r14 (2026-08-22) proved the Colima VM mounts ONLY
        # /Users/julia/agentflow-fc5-7113966 (rw virtiofs) — a shared root
        # anywhere else (including /tmp) bind-mounts as an empty directory
        # inside containers and fails the source-visibility preflight.
        # Attempt roots therefore live under that mount.
        "remote_root": f"/Users/julia/agentflow-fc5-7113966/{attempt_id}-{stamp}",
        "output_marker_text": marker_text,
        "output_marker_sha256": hashlib.sha256(marker_text.encode("utf-8")).hexdigest(),
    }


def _manifest(spec: AttemptSpec) -> dict:
    return {
        "schema": "ci-soak-attempt-bundle/1",
        "spec": {
            "head": spec.head,
            "round_number": spec.round_number,
            "date": spec.date,
            "sequence": spec.sequence,
        },
        "derived": derive_fields(spec),
    }


def generate(spec: AttemptSpec, out_dir: Path) -> Path:
    spec.validate()
    if out_dir.exists():
        raise BundleError(
            f"{out_dir} already exists; attempt identities must be fresh, never reused"
        )
    manifest = _manifest(spec)
    derived = manifest["derived"]

    out_dir.mkdir(parents=True)
    (out_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    # Exact bare bytes: the marker hash is over this file's full content.
    (out_dir / MARKER_NAME).write_bytes(derived["output_marker_text"].encode("utf-8"))
    env_lines = [
        "# Generated by gen_attempt_bundle.py — do not edit by hand (audit F-10).",
        "# Wrapper templates must source identities and hashes from here only.",
    ]
    env_lines.extend(f"CI_SOAK_{key.upper()}={value}" for key, value in derived.items())
    (out_dir / ENV_NAME).write_text("\n".join(env_lines) + "\n", encoding="utf-8", newline="\n")

    verify(out_dir)
    return out_dir


def verify(bundle_dir: Path) -> dict:
    """Fail closed unless every recorded value re-derives from the spec."""
    manifest_path = bundle_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        raise BundleError(f"{manifest_path} is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    if manifest.get("schema") != "ci-soak-attempt-bundle/1":
        raise BundleError(f"unknown bundle schema {manifest.get('schema')!r}")
    spec_payload = manifest.get("spec", {})
    if set(spec_payload) != {"head", "round_number", "date", "sequence"}:
        raise BundleError(f"unexpected spec keys {sorted(spec_payload)!r}")
    spec = AttemptSpec(
        head=spec_payload["head"],
        round_number=spec_payload["round_number"],
        date=spec_payload["date"],
        sequence=spec_payload["sequence"],
    )
    spec.validate()

    expected = derive_fields(spec)
    recorded = manifest.get("derived")
    if recorded != expected:
        raise BundleError(
            "derived fields do not re-derive from the spec; the bundle was "
            f"edited by hand: {recorded!r} != {expected!r}"
        )

    marker_bytes = (bundle_dir / MARKER_NAME).read_bytes()
    if marker_bytes != expected["output_marker_text"].encode("utf-8"):
        raise BundleError("marker.txt bytes do not match the derived marker text")
    marker_sha = hashlib.sha256(marker_bytes).hexdigest()
    if marker_sha != expected["output_marker_sha256"]:
        raise BundleError(
            f"marker hash mismatch: file {marker_sha} != derived {expected['output_marker_sha256']}"
        )

    env_text = (bundle_dir / ENV_NAME).read_text(encoding="utf-8")
    for key, value in expected.items():
        line = f"CI_SOAK_{key.upper()}={value}"
        if line not in env_text.splitlines():
            raise BundleError(f"wrapper-inputs.env is missing or altered: {line!r}")

    return expected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="generate and self-verify a fresh attempt bundle")
    gen.add_argument("--head", required=True, help="exact 40-hex source HEAD")
    gen.add_argument("--round", required=True, type=int, dest="round_number")
    gen.add_argument("--date", required=True, help="YYYYMMDD attempt date")
    gen.add_argument("--seq", required=True, help="two-digit attempt sequence")
    gen.add_argument("--out", required=True, type=Path, help="fresh bundle directory")

    ver = sub.add_parser("verify", help="re-verify an existing bundle before transfer")
    ver.add_argument("--bundle", required=True, type=Path)

    args = parser.parse_args(argv)
    try:
        if args.command == "generate":
            spec = AttemptSpec(
                head=args.head,
                round_number=args.round_number,
                date=args.date,
                sequence=args.seq,
            )
            out_dir = generate(spec, args.out)
            derived = verify(out_dir)
            print(f"BUNDLE=PASS attempt_id={derived['attempt_id']} out={out_dir}")
        else:
            derived = verify(args.bundle)
            print(f"BUNDLE=PASS attempt_id={derived['attempt_id']} out={args.bundle}")
    except BundleError as error:
        print(f"BUNDLE=FAIL reason={error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
