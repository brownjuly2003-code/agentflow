"""Helm schedule for API-owned query-analytics retention (T-27)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.unit.test_helm_production_values_contract import (
    CHART_PATH,
    PRODUCTION_VALUES,
    PROJECT_ROOT,
    _load_yaml,
    _output,
    _render,
)

_HELM = shutil.which("helm")
requires_helm = pytest.mark.skipif(
    _HELM is None, reason="helm CLI is required for Helm render policy tests"
)

_COMPONENT = "app.kubernetes.io/component"
_RETENTION_COMPONENT = "analytics-retention"
_API_COMPONENT = "api"
_MODULE = "agentflow_runtime.serving.api.analytics_retention_client"
_ENDPOINT = "/v1/admin/analytics/retention"


def _render_dev(tmp_path: Path, overrides: dict | None = None) -> subprocess.CompletedProcess[str]:
    helm = shutil.which("helm")
    if helm is None:
        raise AssertionError("helm is required for Helm render policy tests")
    command = [helm, "template", "agentflow", str(CHART_PATH)]
    if overrides is not None:
        values_path = tmp_path / "values-retention.yaml"
        values_path.write_text(yaml.safe_dump(overrides), encoding="utf-8")
        command.extend(["--values", str(values_path)])
    return subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _documents(output: str) -> list[dict]:
    return [doc for doc in yaml.safe_load_all(output) if isinstance(doc, dict)]


def _one_document(output: str, kind: str, component: str | None = None) -> dict:
    matches = []
    for document in _documents(output):
        if document.get("kind") != kind:
            continue
        labels = document.get("metadata", {}).get("labels", {})
        if component is None or labels.get(_COMPONENT) == component:
            matches.append(document)
    assert len(matches) == 1, (kind, component, matches)
    return matches[0]


@requires_helm
def test_default_values_render_no_retention_cronjob(tmp_path: Path) -> None:
    result = _render_dev(tmp_path)
    output = _output(result)

    assert result.returncode == 0, output
    assert not [
        document
        for document in _documents(output)
        if document.get("kind") == "CronJob"
        and document.get("metadata", {}).get("labels", {}).get(_COMPONENT) == _RETENTION_COMPONENT
    ]


@requires_helm
def test_enabled_retention_renders_a_hardened_api_client_cronjob(tmp_path: Path) -> None:
    resources = {"requests": {"cpu": "25m", "memory": "64Mi"}}
    result = _render_dev(
        tmp_path,
        {
            "analyticsRetention": {
                "enabled": True,
                "schedule": "5 4 * * *",
                "retentionDays": 14,
                "dryRun": True,
                "concurrencyPolicy": "Forbid",
                "startingDeadlineSeconds": 900,
                "successfulJobsHistoryLimit": 2,
                "failedJobsHistoryLimit": 4,
                "backoffLimit": 2,
                "resources": resources,
            }
        },
    )
    output = _output(result)

    assert result.returncode == 0, output
    cronjob = _one_document(output, "CronJob", _RETENTION_COMPONENT)
    deployment = _one_document(output, "Deployment", _API_COMPONENT)
    assert cronjob["spec"]["schedule"] == "5 4 * * *"
    assert cronjob["spec"]["concurrencyPolicy"] == "Forbid"
    assert cronjob["spec"]["startingDeadlineSeconds"] == 900
    assert cronjob["spec"]["successfulJobsHistoryLimit"] == 2
    assert cronjob["spec"]["failedJobsHistoryLimit"] == 4

    job_spec = cronjob["spec"]["jobTemplate"]["spec"]
    pod_spec = job_spec["template"]["spec"]
    container = pod_spec["containers"][0]
    assert job_spec["backoffLimit"] == 2
    assert pod_spec["restartPolicy"] == "Never"
    assert pod_spec["serviceAccountName"] == "agentflow-worker"
    assert pod_spec["automountServiceAccountToken"] is False
    assert pod_spec["securityContext"]
    assert container["securityContext"]
    assert container["image"] == deployment["spec"]["template"]["spec"]["containers"][0]["image"]
    assert container["resources"] == resources
    assert container["command"] == [
        "python",
        "-m",
        _MODULE,
        "--url",
        f"http://agentflow:8000{_ENDPOINT}",
        "--retention-days",
        "14",
        "--dry-run",
    ]
    assert "volumes" not in pod_spec
    assert "volumeMounts" not in container
    assert "scripts/prune_query_analytics.py" not in output
    assert "--erase-tenant" not in output
    assert container["env"] == [
        {
            "name": "AGENTFLOW_ADMIN_KEY",
            "valueFrom": {"secretKeyRef": {"name": "agentflow", "key": "admin-key"}},
        }
    ]


@requires_helm
def test_retention_cli_flags_are_omitted_until_configured(tmp_path: Path) -> None:
    result = _render_dev(tmp_path, {"analyticsRetention": {"enabled": True}})
    output = _output(result)

    assert result.returncode == 0, output
    command = _one_document(output, "CronJob", _RETENTION_COMPONENT)["spec"]["jobTemplate"]["spec"][
        "template"
    ]["spec"]["containers"][0]["command"]
    assert "--retention-days" not in command
    assert "--dry-run" not in command


@requires_helm
def test_service_always_selects_only_api_pods(tmp_path: Path) -> None:
    result = _render_dev(tmp_path)
    output = _output(result)

    assert result.returncode == 0, output
    service = _one_document(output, "Service")
    assert service["spec"]["selector"][_COMPONENT] == _API_COMPONENT


@requires_helm
def test_network_policy_admits_only_retention_to_api_on_the_service_port(
    tmp_path: Path,
) -> None:
    result = _render_dev(
        tmp_path,
        {
            "analyticsRetention": {"enabled": True},
            "networkPolicy": {"enabled": True},
        },
    )
    output = _output(result)

    assert result.returncode == 0, output
    policies = [doc for doc in _documents(output) if doc.get("kind") == "NetworkPolicy"]
    base_policy = next(policy for policy in policies if policy["metadata"]["name"] == "agentflow")
    retention_egress = next(
        policy
        for policy in policies
        if policy["spec"]["podSelector"]["matchLabels"].get(_COMPONENT) == _RETENTION_COMPONENT
    )
    api_ingress = next(
        policy
        for policy in policies
        if policy["spec"]["podSelector"]["matchLabels"].get(_COMPONENT) == _API_COMPONENT
    )

    assert base_policy["spec"]["podSelector"]["matchExpressions"] == [
        {
            "key": _COMPONENT,
            "operator": "NotIn",
            "values": [_RETENTION_COMPONENT],
        }
    ]
    assert retention_egress["spec"]["policyTypes"] == ["Ingress", "Egress"]
    assert retention_egress["spec"]["ingress"] == []
    assert retention_egress["spec"]["egress"] == [
        {
            "to": [
                {
                    "namespaceSelector": {},
                    "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}},
                }
            ],
            "ports": [
                {"protocol": "UDP", "port": 53},
                {"protocol": "TCP", "port": 53},
            ],
        },
        {
            "to": [
                {
                    "podSelector": {
                        "matchLabels": {
                            "app.kubernetes.io/name": "agentflow",
                            "app.kubernetes.io/instance": "agentflow",
                            _COMPONENT: _API_COMPONENT,
                        }
                    }
                }
            ],
            "ports": [{"protocol": "TCP", "port": 8000}],
        },
    ]
    assert api_ingress["spec"]["policyTypes"] == ["Ingress"]
    assert api_ingress["spec"]["ingress"] == [
        {
            "from": [
                {
                    "podSelector": {
                        "matchLabels": {
                            "app.kubernetes.io/name": "agentflow",
                            "app.kubernetes.io/instance": "agentflow",
                            _COMPONENT: _RETENTION_COMPONENT,
                        }
                    }
                }
            ],
            "ports": [{"protocol": "TCP", "port": 8000}],
        }
    ]


@requires_helm
def test_production_refuses_disabled_or_nonfinal_retention(tmp_path: Path) -> None:
    for override, expected in (
        (
            {"enabled": False},
            "analyticsRetention.enabled=false",
        ),
        (
            {"dryRun": True},
            "analyticsRetention.dryRun=true",
        ),
        (
            {"concurrencyPolicy": "Allow"},
            "analyticsRetention.concurrencyPolicy=Allow",
        ),
    ):
        result = _render(tmp_path, {"analyticsRetention": override})
        output = _output(result)
        assert result.returncode != 0
        assert expected in output


def test_production_overlay_enables_final_forbid_retention() -> None:
    values = _load_yaml(PRODUCTION_VALUES)

    assert values["analyticsRetention"]["enabled"] is True
    assert values["analyticsRetention"]["dryRun"] is False
    assert values["analyticsRetention"]["concurrencyPolicy"] == "Forbid"


def test_values_schema_closes_and_types_the_retention_block() -> None:
    schema = json.loads((CHART_PATH / "values.schema.json").read_text(encoding="utf-8"))
    retention = schema["properties"]["analyticsRetention"]

    assert "analyticsRetention" in schema["required"]
    assert retention["type"] == "object"
    assert retention["additionalProperties"] is False
    assert set(retention["required"]) == {
        "enabled",
        "schedule",
        "retentionDays",
        "dryRun",
        "concurrencyPolicy",
        "startingDeadlineSeconds",
        "successfulJobsHistoryLimit",
        "failedJobsHistoryLimit",
        "backoffLimit",
        "resources",
    }
    assert retention["properties"]["retentionDays"]["oneOf"] == [
        {"type": "integer", "minimum": 1},
        {"type": "string", "maxLength": 0},
    ]
    assert retention["properties"]["concurrencyPolicy"]["enum"] == [
        "Allow",
        "Forbid",
        "Replace",
    ]
