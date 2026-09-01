"""Runtime-artifact ownership closure ratchet for documentation-plan item 6.

Item 6 of `plan_26_08_2026.md` moved every replaceable runtime output family
(benchmarks, quality/evaluation reports, scanner working files, chaos and
mutation reports, promotion evidence, the Terraform plan file, ...) under the
ignored `.artifacts/` root, one family per sub-slice. This module keeps that
outcome from regressing: every artifact a workflow uploads or downloads must
declare a path under `.artifacts/`, and the only paths outside it are the two
documented exceptions below. It also pins the plan's closure paragraph so the
checkbox, the sweep evidence, and the workflows cannot drift apart.
"""

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = PROJECT_ROOT / ".github" / "workflows"
PLAN = PROJECT_ROOT / "plan_26_08_2026.md"
ARTIFACT_ROOT = ".artifacts/"
ARTIFACT_ACTIONS = (
    "actions/upload-artifact@",
    "actions/download-artifact@",
    "actions/upload-pages-artifact@",
)
# Paths that intentionally stay outside `.artifacts/`, keyed by (workflow, raw
# path). Each entry is also named in the item 6 closure paragraph of the plan.
DOCUMENTED_EXCEPTIONS = {
    # Tracked GitHub Pages landing source (site/index.html, logo, og-image):
    # a deployment input, not a generated runtime artifact.
    ("pages.yml", "site"),
    # Resolved at run time to the newest archive under
    # .artifacts/backup-regression/ (pinned separately below).
    ("backup.yml", "${{ steps.backup.outputs.archive_path }}"),
}
BACKUP_ARCHIVE_RESOLUTION = (
    'archive_path="$(ls -1t .artifacts/backup-regression/*.tar.gz | head -n 1)"'
)
BACKUP_OUTPUT_LINE = 'echo "archive_path=$archive_path" >> "$GITHUB_OUTPUT"'
# Written by hand in the plan; kept literal so the sweep outcome is auditable.
CLOSURE_HEADING = "Runtime-artifact ownership closure sweep завершён 2026-09-01"
CLOSURE_RESIDUALS = (
    "`site/`",
    "`${{ steps.backup.outputs.archive_path }}`",
    "tmp/connect-secrets/neon.properties",
    "`requirements-docker.lock`",
    "`--output json`",
)
REGENERATION_CHECKS = (
    "python scripts/generate_contracts.py --check",
    "python scripts/export_openapi.py --check",
    "python scripts/export_sdk_capabilities.py --check",
    "python scripts/export_quality_reference.py --check",
)


def _artifact_steps() -> list[tuple[str, str, str, str | None]]:
    """Return (workflow, job id, action, raw path) for every artifact step."""
    found = []
    for workflow in sorted(WORKFLOWS_DIR.glob("*.yml")):
        data = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        for job_id, job in data["jobs"].items():
            for step in job.get("steps", []):
                uses = str(step.get("uses", ""))
                if uses.startswith(ARTIFACT_ACTIONS):
                    with_block = step.get("with") or {}
                    found.append(
                        (workflow.name, job_id, uses.split("@", 1)[0], with_block.get("path"))
                    )
    return found


def _path_entries(raw: str) -> list[str]:
    # Multi-line `path: |` blocks list one glob per line; `!` lines exclude.
    return [line.strip().lstrip("!") for line in raw.splitlines() if line.strip()]


def test_workflows_exist_and_use_artifact_actions() -> None:
    steps = _artifact_steps()
    assert steps, "no artifact upload/download steps found under .github/workflows"
    # Keep the allowlist honest: every documented exception must still exist.
    assert DOCUMENTED_EXCEPTIONS <= {(name, path) for name, _, _, path in steps}


def test_every_artifact_step_declares_a_path() -> None:
    # download-artifact without `path` extracts into the working directory,
    # which would scatter runtime files over the checkout.
    missing = [
        f"{name}:{job}:{action}" for name, job, action, path in _artifact_steps() if not path
    ]
    assert not missing, "artifact steps without an explicit path:\n" + "\n".join(missing)


def test_every_artifact_path_stays_under_ignored_artifacts_root() -> None:
    gitignore_lines = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ARTIFACT_ROOT in gitignore_lines

    offenders = []
    for name, job, action, path in _artifact_steps():
        if not path or (name, path) in DOCUMENTED_EXCEPTIONS:
            continue
        for entry in _path_entries(str(path)):
            if not entry.startswith(ARTIFACT_ROOT):
                offenders.append(f"{name}:{job}:{action}: {entry}")
    assert not offenders, "artifact paths outside .artifacts/:\n" + "\n".join(offenders)


def test_backup_fixture_path_resolves_under_ignored_artifacts_root() -> None:
    workflow = yaml.safe_load((WORKFLOWS_DIR / "backup.yml").read_text(encoding="utf-8"))
    resolver = next(
        step for step in workflow["jobs"]["backup"]["steps"] if step.get("id") == "backup"
    )

    assert BACKUP_ARCHIVE_RESOLUTION in resolver["run"]
    assert BACKUP_OUTPUT_LINE in resolver["run"]


def test_pages_upload_is_tracked_landing_source_not_a_runtime_artifact() -> None:
    for tracked in ("index.html", "logo.svg", "og-image.png"):
        assert (PROJECT_ROOT / "site" / tracked).is_file(), tracked


def test_plan_item_6_is_closed_with_the_sweep_evidence() -> None:
    plan = " ".join(PLAN.read_text(encoding="utf-8").split())

    assert "- [x] **6. Отделить generated reference.**" in plan
    assert "- [ ] **6. Отделить generated reference.**" not in plan
    assert CLOSURE_HEADING in plan
    for residual in CLOSURE_RESIDUALS:
        assert residual in plan, residual
    for check in REGENERATION_CHECKS:
        assert check in plan, check
    assert "tests/unit/test_runtime_artifact_ownership.py" in plan
    assert "Пункт 6 закрыт." in plan
