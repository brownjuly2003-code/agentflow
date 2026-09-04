"""Production must keep the API on a ClusterIP Service (F-T-32-22).

`/metrics` is unauthenticated so in-cluster Prometheus can scrape the ClusterIP
Service. NodePort and LoadBalancer publish that same service port without any
Ingress rule; ExternalName turns the Service into a CNAME and voids the routing
contract. The production contract therefore refuses `service.type` other than
`ClusterIP`. The clause is production-only: a dev render may still set
LoadBalancer.

`ingress.enabled=false` remains the sanctioned external-gateway shape. It does
not relax `service.type`; it only skips the Ingress TLS/host/path clauses and
moves routing (and the `/metrics` exposure question) outside the chart.

False-reject control: the existing valid production overlay + environment
reference must still render, and production + `ingress.enabled=false` +
ClusterIP must still render.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.unit.test_helm_production_values_contract import (
    _ENVIRONMENT_VALUES,
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

_SERVICE_TYPE_CONTRACT = (
    "production must keep the API on a ClusterIP Service — "
    "NodePort/LoadBalancer publish the service port (/metrics included) "
    "without any Ingress rule, ExternalName turns the Service into a CNAME "
    "and voids the routing contract"
)

_PUBLISHING_TYPES = ("LoadBalancer", "NodePort", "ExternalName")


def _service_type_problem(value: str) -> str:
    return f"service.type={value}: {_SERVICE_TYPE_CONTRACT}"


def _service(output: str) -> dict:
    for doc in yaml.safe_load_all(output):
        if isinstance(doc, dict) and doc.get("kind") == "Service":
            return doc
    raise AssertionError(f"rendered output has no Service:\n{output}")


def _render_set(
    tmp_path: Path,
    *set_pairs: str,
    overrides: dict | None = None,
) -> subprocess.CompletedProcess[str]:
    """Production overlay + environment values, plus helm `--set` pairs."""
    helm = shutil.which("helm")
    if helm is None:
        raise AssertionError("helm is required for Helm render policy tests")

    values: dict = {key: dict(value) for key, value in _ENVIRONMENT_VALUES.items()}
    for section, patch in (overrides or {}).items():
        if not isinstance(patch, dict):
            values[section] = patch
            continue
        merged = dict(values.get(section, {}))
        merged.update(patch)
        values[section] = merged

    environment = tmp_path / "values-environment.yaml"
    environment.write_text(yaml.safe_dump(values), encoding="utf-8")
    command = [
        helm,
        "template",
        "agentflow",
        str(CHART_PATH),
        "--values",
        str(PRODUCTION_VALUES),
        "--values",
        str(environment),
    ]
    for pair in set_pairs:
        command.extend(["--set", pair])
    return subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


@requires_helm
def test_control_unmodified_values_production_renders_green(tmp_path: Path) -> None:
    """Existing valid reference (production overlay + environment) must stay green."""
    result = _render(tmp_path)
    output = _output(result)

    assert result.returncode == 0, output
    assert _service(output)["spec"]["type"] == "ClusterIP"


@requires_helm
def test_control_production_ingress_disabled_with_clusterip_renders(tmp_path: Path) -> None:
    """Sanctioned external-gateway shape: ingress off, API still ClusterIP."""
    result = _render_set(
        tmp_path,
        "ingress.enabled=false",
        "service.type=ClusterIP",
    )
    output = _output(result)

    assert result.returncode == 0, output
    assert _service(output)["spec"]["type"] == "ClusterIP"
    assert "kind: Ingress" not in output


@requires_helm
@pytest.mark.parametrize("service_type", _PUBLISHING_TYPES)
def test_production_render_refuses_non_clusterip_service_type(
    tmp_path: Path, service_type: str
) -> None:
    result = _render_set(tmp_path, f"service.type={service_type}")
    output = _output(result)

    assert result.returncode != 0
    assert _service_type_problem(service_type) in output


@requires_helm
def test_production_explicit_clusterip_renders(tmp_path: Path) -> None:
    result = _render_set(tmp_path, "service.type=ClusterIP")
    output = _output(result)

    assert result.returncode == 0, output
    assert _service(output)["spec"]["type"] == "ClusterIP"


@requires_helm
def test_production_loadbalancer_still_refused_when_ingress_disabled(
    tmp_path: Path,
) -> None:
    """External gateway does not license publishing the Service port."""
    result = _render_set(
        tmp_path,
        "service.type=LoadBalancer",
        "ingress.enabled=false",
    )
    output = _output(result)

    assert result.returncode != 0
    assert _service_type_problem("LoadBalancer") in output


@requires_helm
def test_dev_profile_loadbalancer_renders(tmp_path: Path) -> None:
    """The service-type clause is production-only."""
    helm = shutil.which("helm")
    assert helm is not None
    extra = tmp_path / "dev-lb.yaml"
    extra.write_text(yaml.safe_dump({"service": {"type": "LoadBalancer"}}), encoding="utf-8")
    result = subprocess.run(
        [
            helm,
            "template",
            "agentflow",
            str(CHART_PATH),
            "--values",
            str(extra),
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    output = _output(result)

    assert result.returncode == 0, output
    assert _service(output)["spec"]["type"] == "LoadBalancer"


def test_production_overlay_pins_clusterip() -> None:
    overlay = _load_yaml(PRODUCTION_VALUES)
    text = PRODUCTION_VALUES.read_text(encoding="utf-8")

    assert overlay["service"]["type"] == "ClusterIP"
    assert "service.type" in text or "ClusterIP" in text
    assert "production-contract" in text or "contract" in text.lower()


def test_helm_deployment_doc_names_service_type_clause() -> None:
    helm_docs = (PROJECT_ROOT / "docs" / "operations" / "helm-deployment.md").read_text(
        encoding="utf-8"
    )

    assert "service.type" in helm_docs
    assert "ClusterIP" in helm_docs
    assert "ingress.enabled=false" in helm_docs
    assert "outside" in helm_docs
