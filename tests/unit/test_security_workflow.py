from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TRIVY_ARTIFACT_DIR = ".artifacts/trivy"
TRIVY_ACTION_PREFIX = "aquasecurity/trivy-action@"
EVALUATOR = "scripts/evaluate_trivy_policy.py"
CANONICAL_TRIVY_OUTPUTS = {
    f"{TRIVY_ARTIFACT_DIR}/agentflow-api.cdx.json",
    f"{TRIVY_ARTIFACT_DIR}/agentflow-flink.cdx.json",
    f"{TRIVY_ARTIFACT_DIR}/trivy-api.json",
    f"{TRIVY_ARTIFACT_DIR}/trivy-flink.json",
    f"{TRIVY_ARTIFACT_DIR}/trivy-api.sarif",
    f"{TRIVY_ARTIFACT_DIR}/trivy-flink.sarif",
    f"{TRIVY_ARTIFACT_DIR}/trivy-api-policy.json",
    f"{TRIVY_ARTIFACT_DIR}/trivy-flink-policy.json",
    f"{TRIVY_ARTIFACT_DIR}/trivy-iac.sarif",
}


def _load_security_workflow() -> dict:
    workflow_path = PROJECT_ROOT / ".github" / "workflows" / "security.yml"
    return yaml.safe_load(workflow_path.read_text(encoding="utf-8"))


def _job(name: str) -> dict:
    return _load_security_workflow()["jobs"][name]


def _is_trivy_writer(step: dict) -> bool:
    uses = str(step.get("uses", ""))
    if uses.startswith(TRIVY_ACTION_PREFIX):
        return True
    run = step.get("run")
    return isinstance(run, str) and EVALUATOR in run


def _prepare_step_indexes(steps: list[dict]) -> list[int]:
    return [
        index
        for index, step in enumerate(steps)
        if isinstance(step.get("run"), str) and "mkdir -p .artifacts/trivy" in step["run"]
    ]


def test_trivy_job_generates_cyclonedx_sbom_artifact() -> None:
    workflow = _load_security_workflow()
    steps = workflow["jobs"]["trivy"]["steps"]

    sbom_step = next(
        (step for step in steps if step.get("name") == "Generate CycloneDX SBOM"),
        None,
    )
    assert sbom_step is not None
    assert str(sbom_step["uses"]).startswith("aquasecurity/trivy-action@")
    assert sbom_step["with"] == {
        "image-ref": "agentflow-api:security-scan",
        "format": "cyclonedx",
        "output": ".artifacts/trivy/agentflow-api.cdx.json",
    }

    upload_step = next(
        (step for step in steps if step.get("name") == "Upload CycloneDX SBOM"),
        None,
    )
    assert upload_step is not None
    assert str(upload_step["uses"]).startswith("actions/upload-artifact@")
    assert upload_step["with"]["name"] == "agentflow-api-sbom-cyclonedx"
    assert upload_step["with"]["path"] == ".artifacts/trivy/agentflow-api.cdx.json"
    assert upload_step["with"]["if-no-files-found"] == "error"


def test_trivy_and_iac_jobs_prepare_canonical_artifact_directory() -> None:
    for job_name in ("trivy", "iac"):
        steps = _job(job_name)["steps"]
        prepare = _prepare_step_indexes(steps)
        assert prepare, f"{job_name} must create {TRIVY_ARTIFACT_DIR} before writers"
        writer = next(index for index, step in enumerate(steps) if _is_trivy_writer(step))
        assert prepare[0] < writer, f"{job_name} must mkdir before the first Trivy writer"


def test_all_trivy_outputs_and_consumers_live_under_canonical_directory() -> None:
    found: set[str] = set()
    for job_name in ("trivy", "iac"):
        for step in _job(job_name)["steps"]:
            with_block = step.get("with") or {}
            uses = str(step.get("uses", ""))
            if uses.startswith(TRIVY_ACTION_PREFIX) and "output" in with_block:
                found.add(with_block["output"])
            if uses.startswith("actions/upload-artifact@") and "path" in with_block:
                found.add(with_block["path"])
            if uses.startswith("github/codeql-action/upload-sarif@") and "sarif_file" in with_block:
                found.add(with_block["sarif_file"])
            run = step.get("run")
            if not isinstance(run, str) or EVALUATOR not in run:
                continue
            for token in run.split():
                if token.startswith(f"{TRIVY_ARTIFACT_DIR}/") or token.endswith(
                    (
                        "trivy-api.json",
                        "trivy-flink.json",
                        "trivy-api-policy.json",
                        "trivy-flink-policy.json",
                    )
                ):
                    found.add(token)

    assert found == CANONICAL_TRIVY_OUTPUTS
    assert all(path.startswith(f"{TRIVY_ARTIFACT_DIR}/") for path in found)


SECURITY_ARTIFACT_DIR = ".artifacts/security"
BANDIT_REPORT = f"{SECURITY_ARTIFACT_DIR}/bandit-current.json"
SAFETY_WORK_DIR = f"{SECURITY_ARTIFACT_DIR}/safety"
PIP_AUDIT_EXPORT = f"{SECURITY_ARTIFACT_DIR}/pip-audit/requirements-all-profiles.txt"
SAFETY_EXTRAS = ("cloud", "postgres", "integrations", "load", "contract")
SAFETY_BUCKETS = frozenset(
    {
        "requirements-main.txt",
        "requirements-sdk.txt",
        "requirements-integrations.txt",
        "requirements-flink-runtime.txt",
        *(f"requirements-extra-{extra}.txt" for extra in SAFETY_EXTRAS),
    }
)
# Working paths the dependency scanners used before 2026-09-01: bandit wrote to
# a system temp dir, the local docs named .tmp/ (both match "tmp/bandit"), and
# Safety/pip-audit used a repository-root workdir. None may reappear.
LEGACY_SCANNER_PATHS = ("tmp/bandit", ".tmp-security")


def _step(job_name: str, step_name: str) -> dict:
    step = next(
        (item for item in _job(job_name)["steps"] if item.get("name") == step_name),
        None,
    )
    assert step is not None, f"step not found: {job_name} / {step_name}"
    return step


def _run_lines(step: dict) -> list[str]:
    run = step["run"]
    assert isinstance(run, str)
    return [
        line.strip()
        for line in run.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _joined_run(step: dict) -> str:
    # Fold shell line continuations so multi-line commands compare as one.
    return " ".join(step["run"].replace("\\\n", " ").split())


def _requirement_inputs(step: dict) -> set[str]:
    tokens = _joined_run(step).split()
    return {tokens[index + 1] for index, arg in enumerate(tokens[:-1]) if arg == "-r"}


def test_bandit_job_writes_ignored_canonical_report_and_diffs_it() -> None:
    assert _run_lines(_step("bandit", "Run Bandit")) == [
        f"mkdir -p {SECURITY_ARTIFACT_DIR}",
        (
            "bandit -r src sdk --ini .bandit --severity-level medium -f json "
            f"-o {BANDIT_REPORT} || true"
        ),
        f"python scripts/bandit_diff.py .bandit-baseline.json {BANDIT_REPORT}",
    ]


def test_safety_job_keeps_working_files_under_canonical_directory() -> None:
    resolve = _step("safety", "Resolve Safety dependency inputs")
    probe = _step("safety", "Verify Safety fails on a known vulnerable pin")
    run = _step("safety", "Run Safety")
    inventory = resolve["run"]

    assert 'output_dir = root / ".artifacts" / "security" / "safety"' in inventory
    assert "output_dir.mkdir(parents=True, exist_ok=True)" in inventory
    for bucket in ("main", "sdk", "integrations", "flink-runtime"):
        assert f'output_dir / "requirements-{bucket}.txt"' in inventory
    assert 'output_dir / f"requirements-extra-{extra_name}.txt"' in inventory
    assert (
        'for extra_name in ("cloud", "postgres", "integrations", "load", "contract"):' in inventory
    )

    probe_lines = _run_lines(probe)
    assert probe_lines[0] == f"mkdir -p {SAFETY_WORK_DIR}"
    assert (
        f"printf 'urllib3==1.24.1\\n' > {SAFETY_WORK_DIR}/requirements-regression.txt"
        in probe_lines
    )
    assert (
        f"if safety check -r {SAFETY_WORK_DIR}/requirements-regression.txt "
        f"> {SAFETY_WORK_DIR}/safety-regression.log 2>&1; then"
    ) in probe_lines
    assert _requirement_inputs(probe) == {f"{SAFETY_WORK_DIR}/requirements-regression.txt"}

    # Every bucket the inventory writes is exactly what Safety reads.
    assert _requirement_inputs(run) == {f"{SAFETY_WORK_DIR}/{bucket}" for bucket in SAFETY_BUCKETS}
    assert run["run"].count("--ignore SFTY-20260217-93940") == 1


def test_pip_audit_job_exports_all_profiles_under_canonical_directory() -> None:
    production = _step("pip-audit", "Audit the locked production dependency set")
    all_profiles = _step(
        "pip-audit", "Audit the full locked profile set (all extras, dev included)"
    )
    joined = _joined_run(all_profiles)

    assert production["run"].strip() == "pip-audit --no-deps -r requirements-docker.lock"
    assert f"mkdir -p {SECURITY_ARTIFACT_DIR}/pip-audit" in joined
    assert (
        "uv export --frozen --format requirements-txt --all-extras "
        f"--no-emit-project -o {PIP_AUDIT_EXPORT}"
    ) in joined
    assert f"pip-audit --no-deps -r {PIP_AUDIT_EXPORT}" in joined
    assert _requirement_inputs(all_profiles) == {PIP_AUDIT_EXPORT}


def test_dependency_scanner_jobs_keep_tool_pins_and_timeouts() -> None:
    workflow = _load_security_workflow()

    assert workflow["jobs"]["bandit"]["timeout-minutes"] == 10
    assert workflow["jobs"]["safety"]["timeout-minutes"] == 20
    assert workflow["jobs"]["pip-audit"]["timeout-minutes"] == 10
    assert (
        _step("bandit", "Install Bandit")["run"].strip()
        == "python -m pip install --upgrade pip bandit"
    )
    assert (
        _step("safety", "Install Safety")["run"].strip()
        == 'python -m pip install --upgrade pip "safety<3"'
    )
    assert (
        _step("pip-audit", "Install pip-audit")["run"].strip()
        == 'python -m pip install --upgrade pip "pip-audit>=2.7,<3" uv==0.8.23'
    )


def test_dependency_scanners_leave_no_legacy_working_paths() -> None:
    workflow_text = (PROJECT_ROOT / ".github" / "workflows" / "security.yml").read_text(
        encoding="utf-8"
    )
    gitignore_lines = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    for legacy in LEGACY_SCANNER_PATHS:
        assert legacy not in workflow_text, legacy
    assert ".artifacts/" in gitignore_lines

    for doc_name in ("README.md", "CONTRIBUTING.md"):
        text = (PROJECT_ROOT / doc_name).read_text(encoding="utf-8")
        assert f"mkdir -p {SECURITY_ARTIFACT_DIR}" in text, doc_name
        assert f"-f json -o {BANDIT_REPORT}" in text, doc_name
        assert f"python scripts/bandit_diff.py .bandit-baseline.json {BANDIT_REPORT}" in text, (
            doc_name
        )
        for legacy in LEGACY_SCANNER_PATHS:
            assert legacy not in text, f"{doc_name}: {legacy}"
