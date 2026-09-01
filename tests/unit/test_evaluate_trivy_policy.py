import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

from scripts import evaluate_trivy_policy
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
    policy = json.loads((ROOT / "security" / "trivy-waivers.json").read_text(encoding="utf-8"))
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
        for path in (ROOT / "src" / "agentflow_runtime" / "processing" / "flink_jobs").glob("*.py")
    )
    assert "httplib2" not in flink_job_sources
    assert "pyarrow" not in flink_job_sources


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _run_main(monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setattr(
        sys,
        "argv",
        ["evaluate_trivy_policy.py", *argv],
    )
    return evaluate_trivy_policy.main()


def test_relative_paths_resolve_from_project_root_not_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    relative_report = evaluate_trivy_policy.resolve_cli_path("trivy-api.json")
    relative_waivers = evaluate_trivy_policy.resolve_cli_path("security/trivy-waivers.json")
    relative_output = evaluate_trivy_policy.resolve_cli_path(
        ".artifacts/trivy/trivy-api-policy.json"
    )
    absolute = tmp_path / "outside" / "trivy-api.json"

    assert relative_report == ROOT / "trivy-api.json"
    assert relative_waivers == ROOT / "security" / "trivy-waivers.json"
    assert relative_output == ROOT / ".artifacts" / "trivy" / "trivy-api-policy.json"
    assert evaluate_trivy_policy.resolve_cli_path(absolute) == absolute
    assert evaluate_trivy_policy.resolve_cli_path(str(absolute)) == absolute


def test_main_relative_paths_resolve_from_project_root_after_chdir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    cwd = tmp_path / "elsewhere"
    repo.mkdir()
    cwd.mkdir()
    monkeypatch.setattr(evaluate_trivy_policy, "PROJECT_ROOT", repo)
    monkeypatch.chdir(cwd)

    report = repo / "trivy-api.json"
    waivers = repo / "security" / "trivy-waivers.json"
    output = repo / ".artifacts" / "trivy" / "nested" / "trivy-api-policy.json"
    _write_json(report, _report())
    _write_json(
        waivers,
        {
            "schema_version": 1,
            "scopes": {"api-runtime": {"image": "agentflow-api", "waivers": []}},
        },
    )

    assert (
        _run_main(
            monkeypatch,
            "--report",
            "trivy-api.json",
            "--waivers",
            "security/trivy-waivers.json",
            "--scope",
            "api-runtime",
            "--output",
            ".artifacts/trivy/nested/trivy-api-policy.json",
            "--as-of",
            "2026-07-27",
        )
        == 0
    )
    assert output.is_file()
    assert list(cwd.rglob("*.json")) == []


@pytest.mark.parametrize(
    "output",
    [
        "docs/trivy-api-policy.json",
        "docs/security/nested/trivy-policy.json",
        str(ROOT / "docs" / "trivy-api-policy.json"),
        str(ROOT / "docs" / "archive" / "nested" / "trivy-policy.json"),
    ],
)
def test_docs_output_is_rejected_before_reading_inputs(
    output: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        evaluate_trivy_policy,
        "evaluate_report",
        lambda *_args, **_kwargs: pytest.fail(
            "docs destination validation must run before policy evaluation"
        ),
    )

    with pytest.raises(ValueError, match=r"\.artifacts/trivy"):
        _run_main(
            monkeypatch,
            "--report",
            "definitely-missing-trivy-report.json",
            "--waivers",
            "definitely-missing-trivy-waivers.json",
            "--scope",
            "api-runtime",
            "--output",
            output,
        )
    assert not (ROOT / "docs" / "trivy-api-policy.json").exists()


def test_docs_named_input_outside_repo_docs_is_not_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = tmp_path / "docs" / "historical-trivy.json"
    waivers = tmp_path / "docs" / "waivers.json"
    output = tmp_path / "nested" / "policy.json"
    _write_json(report, _report())
    _write_json(
        waivers,
        {
            "schema_version": 1,
            "scopes": {"api-runtime": {"image": "agentflow-api", "waivers": []}},
        },
    )

    assert (
        _run_main(
            monkeypatch,
            "--report",
            str(report),
            "--waivers",
            str(waivers),
            "--scope",
            "api-runtime",
            "--output",
            str(output),
            "--as-of",
            "2026-07-27",
        )
        == 0
    )
    assert output.is_file()


def test_main_creates_nested_parent_and_writes_utf8_lf_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = tmp_path / "report.json"
    waivers = tmp_path / "waivers.json"
    output = tmp_path / "nested" / "dir" / "trivy-api-policy.json"
    _write_json(report, _report())
    _write_json(
        waivers,
        {
            "schema_version": 1,
            "scopes": {"api-runtime": {"image": "agentflow-api", "waivers": []}},
        },
    )

    assert (
        _run_main(
            monkeypatch,
            "--report",
            str(report),
            "--waivers",
            str(waivers),
            "--scope",
            "api-runtime",
            "--output",
            str(output),
            "--as-of",
            "2026-07-27",
        )
        == 0
    )

    raw = output.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    assert raw.endswith(b"\n")
    assert b"\r" not in raw
    assert payload["status"] == "ok"
    assert raw.decode("utf-8") == json.dumps(payload, indent=2, sort_keys=True) + "\n"


def test_main_returns_1_for_policy_failure_and_still_writes_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = tmp_path / "report.json"
    waivers = tmp_path / "waivers.json"
    output = tmp_path / "nested" / "trivy-flink-policy.json"
    _write_json(report, _report(_finding(vulnerability_id="CVE-2099-0001")))
    _write_json(waivers, _policy(_waiver()))

    assert (
        _run_main(
            monkeypatch,
            "--report",
            str(report),
            "--waivers",
            str(waivers),
            "--scope",
            "flink-runtime",
            "--output",
            str(output),
            "--as-of",
            "2026-07-27",
        )
        == 1
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert [finding["id"] for finding in payload["unwaived"]] == ["CVE-2099-0001"]


def test_docs_contributing_and_plan_name_trivy_runtime_owner() -> None:
    docs_hub = " ".join((ROOT / "docs" / "README.md").read_text(encoding="utf-8").split())
    contributing = " ".join((ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8").split())
    security_audit = (ROOT / "docs" / "security-audit.md").read_text(encoding="utf-8")
    plan = (ROOT / "plan_26_08_2026.md").read_text(encoding="utf-8")

    assert "| Trivy scan policy |" in docs_hub
    assert ".artifacts/trivy/" in docs_hub
    assert "date-stamped" in docs_hub
    assert "python scripts/evaluate_trivy_policy.py" in contributing
    assert ".artifacts/trivy/" in contributing
    assert "project root" in contributing
    assert "date-stamped" in contributing
    assert ".artifacts/trivy/" in security_audit
    assert "Trivy scan-policy runtime-artifact ownership sub-slice" in plan
    assert "- [ ] **6. Отделить generated reference.**" in plan
    assert "Пункт 6 остаётся открыт" in plan
