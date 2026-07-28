"""Evaluate a filtered Trivy JSON report against narrow, expiring waivers."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

Finding = dict[str, Any]
Waiver = dict[str, Any]


def _finding_key(item: Finding) -> tuple[str, str, str, str]:
    return (
        str(item.get("VulnerabilityID") or item.get("id") or ""),
        str(item.get("PkgName") or item.get("package") or ""),
        str(item.get("InstalledVersion") or item.get("installed_version") or ""),
        str(item.get("FixedVersion") or item.get("fixed_version") or ""),
    )


def _waiver_key(item: Waiver) -> tuple[str, str, str, str]:
    return (
        str(item.get("id") or ""),
        str(item.get("package") or ""),
        str(item.get("installed_version") or ""),
        str(item.get("fixed_version") or ""),
    )


def _normalized_finding(item: Finding, target: str) -> Finding:
    vulnerability_id, package, installed, fixed = _finding_key(item)
    return {
        "id": vulnerability_id,
        "package": package,
        "installed_version": installed,
        "fixed_version": fixed,
        "severity": item.get("Severity"),
        "target": target,
    }


def _validate_waiver(item: Waiver) -> None:
    required = (
        "id",
        "package",
        "installed_version",
        "fixed_version",
        "expires_on",
        "disposition",
        "rationale",
        "removal_condition",
    )
    missing = [field for field in required if not item.get(field)]
    if missing:
        raise ValueError(f"waiver is missing required fields {missing}: {item}")
    if item["disposition"] != "not_affected":
        raise ValueError(f"unsupported waiver disposition: {item['disposition']}")
    date.fromisoformat(str(item["expires_on"]))


def evaluate_report(
    report: dict[str, Any],
    policy: dict[str, Any],
    *,
    scope_name: str,
    as_of: date,
) -> dict[str, Any]:
    """Return a fail-closed policy summary for one Trivy image scope."""
    if policy.get("schema_version") != 1:
        raise ValueError("unsupported waiver policy schema")
    try:
        scope = policy["scopes"][scope_name]
    except KeyError as exc:
        raise ValueError(f"unknown waiver scope: {scope_name}") from exc

    waivers = list(scope.get("waivers") or [])
    for waiver in waivers:
        _validate_waiver(waiver)
    keys = [_waiver_key(waiver) for waiver in waivers]
    if len(keys) != len(set(keys)):
        raise ValueError(f"duplicate waiver key in scope {scope_name}")
    waivers_by_key = dict(zip(keys, waivers, strict=True))

    findings: list[Finding] = []
    for result in report.get("Results") or []:
        target = str(result.get("Target") or "")
        for item in result.get("Vulnerabilities") or []:
            findings.append(_normalized_finding(item, target))

    matched_keys: set[tuple[str, str, str, str]] = set()
    waived: list[Finding] = []
    unwaived: list[Finding] = []
    expired_waivers: list[Waiver] = []
    for finding in findings:
        key = _finding_key(finding)
        waiver = waivers_by_key.get(key)
        if waiver is None:
            unwaived.append(finding)
            continue
        matched_keys.add(key)
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

    stale_waivers = [waiver for key, waiver in waivers_by_key.items() if key not in matched_keys]
    failed = bool(unwaived or expired_waivers or stale_waivers)
    return {
        "schema_version": 1,
        "status": "failed" if failed else "ok",
        "scope": scope_name,
        "image": scope.get("image"),
        "evaluated_as_of": as_of.isoformat(),
        "finding_count": len(findings),
        "waived_count": len(waived),
        "waived": waived,
        "unwaived": unwaived,
        "expired_waivers": expired_waivers,
        "stale_waivers": stale_waivers,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--waivers", type=Path, required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--as-of", type=date.fromisoformat)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    policy = json.loads(args.waivers.read_text(encoding="utf-8"))
    as_of = args.as_of or datetime.now(UTC).date()
    summary = evaluate_report(report, policy, scope_name=args.scope, as_of=as_of)
    args.output.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "status": summary["status"],
                "findings": summary["finding_count"],
                "waived": summary["waived_count"],
                "unwaived": len(summary["unwaived"]),
                "expired": len(summary["expired_waivers"]),
                "stale": len(summary["stale_waivers"]),
            },
            sort_keys=True,
        )
    )
    return 0 if summary["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
