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
    "src/agentflow_runtime/processing/flink_jobs/requirements.txt",
    "src/agentflow_runtime/processing/flink_jobs/Dockerfile",
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
    "docs/archive/performance/freshness-e2e-realpath-2026-07-09.md",
    "docs/perf/golden-flink-submission-2026-07-30.md",
    "docs/perf/live-iceberg-materialization-2026-08-01.md",
    "docs/perf/full-lake-to-serving-e2e-2026-08-01.md",
    "docs/perf/checkpoint-restore-replay-2026-08-02.md",
    "docs/operations/npm-environment-approval-2026-08-03.md",
    "docs/perf/golden-4h-soak-canary-failure-2026-08-02.md",
    "docs/perf/ready-baselined-checkpoint-hold-2026-08-03.md",
    "docs/perf/golden-4h-canary2-fix4-kind-residual-pass-2026-08-07.md",
    "docs/perf/golden-4h-soak-start-2026-08-07.md",
    "docs/perf/golden-4h-soak-05-failure-2026-08-08.md",
    "corrected-rollback-pair-runtime-20260823-01.md",
    "ci-soak-f02-capacity-decision-20260823-01.md",
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


def test_live_iceberg_materialization_evidence_is_claimed() -> None:
    """Live Iceberg materialization PASS is machine-readable and fixture-wired.

    Scope boundary: direct events.validated -> lake materializer -> Iceberg
    exact identity once — not Kafka source, full lake-to-serving E2E, or
    production acceptance.
    """
    evidence = "docs/perf/live-iceberg-materialization-2026-08-01.md"
    pending_item = "live Iceberg materialization from events.validated"
    remaining_pending = [
        "4h soak and rollback rehearsal on the golden topology",
    ]
    manifest = tomllib.loads((ROOT / "config" / "project_claims.toml").read_text(encoding="utf-8"))
    production = manifest["production"]
    pending = production.get("pending_acceptance", [])

    assert evidence in manifest["required_evidence"]
    assert production.get("verified_iceberg_materialization") == evidence
    assert pending_item not in pending
    assert pending == remaining_pending
    assert evidence in VALIDATOR_INPUTS
    assert (ROOT / evidence).is_file()


def test_full_lake_to_serving_e2e_evidence_is_claimed() -> None:
    """Full lake-to-serving single-event smoke PASS is machine-readable.

    Scope boundary: one measured hop chain for one event —
    orders.raw -> PyFlink -> events.validated -> Iceberg and serving bridge ->
    ClickHouse -> API. Not production acceptance, restore/replay, soak,
    rollback, pentest, or npm approval.
    """
    evidence = "docs/perf/full-lake-to-serving-e2e-2026-08-01.md"
    pending_item = "Kafka -> PyFlink -> Iceberg -> ClickHouse -> API smoke"
    remaining_pending = [
        "4h soak and rollback rehearsal on the golden topology",
    ]
    manifest = tomllib.loads((ROOT / "config" / "project_claims.toml").read_text(encoding="utf-8"))
    production = manifest["production"]
    pending = production.get("pending_acceptance", [])

    assert evidence in manifest["required_evidence"]
    assert production.get("verified_full_lake_to_serving_smoke") == evidence
    assert pending_item not in pending
    assert pending == remaining_pending
    assert evidence in VALIDATOR_INPUTS
    assert (ROOT / evidence).is_file()


def test_checkpoint_restore_replay_evidence_is_claimed() -> None:
    """Restore/replay PASS is machine-readable without elevating production."""
    evidence = "docs/perf/checkpoint-restore-replay-2026-08-02.md"
    pending_item = "checkpoint restore and replay acceptance"
    remaining_pending = ["4h soak and rollback rehearsal on the golden topology"]
    manifest = tomllib.loads((ROOT / "config" / "project_claims.toml").read_text(encoding="utf-8"))
    production = manifest["production"]
    pending = production.get("pending_acceptance", [])

    assert manifest["production"]["status"] == "candidate"
    assert evidence in manifest["required_evidence"]
    assert production.get("verified_checkpoint_restore_replay") == evidence
    assert pending_item not in pending
    assert pending == remaining_pending
    assert evidence in VALIDATOR_INPUTS
    assert (ROOT / evidence).is_file()


def test_npm_environment_approval_evidence_is_claimed() -> None:
    """The external npm approval gate is evidenced without elevating production."""
    evidence = "docs/operations/npm-environment-approval-2026-08-03.md"
    remaining_pending = ["4h soak and rollback rehearsal on the golden topology"]
    manifest = tomllib.loads((ROOT / "config" / "project_claims.toml").read_text(encoding="utf-8"))
    production = manifest["production"]

    assert production["status"] == "candidate"
    assert evidence in manifest["required_evidence"]
    assert production.get("verified_npm_environment_approval") == evidence
    assert production.get("pending_acceptance", []) == remaining_pending
    assert evidence in VALIDATOR_INPUTS
    assert (ROOT / evidence).is_file()


def test_failed_soak_canary_is_claimed_without_closing_the_gate() -> None:
    """Historical failed canary remains required evidence; gate stays open."""
    evidence = "docs/perf/golden-4h-soak-canary-failure-2026-08-02.md"
    remaining_pending = ["4h soak and rollback rehearsal on the golden topology"]
    manifest = tomllib.loads((ROOT / "config" / "project_claims.toml").read_text(encoding="utf-8"))
    production = manifest["production"]

    assert production["status"] == "candidate"
    assert evidence in manifest["required_evidence"]
    # Superseded as *latest* attempt by kind residual PASS + soak start, but retained.
    assert production.get("latest_soak_attempt") != evidence
    assert production.get("pending_acceptance", []) == remaining_pending
    assert evidence in VALIDATOR_INPUTS
    assert (ROOT / evidence).is_file()


def test_ready_baselined_hold_pass_is_claimed_without_closing_the_soak_gate() -> None:
    """The read-only hold PASS advances recovery evidence, not acceptance."""
    evidence = "docs/perf/ready-baselined-checkpoint-hold-2026-08-03.md"
    remaining_pending = ["4h soak and rollback rehearsal on the golden topology"]
    manifest = tomllib.loads((ROOT / "config" / "project_claims.toml").read_text(encoding="utf-8"))
    production = manifest["production"]

    assert production["status"] == "candidate"
    assert evidence in manifest["required_evidence"]
    assert production.get("verified_ready_baselined_checkpoint_hold") == evidence
    assert production.get("latest_soak_recovery_evidence") == evidence
    assert production.get("latest_soak_recovery_state") == "ready-baselined-hold-pass"
    assert (
        production.get("latest_soak_recovery_source") == "78742d0a80206b31219c6d06b84952236235cd74"
    )
    assert (
        production.get("latest_soak_recovery_image")
        == "agentflow-flink-local:78742d0-minpause0-groupoffsets-20260803-01"
    )
    assert production.get("latest_soak_recovery_startup_mode") == "group-offsets"
    assert production.get("pending_acceptance", []) == remaining_pending
    assert evidence in VALIDATOR_INPUTS
    assert (ROOT / evidence).is_file()

    for relative in (
        "docs/STATUS.md",
        "docs/release-readiness.md",
        "docs/PROJECT_CLOSURE.md",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "ready-baselined-checkpoint-hold-2026-08-03.md" in text
        assert "RUNTIME_HOLD_PASS" in text


def test_kind_residual_canary_pass_is_claimed_without_closing_the_soak_gate() -> None:
    """Kind residual canary PASS does not clear dual-mean soak acceptance."""
    evidence = "docs/perf/golden-4h-canary2-fix4-kind-residual-pass-2026-08-07.md"
    remaining_pending = ["4h soak and rollback rehearsal on the golden topology"]
    manifest = tomllib.loads((ROOT / "config" / "project_claims.toml").read_text(encoding="utf-8"))
    production = manifest["production"]

    assert production["status"] == "candidate"
    assert evidence in manifest["required_evidence"]
    assert production.get("latest_kind_residual_canary") == evidence
    assert production.get("latest_kind_residual_canary_result") == (
        "pass-residual-7p51s-budget-20s"
    )
    assert production.get("pending_acceptance", []) == remaining_pending
    assert evidence in VALIDATOR_INPUTS
    assert (ROOT / evidence).is_file()
    text = (ROOT / evidence).read_text(encoding="utf-8")
    assert "PASS_KIND_RESIDUAL_20" in text
    assert "not" in text.lower()
    assert "production" in text.lower()


def test_soak_failure_is_latest_attempt_without_closing_the_gate() -> None:
    """Soak-05 failure is the latest attempt; acceptance stays open."""
    failure_evidence = "docs/perf/golden-4h-soak-05-failure-2026-08-08.md"
    historical_start = "docs/perf/golden-4h-soak-start-2026-08-07.md"
    remaining_pending = ["4h soak and rollback rehearsal on the golden topology"]
    manifest = tomllib.loads((ROOT / "config" / "project_claims.toml").read_text(encoding="utf-8"))
    production = manifest["production"]

    assert production["status"] == "candidate"
    assert failure_evidence in manifest["required_evidence"]
    assert failure_evidence in VALIDATOR_INPUTS
    assert historical_start in manifest["required_evidence"]
    assert (ROOT / historical_start).is_file()
    assert production.get("latest_soak_attempt") != historical_start
    assert production.get("latest_soak_attempt") == failure_evidence
    assert production.get("latest_soak_attempt_result") == (
        "soak-fail-unresolved-flink-terminal-failure"
    )
    assert production.get("pending_acceptance", []) == remaining_pending
    assert (ROOT / failure_evidence).is_file()
    failure_text = (ROOT / failure_evidence).read_text(encoding="utf-8")
    assert "SOAK_FAIL" in failure_text
    assert "UNRESOLVED_FLINK_TERMINAL_FAILURE" in failure_text
    assert "not" in failure_text.lower()
    assert "production" in failure_text.lower()
    historical_text = (ROOT / historical_start).read_text(encoding="utf-8")
    assert "SOAK_RUNNING" in historical_text


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

    assert "-f src/agentflow_runtime/processing/flink_jobs/Dockerfile" not in text


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

    dockerfile = (
        fixture_root / "src" / "agentflow_runtime" / "processing" / "flink_jobs" / "Dockerfile"
    )
    original = dockerfile.read_text(encoding="utf-8")
    dockerfile.write_text(
        original.replace(original.splitlines()[0], "FROM python:3.11-slim", 1),
        encoding="utf-8",
    )

    errors = validate_repository(fixture_root)

    assert any(
        "src/agentflow_runtime/processing/flink_jobs/Dockerfile" in error
        and "official Flink base image" in error
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
