"""Runtime-artifact ownership for the dedicated control-plane coverage XML."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "ci.yml"
ARTIFACT_DIR = ".artifacts/coverage"
ARTIFACT_PATH = ".artifacts/coverage/coverage-control-plane.xml"


def _load_workflow() -> dict:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def test_control_plane_coverage_xml_has_ignored_runtime_owner() -> None:
    steps = _load_workflow()["jobs"]["test-integration"]["steps"]
    gate = next(
        step
        for step in steps
        if step.get("name") == "Control-plane critical-set coverage gate (audit F-12)"
    )
    publish = next(step for step in steps if step.get("name") == "Publish control-plane coverage")
    run = gate["run"]
    mkdir_at = run.find(f"mkdir -p {ARTIFACT_DIR}")
    xml_at = run.find("coverage xml")

    assert mkdir_at != -1, f"gate must create {ARTIFACT_DIR} before coverage xml"
    assert xml_at != -1
    assert mkdir_at < xml_at
    assert f"coverage xml -o {ARTIFACT_PATH}" in run
    assert "coverage xml -o coverage-control-plane.xml" not in run
    assert publish["if"] == "always()"
    assert str(publish["uses"]).startswith("actions/upload-artifact@")
    assert publish["with"]["name"] == "coverage-control-plane"
    assert publish["with"]["path"] == ARTIFACT_PATH
    assert publish["with"]["path"] != "coverage-control-plane.xml"
    assert publish["with"]["if-no-files-found"] == "warn"
    assert ".artifacts/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
