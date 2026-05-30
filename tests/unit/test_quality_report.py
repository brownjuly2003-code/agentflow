from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import scripts.quality_report as quality_report


def test_resolve_output_path_anchors_relative_paths() -> None:
    assert quality_report.resolve_output_path("docs/quality.md") == (
        quality_report.PROJECT_ROOT / "docs" / "quality.md"
    )


def test_build_generator_command_includes_skip_flags() -> None:
    assert (
        quality_report.build_generator_command(
            skip_docker=True,
            skip_dependency_scans=True,
        )
        == "python scripts/quality_report.py --skip-docker --skip-dependency-scans"
    )


def test_build_requirement_files_reuses_resolved_security_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_build_resolved_requirement_files(temp_path: Path):
        assert temp_path == tmp_path
        paths = (
            temp_path / "requirements-main.txt",
            temp_path / "requirements-sdk.txt",
            temp_path / "requirements-integrations.txt",
        )
        for path in paths:
            path.write_text(f"{path.stem}==1.0.0\n", encoding="utf-8")
        return paths

    monkeypatch.setattr(
        quality_report,
        "build_resolved_requirement_files",
        fake_build_resolved_requirement_files,
    )

    main_requirements, sdk_requirements, integrations_requirements = (
        quality_report.build_requirement_files(tmp_path)
    )

    assert main_requirements.read_text(encoding="utf-8") == "requirements-main==1.0.0\n"
    assert sdk_requirements.read_text(encoding="utf-8") == "requirements-sdk==1.0.0\n"
    assert (
        integrations_requirements.read_text(encoding="utf-8")
        == "requirements-integrations==1.0.0\n"
    )


def test_collect_safety_metric_scans_all_runtime_requirement_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    main_requirements = tmp_path / "requirements-main.txt"
    sdk_requirements = tmp_path / "requirements-sdk.txt"
    integrations_requirements = tmp_path / "requirements-integrations.txt"
    calls: list[list[str]] = []

    def fake_run_command(command: list[str], timeout: int):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="[]", stderr="")

    monkeypatch.setattr(quality_report, "resolve_command", lambda program: program)
    monkeypatch.setattr(quality_report, "run_command", fake_run_command)

    metric = quality_report.collect_safety_metric(
        main_requirements,
        sdk_requirements,
        integrations_requirements,
    )

    assert metric.status == "PASS"
    assert calls == [
        [
            "safety",
            "check",
            "--json",
            "-r",
            str(main_requirements),
            "-r",
            str(sdk_requirements),
            "-r",
            str(integrations_requirements),
        ]
    ]


def test_collect_pip_audit_metric_scans_all_runtime_requirement_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    main_requirements = tmp_path / "requirements-main.txt"
    sdk_requirements = tmp_path / "requirements-sdk.txt"
    integrations_requirements = tmp_path / "requirements-integrations.txt"
    calls: list[list[str]] = []

    def fake_run_command(command: list[str], timeout: int):
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='{"dependencies": []}',
            stderr="",
        )

    monkeypatch.setattr(quality_report, "resolve_command", lambda program: program)
    monkeypatch.setattr(quality_report, "run_command", fake_run_command)

    metric = quality_report.collect_pip_audit_metric(
        main_requirements,
        sdk_requirements,
        integrations_requirements,
    )

    assert metric.status == "PASS"
    assert calls == [
        [
            "pip-audit",
            "-r",
            str(main_requirements),
            "-r",
            str(sdk_requirements),
            "-r",
            str(integrations_requirements),
            "--progress-spinner",
            "off",
            "--format",
            "json",
        ]
    ]


def test_collect_trivy_metric_skips_docker_when_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(quality_report, "resolve_command", lambda program: program)
    monkeypatch.setattr(
        quality_report,
        "run_command",
        lambda command, timeout: pytest.fail(f"unexpected command: {command!r}"),
    )

    metric = quality_report.collect_trivy_metric(skip_docker=True)

    assert metric.name == "Trivy"
    assert metric.status == "SKIP"
    assert "Docker image scan skipped" in metric.detail


def test_collect_security_metrics_can_skip_dependency_scans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        quality_report,
        "build_requirement_files",
        lambda temp_path: pytest.fail("dependency requirements should not be built"),
    )
    monkeypatch.setattr(
        quality_report,
        "collect_bandit_metric",
        lambda: quality_report.SecurityMetric("Bandit", "PASS", "ok"),
    )
    monkeypatch.setattr(
        quality_report,
        "collect_trivy_metric",
        lambda skip_docker=False: quality_report.SecurityMetric("Trivy", "SKIP", "ok"),
    )

    metrics = quality_report.collect_security_metrics(skip_dependency_scans=True)

    assert [(metric.name, metric.status) for metric in metrics] == [
        ("Bandit", "PASS"),
        ("Safety", "SKIP"),
        ("pip-audit", "SKIP"),
        ("Trivy", "SKIP"),
    ]


def test_collect_pip_audit_metric_reports_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("fastapi==0.1.0\n", encoding="utf-8")

    def raise_timeout(command: list[str], timeout: int):
        raise subprocess.TimeoutExpired(command, timeout)

    monkeypatch.setattr(quality_report, "resolve_command", lambda program: program)
    monkeypatch.setattr(quality_report, "run_command", raise_timeout)

    metric = quality_report.collect_pip_audit_metric(
        requirements,
        requirements,
        requirements,
    )

    assert metric.name == "pip-audit"
    assert metric.status == "WARN"
    assert "timed out" in metric.detail
