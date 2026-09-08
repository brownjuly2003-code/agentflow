"""The pip-audit gate suppresses findings only through validated waivers (FB-02).

`pip-audit` accepts `--ignore-vuln`, and reaching for it in the workflow would
have been the short way to turn this job green after nltk 3.10.3 picked up an
advisory upstream has not fixed. A flag in YAML expires on nobody's calendar,
matches nothing in particular, and survives the fix it is hiding. These tests
pin the alternative: the same waiver file the Trivy and Safety gates already
answer to, with the same three fail-closed properties -- unwaived findings fail,
expired waivers fail, and a waiver that has stopped matching fails.

The last one is what makes an unfixed advisory safe to waive at all. The waiver
claims "upstream has published no fix"; the day pip-audit reports a fix version
the claim is false, the finding goes back to unwaived, and the job goes red on
the release that is now available.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from scripts import run_pip_audit_scan
from scripts.run_pip_audit_scan import (
    EXIT_AUDIT_FAILED,
    EXIT_AUDIT_UNAVAILABLE,
    EXIT_MALFORMED_WAIVERS,
    EXIT_NO_REQUIREMENTS,
    EXIT_REQUIREMENTS_MISSING_OR_EMPTY,
    EXIT_UNKNOWN_SCOPE,
    audit_command,
    evaluate_audit,
    findings_from_report,
)
from tests.unit import test_security_workflow as security_workflow

ROOT = Path(__file__).resolve().parents[2]
WAIVERS_PATH = ROOT / "security" / "trivy-waivers.json"
PYTHON_PROFILES = "python-profiles"
NLTK_ADVISORY = "PYSEC-2026-3740"
TODAY = date(2026, 9, 7)


def _vuln(
    vulnerability_id: str = NLTK_ADVISORY,
    aliases: list[str] | None = None,
    fix_versions: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": vulnerability_id,
        "aliases": aliases if aliases is not None else ["CVE-2026-81726", "GHSA-8mgp-746c-j5xp"],
        "fix_versions": fix_versions or [],
    }


def _report(*, package: str = "nltk", version: str = "3.10.3", **kwargs: Any) -> dict[str, Any]:
    return {
        "dependencies": [
            {"name": "click", "version": "8.5.0", "vulns": []},
            {"name": package, "version": version, "vulns": [_vuln(**kwargs)]},
        ]
    }


def _waiver(
    vulnerability_id: str = NLTK_ADVISORY,
    package: str = "nltk",
    installed_version: str = "3.10.3",
    fixed_version: str | None = None,
    expires_on: str = "2026-11-01",
) -> dict[str, Any]:
    return {
        "id": vulnerability_id,
        "package": package,
        "installed_version": installed_version,
        "fixed_version": fixed_version,
        "expires_on": expires_on,
        "disposition": "not_affected",
        "rationale": "The affected model-persistence APIs are never imported.",
        "removal_condition": "Remove when upstream publishes a fix.",
    }


def _policy(*waivers: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "scopes": {PYTHON_PROFILES: {"owner": "security", "waivers": list(waivers)}},
    }


def _evaluate(report: dict[str, Any], *waivers: dict[str, Any]) -> dict[str, Any]:
    return evaluate_audit(report, waivers, scope_name=PYTHON_PROFILES, as_of=TODAY)


# --- report parsing ---------------------------------------------------------


def test_findings_carry_the_package_that_declared_them() -> None:
    findings = findings_from_report(_report())

    assert [finding["package"] for finding in findings] == ["nltk"]
    assert findings[0]["installed_version"] == "3.10.3"
    assert findings[0]["id"] == NLTK_ADVISORY
    assert findings[0]["fix_versions"] == []


def test_an_empty_report_has_no_findings() -> None:
    assert findings_from_report({}) == []
    assert findings_from_report({"dependencies": [{"name": "click", "version": "8.5.0"}]}) == []


# --- waiving ----------------------------------------------------------------


def test_an_active_waiver_covers_its_finding() -> None:
    summary = _evaluate(_report(), _waiver())

    assert summary["status"] == "ok"
    assert [finding["id"] for finding in summary["waived"]] == [NLTK_ADVISORY]
    assert summary["waived"][0]["expires_on"] == "2026-11-01"
    assert summary["unwaived"] == []


def test_a_waiver_may_cite_any_alias_of_the_advisory() -> None:
    """pip-audit prints PYSEC for a PyPI advisory; GitHub and Trivy say GHSA and
    CVE for the same thing. Demanding one spelling would make a correct waiver
    read as if it covered something else."""
    summary = _evaluate(_report(), _waiver(vulnerability_id="GHSA-8mgp-746c-j5xp"))

    assert summary["status"] == "ok"
    assert [finding["id"] for finding in summary["waived"]] == [NLTK_ADVISORY]


def test_an_unwaived_finding_fails() -> None:
    summary = _evaluate(_report())

    assert summary["status"] == "failed"
    assert [finding["id"] for finding in summary["unwaived"]] == [NLTK_ADVISORY]


def test_an_expired_waiver_stops_covering_its_finding() -> None:
    summary = _evaluate(_report(), _waiver(expires_on="2026-09-06"))

    assert summary["status"] == "failed"
    assert [waiver["id"] for waiver in summary["expired_waivers"]] == [NLTK_ADVISORY]
    assert summary["waived"] == []


def test_a_waiver_that_matches_nothing_fails_instead_of_lingering() -> None:
    """A waiver nobody removed after the dependency went away still reads as an
    accepted risk. Failing on it is what keeps the file an inventory rather than
    a graveyard."""
    summary = _evaluate({"dependencies": []}, _waiver())

    assert summary["status"] == "failed"
    assert [waiver["id"] for waiver in summary["stale_waivers"]] == [NLTK_ADVISORY]


# --- the watchdog: a waiver's premise is part of the match ------------------


def test_a_published_fix_revokes_an_unfixed_waiver() -> None:
    """The whole risk of waiving an unfixed advisory is that the waiver outlives
    the fix. `fixed_version: null` is a claim about upstream, not a wildcard --
    the day pip-audit reports a fix version, the claim is false and the gate
    goes red on the release that is now available."""
    summary = _evaluate(_report(fix_versions=["3.10.4"]), _waiver(fixed_version=None))

    assert summary["status"] == "failed"
    assert [finding["id"] for finding in summary["unwaived"]] == [NLTK_ADVISORY]
    assert [waiver["id"] for waiver in summary["stale_waivers"]] == [NLTK_ADVISORY]


def test_a_waiver_naming_a_fix_matches_only_that_fix() -> None:
    covered = _evaluate(_report(fix_versions=["3.10.4"]), _waiver(fixed_version="3.10.4"))
    superseded = _evaluate(_report(fix_versions=["3.11.0"]), _waiver(fixed_version="3.10.4"))

    assert covered["status"] == "ok"
    assert superseded["status"] == "failed"


def test_a_waiver_does_not_reach_a_different_installed_version() -> None:
    """Version is part of the key: the argument for waiving 3.10.3 was made
    about 3.10.3, and a bump has to be re-argued rather than inherited."""
    summary = _evaluate(_report(version="3.11.0"), _waiver(installed_version="3.10.3"))

    assert summary["status"] == "failed"
    assert [finding["id"] for finding in summary["unwaived"]] == [NLTK_ADVISORY]


def test_a_waiver_does_not_reach_a_different_package() -> None:
    summary = _evaluate(_report(package="regex"), _waiver(package="nltk"))

    assert summary["status"] == "failed"
    assert summary["unwaived"][0]["package"] == "regex"


# --- CLI plumbing -----------------------------------------------------------


def _write(tmp_path: Path, name: str, payload: Any) -> Path:
    path = tmp_path / name
    text = payload if isinstance(payload, str) else json.dumps(payload)
    path.write_text(text, encoding="utf-8")
    return path


def _runner(report: dict[str, Any], returncode: int = 1):
    def run(command, **kwargs):  # type: ignore[no-untyped-def]
        import subprocess

        run.command = list(command)  # type: ignore[attr-defined]
        return subprocess.CompletedProcess(command, returncode, json.dumps(report), "")

    return run


def test_the_audit_command_never_carries_an_ignore_flag() -> None:
    command = audit_command("pip-audit", [Path("requirements.txt")])

    assert "--ignore-vuln" not in command
    assert command[:2] == ["pip-audit", "--no-deps"]
    assert "--format" in command
    assert command[command.index("--format") + 1] == "json"


def test_main_is_green_when_every_finding_is_waived(tmp_path: Path) -> None:
    requirements = _write(tmp_path, "requirements.txt", "nltk==3.10.3\n")
    waivers = _write(tmp_path, "waivers.json", _policy(_waiver()))

    exit_code = run_pip_audit_scan.main(
        [
            "--waivers",
            str(waivers),
            "--scope",
            PYTHON_PROFILES,
            "--as-of",
            TODAY.isoformat(),
            "-r",
            str(requirements),
        ],
        runner=_runner(_report()),
    )

    assert exit_code == 0


def test_main_fails_on_an_unwaived_finding(tmp_path: Path) -> None:
    """pip-audit's own exit code is not consulted -- the verdict comes from the
    report, so a scanner that starts exiting 0 on findings cannot quietly turn
    this gate green."""
    requirements = _write(tmp_path, "requirements.txt", "nltk==3.10.3\n")
    waivers = _write(tmp_path, "waivers.json", _policy())

    exit_code = run_pip_audit_scan.main(
        [
            "--waivers",
            str(waivers),
            "--scope",
            PYTHON_PROFILES,
            "-r",
            str(requirements),
        ],
        runner=_runner(_report(), returncode=0),
    )

    assert exit_code == EXIT_AUDIT_FAILED


def test_main_refuses_without_requirements(tmp_path: Path) -> None:
    waivers = _write(tmp_path, "waivers.json", _policy(_waiver()))

    assert (
        run_pip_audit_scan.main(
            ["--waivers", str(waivers), "--scope", PYTHON_PROFILES],
            runner=_runner(_report()),
        )
        == EXIT_NO_REQUIREMENTS
    )


def test_main_refuses_an_empty_requirements_file(tmp_path: Path) -> None:
    requirements = _write(tmp_path, "requirements.txt", "   \n")
    waivers = _write(tmp_path, "waivers.json", _policy(_waiver()))

    assert (
        run_pip_audit_scan.main(
            [
                "--waivers",
                str(waivers),
                "--scope",
                PYTHON_PROFILES,
                "-r",
                str(requirements),
            ],
            runner=_runner(_report()),
        )
        == EXIT_REQUIREMENTS_MISSING_OR_EMPTY
    )


def test_main_refuses_an_unknown_scope(tmp_path: Path) -> None:
    requirements = _write(tmp_path, "requirements.txt", "nltk==3.10.3\n")
    waivers = _write(tmp_path, "waivers.json", _policy(_waiver()))

    assert (
        run_pip_audit_scan.main(
            ["--waivers", str(waivers), "--scope", "nope", "-r", str(requirements)],
            runner=_runner(_report()),
        )
        == EXIT_UNKNOWN_SCOPE
    )


def test_a_malformed_waiver_in_any_scope_fails_the_run(tmp_path: Path) -> None:
    """Validation covers the whole file, not the scanned scope: a broken entry
    must not sit in an unscanned scope waiting to be trusted later."""
    requirements = _write(tmp_path, "requirements.txt", "nltk==3.10.3\n")
    broken = _waiver()
    del broken["fixed_version"]
    policy = _policy(_waiver())
    policy["scopes"]["other"] = {"waivers": [broken]}
    waivers = _write(tmp_path, "waivers.json", policy)

    assert (
        run_pip_audit_scan.main(
            [
                "--waivers",
                str(waivers),
                "--scope",
                PYTHON_PROFILES,
                "-r",
                str(requirements),
            ],
            runner=_runner(_report()),
        )
        == EXIT_MALFORMED_WAIVERS
    )


def test_unparseable_scanner_output_fails_closed(tmp_path: Path) -> None:
    """No JSON means no verdict. Treating silence as "nothing found" is how a
    crashed scanner passes a gate."""
    requirements = _write(tmp_path, "requirements.txt", "nltk==3.10.3\n")
    waivers = _write(tmp_path, "waivers.json", _policy(_waiver()))

    def run(command, **kwargs):  # type: ignore[no-untyped-def]
        import subprocess

        return subprocess.CompletedProcess(command, 2, "Traceback (most recent call last)", "")

    assert (
        run_pip_audit_scan.main(
            [
                "--waivers",
                str(waivers),
                "--scope",
                PYTHON_PROFILES,
                "-r",
                str(requirements),
            ],
            runner=run,
        )
        == EXIT_AUDIT_UNAVAILABLE
    )


# --- the repository's own policy and workflow -------------------------------


def _repo_policy() -> dict[str, Any]:
    return json.loads(WAIVERS_PATH.read_text(encoding="utf-8"))


def test_the_repo_python_profile_scope_waives_only_the_unfixed_nltk_advisory() -> None:
    waivers = _repo_policy()["scopes"][PYTHON_PROFILES]["waivers"]

    assert [
        (waiver["id"], waiver["package"], waiver["installed_version"], waiver["fixed_version"])
        for waiver in waivers
    ] == [(NLTK_ADVISORY, "nltk", "3.10.3", None)]
    waiver = waivers[0]
    assert waiver["disposition"] == "not_affected"
    assert date.fromisoformat(waiver["expires_on"]) > date.today(), (
        f"waiver {waiver['id']} expired on {waiver['expires_on']}; re-argue it or drop it"
    )
    assert "nltk" in waiver["rationale"]
    assert "pathsec" in waiver["rationale"]
    assert waiver["removal_condition"]


def test_the_repo_policy_validates_under_the_shared_validator() -> None:
    policy = _repo_policy()

    assert run_pip_audit_scan.scope_waivers(policy, PYTHON_PROFILES)


def test_no_source_file_imports_the_package_the_waiver_calls_unreachable() -> None:
    """The rationale is the waiver. If `nltk` ever gets imported the argument is
    void, and this is the assertion that notices."""
    roots = [ROOT / "src", ROOT / "sdk", ROOT / "integrations"]
    offenders = [
        path
        for root in roots
        if root.exists()
        for path in root.rglob("*.py")
        if "nltk" in path.read_text(encoding="utf-8")
    ]

    assert offenders == [], f"nltk is referenced in {offenders}; the FB-02 waiver no longer holds"


def _pip_audit_step(name: str) -> dict[str, Any]:
    return security_workflow._step("pip-audit", name)


def test_the_workflow_never_passes_an_ignore_flag_to_pip_audit() -> None:
    for name in (
        "Audit the locked production dependency set",
        "Audit the full locked profile set (all extras, dev included)",
    ):
        executable = " ".join(security_workflow._run_lines(_pip_audit_step(name)))
        assert "--ignore-vuln" not in executable, (
            f"{name} suppresses a finding with a flag; waivers belong in {WAIVERS_PATH.name}"
        )


def test_the_production_lock_is_audited_with_no_waiver_mechanism_at_all() -> None:
    """The one inventory that ships. A finding there is a release blocker, so
    the scanner that can read waivers is deliberately not in its path."""
    step = _pip_audit_step("Audit the locked production dependency set")

    assert step["run"].strip() == "pip-audit --no-deps -r requirements-docker.lock"
    assert "run_pip_audit_scan" not in step["run"]


def test_the_scope_the_workflow_names_exists_in_the_policy() -> None:
    step = _pip_audit_step("Audit the full locked profile set (all extras, dev included)")
    tokens = " ".join(security_workflow._run_lines(step)).replace(" \\ ", " ").split()
    scope = tokens[tokens.index("--scope") + 1]

    assert scope in _repo_policy()["scopes"]
    assert scope == PYTHON_PROFILES


@pytest.mark.parametrize("field", ["rationale", "removal_condition", "expires_on"])
def test_every_waiver_in_the_file_still_carries_its_argument(field: str) -> None:
    for scope in _repo_policy()["scopes"].values():
        for waiver in scope.get("waivers") or []:
            assert waiver.get(field), f"waiver {waiver.get('id')} has no {field}"
