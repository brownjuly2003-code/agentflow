"""Audit a locked requirements export with pip-audit under expiring waivers.

`pip-audit` has an `--ignore-vuln` flag, but passing it from the workflow would
put the suppression in YAML where nothing validates it, nothing expires it, and
nothing notices when it stops matching anything. This runner keeps the same
contract the Trivy and Safety gates already have (audit FB-02): every waiver is
validated by `scripts.evaluate_trivy_policy.validate_waiver`, an expired waiver
suppresses nothing, and an active waiver that matches no finding fails the job
rather than lingering.

So pip-audit runs with no ignores at all and emits JSON; the waiving happens
here, where it can be argued with. The fix state is part of the match: a waiver
that claims upstream has published no fix stops matching the moment upstream
publishes one, and the gate goes red on the release that is now available.

The production image lock is deliberately *not* routed through this script. It
is audited bare, with no waiver mechanism reachable at all.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.evaluate_trivy_policy import validate_waiver

EXIT_AUDIT_FAILED = 1
EXIT_NO_REQUIREMENTS = 2
EXIT_REQUIREMENTS_MISSING_OR_EMPTY = 3
EXIT_UNKNOWN_SCOPE = 4
EXIT_AUDIT_UNAVAILABLE = 5
EXIT_MALFORMED_WAIVERS = 6

Finding = dict[str, Any]
Waiver = dict[str, Any]
Runner = Callable[..., subprocess.CompletedProcess[str]]


class PipAuditScanError(Exception):
    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def _today() -> date:
    return datetime.now(UTC).date()


def load_policy(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PipAuditScanError(
            f"malformed waiver file: cannot read {path}: {exc}",
            EXIT_MALFORMED_WAIVERS,
        ) from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise PipAuditScanError(
            f"unsupported waiver policy schema in {path}",
            EXIT_MALFORMED_WAIVERS,
        )
    return payload


def scope_waivers(policy: dict[str, Any], scope_name: str) -> list[Waiver]:
    """Return the named scope's waivers, validating *every* scope on the way.

    Validating the whole file rather than one scope is deliberate: a malformed
    waiver anywhere must fail whichever gate runs first, so a broken entry
    cannot sit in an unscanned scope waiting to be trusted later.
    """
    scopes = policy.get("scopes")
    if not isinstance(scopes, dict):
        raise PipAuditScanError("waiver policy has no scopes", EXIT_MALFORMED_WAIVERS)
    for scope in scopes.values():
        for waiver in scope.get("waivers") or []:
            try:
                validate_waiver(waiver)
            except ValueError as exc:
                raise PipAuditScanError(str(exc), EXIT_MALFORMED_WAIVERS) from exc
    if scope_name not in scopes:
        raise PipAuditScanError(f"unknown waiver scope: {scope_name}", EXIT_UNKNOWN_SCOPE)
    return list(scopes[scope_name].get("waivers") or [])


def findings_from_report(report: dict[str, Any]) -> list[Finding]:
    """Flatten pip-audit's per-dependency JSON into one finding per advisory."""
    findings: list[Finding] = []
    for dependency in report.get("dependencies") or []:
        package = str(dependency.get("name") or "")
        installed = str(dependency.get("version") or "")
        for vulnerability in dependency.get("vulns") or []:
            fix_versions = [str(item) for item in vulnerability.get("fix_versions") or []]
            findings.append(
                {
                    "id": str(vulnerability.get("id") or ""),
                    "aliases": [str(item) for item in vulnerability.get("aliases") or []],
                    "package": package,
                    "installed_version": installed,
                    "fix_versions": fix_versions,
                }
            )
    return findings


def _identifies(waiver: Waiver, finding: Finding) -> bool:
    """Advisory IDs are aliased across databases.

    pip-audit prints the PYSEC id for a PyPI advisory while GitHub and Trivy
    name the same thing GHSA or CVE. A waiver may cite any of them; requiring
    one spelling would make the waiver read as if it covered something else.
    """
    waiver_id = str(waiver.get("id") or "")
    return bool(waiver_id) and waiver_id in {finding["id"], *finding["aliases"]}


def _fix_state_agrees(waiver: Waiver, finding: Finding) -> bool:
    """A waiver stops matching once its premise about the fix changes.

    ``fixed_version: null`` is the claim "upstream has published no fix". When
    upstream publishes one, pip-audit starts reporting it in ``fix_versions``,
    the claim is false, and the finding goes back to unwaived -- the gate turns
    red on the release that is now available rather than staying quiet.
    """
    fixed_version = waiver.get("fixed_version")
    if fixed_version is None:
        return not finding["fix_versions"]
    return str(fixed_version) in finding["fix_versions"]


def _matches(waiver: Waiver, finding: Finding) -> bool:
    return (
        _identifies(waiver, finding)
        and str(waiver.get("package") or "") == finding["package"]
        and str(waiver.get("installed_version") or "") == finding["installed_version"]
        and _fix_state_agrees(waiver, finding)
    )


def evaluate_audit(
    report: dict[str, Any],
    waivers: Sequence[Waiver],
    *,
    scope_name: str,
    as_of: date,
) -> dict[str, Any]:
    """Return a fail-closed summary of one pip-audit report against waivers."""
    findings = findings_from_report(report)

    waived: list[Finding] = []
    unwaived: list[Finding] = []
    expired_waivers: list[Waiver] = []
    matched: set[int] = set()
    for finding in findings:
        waiver = next((item for item in waivers if _matches(item, finding)), None)
        if waiver is None:
            unwaived.append(finding)
            continue
        matched.add(id(waiver))
        if date.fromisoformat(str(waiver["expires_on"])) < as_of:
            expired_waivers.append(waiver)
            continue
        waived.append(
            {
                **finding,
                "expires_on": waiver["expires_on"],
                "disposition": waiver["disposition"],
                "rationale": waiver["rationale"],
                "removal_condition": waiver["removal_condition"],
            }
        )

    stale_waivers = [waiver for waiver in waivers if id(waiver) not in matched]
    failed = bool(unwaived or expired_waivers or stale_waivers)
    return {
        "status": "failed" if failed else "ok",
        "scope": scope_name,
        "evaluated_as_of": as_of.isoformat(),
        "finding_count": len(findings),
        "waived": waived,
        "unwaived": unwaived,
        "expired_waivers": expired_waivers,
        "stale_waivers": stale_waivers,
    }


def _validate_requirements(paths: Sequence[Path]) -> None:
    problems: list[str] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            problems.append(str(path))
            continue
        if not text.strip():
            problems.append(str(path))
    if problems:
        raise PipAuditScanError(
            "requirements file missing or empty: " + ", ".join(problems),
            EXIT_REQUIREMENTS_MISSING_OR_EMPTY,
        )


def audit_command(pip_audit_cmd: str, requirements: Sequence[Path]) -> list[str]:
    command = [pip_audit_cmd, "--no-deps", "--format", "json", "--progress-spinner", "off"]
    for path in requirements:
        command.extend(["-r", str(path)])
    return command


def run_audit(
    command: Sequence[str],
    runner: Runner,
) -> dict[str, Any]:
    try:
        result = runner(list(command), capture_output=True, text=True, check=False)
    except OSError as exc:
        raise PipAuditScanError(
            f"failed to start pip-audit: {exc}",
            EXIT_AUDIT_UNAVAILABLE,
        ) from exc
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise PipAuditScanError(
            f"pip-audit produced no parseable JSON (exit {result.returncode}): {exc}",
            EXIT_AUDIT_UNAVAILABLE,
        ) from exc
    if not isinstance(payload, dict):
        raise PipAuditScanError(
            "pip-audit JSON report is not an object",
            EXIT_AUDIT_UNAVAILABLE,
        )
    return payload


def _describe(finding: Finding) -> str:
    fixes = ", ".join(finding["fix_versions"]) or "no fix published"
    return f"{finding['id']} {finding['package']}=={finding['installed_version']} (fix: {fixes})"


def _report_summary(summary: dict[str, Any]) -> None:
    print(f"pip-audit scope: {summary['scope']} ({summary['finding_count']} findings)")
    for finding in summary["waived"]:
        print(f"  waived   {_describe(finding)} until {finding['expires_on']}")
    for finding in summary["unwaived"]:
        print(f"  UNWAIVED {_describe(finding)}", file=sys.stderr)
    for waiver in summary["expired_waivers"]:
        print(
            f"  EXPIRED  waiver {waiver['id']} for {waiver['package']} "
            f"lapsed on {waiver['expires_on']}",
            file=sys.stderr,
        )
    for waiver in summary["stale_waivers"]:
        print(
            f"  STALE    waiver {waiver['id']} for {waiver['package']} matches no finding; "
            "drop it or correct it",
            file=sys.stderr,
        )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--waivers", type=Path, default=Path("security/trivy-waivers.json"))
    parser.add_argument("--scope", required=True)
    parser.add_argument(
        "-r",
        "--requirements",
        action="append",
        type=Path,
        default=[],
        dest="requirements",
    )
    parser.add_argument("--as-of", type=date.fromisoformat)
    parser.add_argument("--pip-audit-cmd", default="pip-audit")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, runner: Runner = subprocess.run) -> int:
    args = _parse_args(argv)
    requirements: list[Path] = list(args.requirements)
    if not requirements:
        print(
            "no requirements given; pass one or more -r/--requirements",
            file=sys.stderr,
        )
        return EXIT_NO_REQUIREMENTS

    try:
        policy = load_policy(args.waivers)
        waivers = scope_waivers(policy, args.scope)
        _validate_requirements(requirements)
        report = run_audit(audit_command(args.pip_audit_cmd, requirements), runner)
    except PipAuditScanError as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code

    summary = evaluate_audit(
        report,
        waivers,
        scope_name=args.scope,
        as_of=args.as_of or _today(),
    )
    _report_summary(summary)
    return 0 if summary["status"] == "ok" else EXIT_AUDIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
