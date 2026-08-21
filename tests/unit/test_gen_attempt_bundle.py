"""Audit F-10: ci-soak attempt bundles derive from one typed schema.

The r12 preflight failed at ``output_marker_hash_mismatch`` because a
hand-assembled wrapper paired r12 marker text with the retained r11 marker
hash. These tests pin the generator's guarantees: hashes are derived and
never accepted as input, consumed rounds are rejected, and any manual edit
of a generated bundle fails verification before transfer.
"""

import json
from pathlib import Path

import pytest

from scripts.golden_soak.gen_attempt_bundle import (
    MIN_ROUND,
    AttemptSpec,
    BundleError,
    derive_fields,
    generate,
    verify,
)

R12_HEAD = "bfb82ecb6c66e5490db2d99bbdaf8b9da55f2082"
# The exact values the r12 evidence recorded
# (ci-soak-r12-preflight-fail-20260821-01.md).
R12_MARKER_TEXT = "ci-soak-output-bfb82ec-r12"
R12_MARKER_SHA256 = "9853a9344b1378f968eb4f5c808c6541275746d6f5682a507b6d3294d4bfb6f2"


def _fresh_spec() -> AttemptSpec:
    return AttemptSpec(head=R12_HEAD, round_number=MIN_ROUND, date="20260822", sequence="01")


def test_marker_hash_reproduces_the_recorded_r12_convention():
    derived = derive_fields(
        AttemptSpec(head=R12_HEAD, round_number=12, date="20260821", sequence="01")
    )

    assert derived["output_marker_text"] == R12_MARKER_TEXT
    assert derived["output_marker_sha256"] == R12_MARKER_SHA256


def test_spec_has_no_hash_input_surface():
    # The r12 failure class — a hand-typed expected hash — must be
    # impossible at the schema level, not merely discouraged.
    assert set(AttemptSpec.__dataclass_fields__) == {"head", "round_number", "date", "sequence"}


def test_generate_produces_a_self_consistent_bundle(tmp_path: Path):
    out_dir = generate(_fresh_spec(), tmp_path / "bundle")

    derived = verify(out_dir)

    marker_bytes = (out_dir / "marker.txt").read_bytes()
    assert marker_bytes == derived["output_marker_text"].encode("utf-8")
    env_text = (out_dir / "wrapper-inputs.env").read_text(encoding="utf-8")
    assert f"CI_SOAK_OUTPUT_MARKER_SHA256={derived['output_marker_sha256']}" in env_text
    assert f"CI_SOAK_OUTPUT_MARKER_TEXT={derived['output_marker_text']}" in env_text
    assert derived["attempt_id"] == f"ci-soak-bfb82ec-r{MIN_ROUND}"


def test_generate_rejects_consumed_rounds(tmp_path: Path):
    spec = AttemptSpec(head=R12_HEAD, round_number=12, date="20260822", sequence="01")

    with pytest.raises(BundleError, match="consumed evidence"):
        generate(spec, tmp_path / "bundle")


def test_generate_rejects_existing_directory(tmp_path: Path):
    target = tmp_path / "bundle"
    target.mkdir()

    with pytest.raises(BundleError, match="fresh"):
        generate(_fresh_spec(), target)


def test_generate_rejects_malformed_head(tmp_path: Path):
    spec = AttemptSpec(head="bfb82ec", round_number=MIN_ROUND, date="20260822", sequence="01")

    with pytest.raises(BundleError, match="40 lowercase hex"):
        generate(spec, tmp_path / "bundle")


def test_verify_fails_closed_on_hand_edited_marker_hash(tmp_path: Path):
    out_dir = generate(_fresh_spec(), tmp_path / "bundle")
    manifest_path = out_dir / "attempt-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    # Re-create the r12 failure: correct marker text, stale hash pasted in.
    manifest["derived"]["output_marker_sha256"] = R12_MARKER_SHA256
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BundleError, match="edited by hand"):
        verify(out_dir)


def test_verify_fails_closed_on_tampered_marker_file(tmp_path: Path):
    out_dir = generate(_fresh_spec(), tmp_path / "bundle")
    (out_dir / "marker.txt").write_bytes(R12_MARKER_TEXT.encode("utf-8"))

    with pytest.raises(BundleError, match="marker.txt bytes"):
        verify(out_dir)


def test_verify_fails_closed_on_altered_env_file(tmp_path: Path):
    out_dir = generate(_fresh_spec(), tmp_path / "bundle")
    env_path = out_dir / "wrapper-inputs.env"
    env_text = env_path.read_text(encoding="utf-8")
    env_path.write_text(
        env_text.replace("CI_SOAK_OUTPUT_MARKER_SHA256=", "CI_SOAK_OUTPUT_MARKER_SHA256=dead"),
        encoding="utf-8",
    )

    with pytest.raises(BundleError, match="wrapper-inputs.env"):
        verify(out_dir)
