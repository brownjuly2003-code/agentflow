import json
from datetime import date, timedelta
from pathlib import Path

from scripts.evaluate_trivy_policy import evaluate_report

ROOT = Path(__file__).resolve().parents[2]


def _report(*vulnerabilities: dict[str, str]) -> dict:
    return {
        "Results": [
            {
                "Target": "Python",
                "Vulnerabilities": list(vulnerabilities),
            }
        ]
    }


def _finding(
    vulnerability_id: str = "CVE-2026-59939",
    package: str = "httplib2",
    installed: str = "0.22.0",
    fixed: str = "0.32.0",
) -> dict[str, str]:
    return {
        "VulnerabilityID": vulnerability_id,
        "PkgName": package,
        "InstalledVersion": installed,
        "FixedVersion": fixed,
        "Severity": "HIGH",
    }


def _policy(*waivers: dict[str, str]) -> dict:
    return {
        "schema_version": 1,
        "scopes": {
            "flink-runtime": {
                "image": "agentflow-flink",
                "waivers": list(waivers),
            }
        },
    }


def _waiver(
    vulnerability_id: str = "CVE-2026-59939",
    package: str = "httplib2",
    installed: str = "0.22.0",
    fixed: str = "0.32.0",
    expires_on: str = "2026-10-27",
) -> dict[str, str]:
    return {
        "id": vulnerability_id,
        "package": package,
        "installed_version": installed,
        "fixed_version": fixed,
        "expires_on": expires_on,
        "disposition": "not_affected",
        "rationale": "The runtime has no reachable HTTP client path.",
        "removal_condition": "Remove when the upstream dependency accepts the fixed release.",
    }


def test_exact_nonexpired_waiver_is_reported_but_passes() -> None:
    summary = evaluate_report(
        _report(_finding()),
        _policy(_waiver()),
        scope_name="flink-runtime",
        as_of=date(2026, 7, 27),
    )

    assert summary["status"] == "ok"
    assert summary["finding_count"] == 1
    assert summary["waived_count"] == 1
    assert summary["unwaived"] == []
    assert summary["expired_waivers"] == []
    assert summary["stale_waivers"] == []


def test_unexpected_finding_fails_closed() -> None:
    summary = evaluate_report(
        _report(_finding(vulnerability_id="CVE-2099-0001")),
        _policy(_waiver()),
        scope_name="flink-runtime",
        as_of=date(2026, 7, 27),
    )

    assert summary["status"] == "failed"
    assert [finding["id"] for finding in summary["unwaived"]] == ["CVE-2099-0001"]
    assert [waiver["id"] for waiver in summary["stale_waivers"]] == ["CVE-2026-59939"]


def test_expired_waiver_fails_closed() -> None:
    summary = evaluate_report(
        _report(_finding()),
        _policy(_waiver(expires_on="2026-07-26")),
        scope_name="flink-runtime",
        as_of=date(2026, 7, 27),
    )

    assert summary["status"] == "failed"
    assert [waiver["id"] for waiver in summary["expired_waivers"]] == ["CVE-2026-59939"]


def test_repo_flink_policy_pins_only_the_two_proven_findings() -> None:
    policy = json.loads(
        (ROOT / "config" / "security-vulnerability-waivers.json").read_text(encoding="utf-8")
    )
    scope = policy["scopes"]["flink-runtime"]
    waivers = scope["waivers"]

    assert scope["image"] == "agentflow-flink"
    assert {
        (
            waiver["id"],
            waiver["package"],
            waiver["installed_version"],
            waiver["fixed_version"],
        )
        for waiver in waivers
    } == {
        ("CVE-2026-59939", "httplib2", "0.22.0", "0.32.0"),
        ("CVE-2026-25087", "pyarrow", "16.1.0", "23.0.1"),
    }
    assert {waiver["expires_on"] for waiver in waivers} == {"2026-10-27"}
    assert all(waiver["disposition"] == "not_affected" for waiver in waivers)
    assert all(waiver["rationale"] for waiver in waivers)
    assert all(waiver["removal_condition"] for waiver in waivers)

    reviewed_on = date.fromisoformat(policy["reviewed_on"])
    assert all(
        reviewed_on < date.fromisoformat(waiver["expires_on"]) <= reviewed_on + timedelta(days=92)
        for waiver in waivers
    )

    flink_job_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src" / "processing" / "flink_jobs").glob("*.py")
    )
    assert "httplib2" not in flink_job_sources
    assert "pyarrow" not in flink_job_sources
