from __future__ import annotations

import shutil
import tomllib
from pathlib import Path

from scripts.validate_project_claims import validate_repository

ROOT = Path(__file__).resolve().parents[2]

VALIDATOR_INPUTS = (
    "config/project_claims.toml",
    "pyproject.toml",
    ".github/workflows/ci.yml",
    "codecov.yml",
    "src/processing/flink_jobs/requirements.txt",
    "src/processing/flink_jobs/Dockerfile",
    "helm/agentflow/values.yaml",
    "helm/agentflow/templates/flinkdeployment.yaml",
    "sdk/agentflow/client.py",
    "sdk-ts/src/client.ts",
    "docs/sdk-capabilities.md",
    "README.md",
    "docs/api-reference.md",
    "docs/architecture.md",
    "docs/dataflow.html",
    "docs/release-readiness.md",
    "docs/STATUS.md",
    "docs/quality.md",
    "docs/decisions/0013-golden-production-topology.md",
    "docs/perf/freshness-e2e-realpath.md",
    "docs/perf/golden-flink-submission-2026-07-30.md",
)


def test_repository_claims_are_consistent() -> None:
    assert validate_repository(ROOT) == []


def test_flink_submission_smoke_evidence_is_claimed() -> None:
    """Submission smoke PASS is machine-readable and fixture-wired.

    Scope boundary: clean-checkout OCI build + real job submission only —
    not Operator deployment, lake-to-serving E2E, or production acceptance.
    """
    evidence = "docs/perf/golden-flink-submission-2026-07-30.md"
    manifest = tomllib.loads((ROOT / "config" / "project_claims.toml").read_text(encoding="utf-8"))
    production = manifest["production"]

    assert evidence in manifest["required_evidence"]
    assert production.get("verified_submission_smoke") == evidence
    assert evidence in VALIDATOR_INPUTS
    assert (ROOT / evidence).is_file()


def test_flink_submission_smoke_evidence_documents_live_compose_commands() -> None:
    """Report command classes must match the live Mac PASS-run compose workflow.

    Rejects the drifted direct `docker build -f .../Dockerfile` recipe that
    never ran in the recorded PASS evidence.
    """
    evidence = ROOT / "docs/perf/golden-flink-submission-2026-07-30.md"
    text = evidence.read_text(encoding="utf-8")
    # Evidence fragment from the live Mac PASS path; not a temp-file operation.
    checkout = "/tmp/agentflow-acceptance-ca82be5-grokw-01"  # noqa: S108

    required_fragments = (
        "docker compose --project-name agentflow-flink-ca82be5",
        f"--project-directory {checkout}",
        f"-f {checkout}/docker-compose.yml",
        f"-f {checkout}/docker-compose.flink.yml",
        "build flink-job-runner",
        "up -d flink-job-runner",
        "logs flink-job-runner",
        "down -v",
    )
    for fragment in required_fragments:
        assert fragment in text, f"missing live command fragment: {fragment}"

    assert "-f src/processing/flink_jobs/Dockerfile" not in text


def test_validator_detects_document_drift(tmp_path: Path) -> None:
    fixture_root = tmp_path / "repo"
    for relative in VALIDATOR_INPUTS:
        source = ROOT / relative
        target = fixture_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    readme = fixture_root / "README.md"
    original = readme.read_text(encoding="utf-8")
    assert "3.02 s p50" in original
    readme.write_text(original.replace("3.02 s p50", "0.22 s p50", 1), encoding="utf-8")

    errors = validate_repository(fixture_root)

    assert any("README.md" in error and "3.02 s p50" in error for error in errors)


def test_validator_detects_dataflow_latency_drift(tmp_path: Path) -> None:
    fixture_root = tmp_path / "repo"
    for relative in VALIDATOR_INPUTS:
        source = ROOT / relative
        target = fixture_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    dataflow = fixture_root / "docs" / "dataflow.html"
    original = dataflow.read_text(encoding="utf-8")
    assert "3.02 s p50" in original
    dataflow.write_text(original.replace("3.02 s p50", "0.22 s p50", 1), encoding="utf-8")

    errors = validate_repository(fixture_root)

    assert any("docs/dataflow.html" in error and "3.02 s p50" in error for error in errors)


def test_validator_detects_flink_workload_version_drift(tmp_path: Path) -> None:
    fixture_root = tmp_path / "repo"
    for relative in VALIDATOR_INPUTS:
        source = ROOT / relative
        target = fixture_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    values = fixture_root / "helm" / "agentflow" / "values.yaml"
    original = values.read_text(encoding="utf-8")
    values.write_text(
        original.replace(
            'repository: agentflow/flink\n    tag: "2.3.0"',
            'repository: agentflow/flink\n    tag: "2.2.0"',
        ),
        encoding="utf-8",
    )

    errors = validate_repository(fixture_root)

    assert any("helm/agentflow/values.yaml" in error and "2.3.0" in error for error in errors)


def test_validator_rejects_non_flink_runtime_base_image(tmp_path: Path) -> None:
    fixture_root = tmp_path / "repo"
    for relative in VALIDATOR_INPUTS:
        source = ROOT / relative
        target = fixture_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    dockerfile = fixture_root / "src" / "processing" / "flink_jobs" / "Dockerfile"
    original = dockerfile.read_text(encoding="utf-8")
    dockerfile.write_text(
        original.replace(original.splitlines()[0], "FROM python:3.11-slim", 1),
        encoding="utf-8",
    )

    errors = validate_repository(fixture_root)

    assert any(
        "src/processing/flink_jobs/Dockerfile" in error and "official Flink base image" in error
        for error in errors
    )


def test_validator_detects_sdk_method_drift(tmp_path: Path) -> None:
    fixture_root = tmp_path / "repo"
    for relative in VALIDATOR_INPUTS:
        source = ROOT / relative
        target = fixture_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    client = fixture_root / "sdk-ts" / "src" / "client.ts"
    original = client.read_text(encoding="utf-8")
    client.write_text(
        original.replace("  async explainQuery(", "  async removedExplainQuery(", 1),
        encoding="utf-8",
    )

    errors = validate_repository(fixture_root)

    assert any("sdk-ts/src/client.ts" in error and "explainQuery" in error for error in errors)


def test_validator_detects_patch_coverage_gate_drift(tmp_path: Path) -> None:
    fixture_root = tmp_path / "repo"
    for relative in VALIDATOR_INPUTS:
        source = ROOT / relative
        target = fixture_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    workflow = fixture_root / ".github" / "workflows" / "ci.yml"
    original = workflow.read_text(encoding="utf-8")
    workflow.write_text(
        original.replace("--fail-under=80", "--fail-under=75", 1),
        encoding="utf-8",
    )

    errors = validate_repository(fixture_root)

    assert any(
        ".github/workflows/ci.yml" in error and "patch coverage" in error for error in errors
    )
