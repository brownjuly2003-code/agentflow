"""Production refuses Ingress annotations that can re-route `/metrics`.

The chart serialises arbitrary annotation strings safely, but ingress-nginx
interprets routing-control annotations after Helm has validated the literal
host and path.  Production therefore rejects the exact rewrite, regex, app
root, and snippet keys under both supported nginx annotation prefixes.

The check is intentionally narrow: unrelated annotations remain valid, the
development profile is unchanged, and disabling this chart's Ingress keeps
routing outside the chart's production contract.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.unit.test_helm_production_values_contract import (
    CHART_PATH,
    PRODUCTION_VALUES,
    PROJECT_ROOT,
    _output,
    _render,
)

_HELM = shutil.which("helm")
requires_helm = pytest.mark.skipif(
    _HELM is None, reason="helm CLI is required for Helm render policy tests"
)

_ANNOTATION_PREFIXES = (
    "nginx.ingress.kubernetes.io/",
    "ingress.kubernetes.io/",
)

_ROUTING_CONTROL_VALUES = {
    "rewrite-target": "/metrics",
    "use-regex": "false",
    "app-root": "",
    "configuration-snippet": "return 404;",
    "server-snippet": "return 404;",
}
_ROUTING_CONTROL_NAMES = tuple(_ROUTING_CONTROL_VALUES)

_DENIED_ANNOTATIONS = [
    (f"{prefix}{name}", value)
    for prefix in _ANNOTATION_PREFIXES
    for name, value in _ROUTING_CONTROL_VALUES.items()
]

_BENIGN_ANNOTATIONS = (
    ("cert-manager.io/cluster-issuer", "letsencrypt-production"),
    ("nginx.ingress.kubernetes.io/ssl-redirect", "true"),
    ("nginx.ingress.kubernetes.io/proxy-body-size", "8m"),
)

_ANNOTATION_CONTRACT = "production refuses ingress-nginx routing-control annotations"


def _ingress(output: str) -> dict:
    for document in yaml.safe_load_all(output):
        if isinstance(document, dict) and document.get("kind") == "Ingress":
            return document
    raise AssertionError(f"rendered output has no Ingress:\n{output}")


@requires_helm
def test_control_unmodified_production_ingress_renders(tmp_path: Path) -> None:
    """The existing valid production reference must remain accepted."""
    result = _render(tmp_path)
    output = _output(result)

    assert result.returncode == 0, output
    assert _ingress(output)["metadata"].get("annotations") is None


@requires_helm
@pytest.mark.parametrize(("annotation", "value"), _DENIED_ANNOTATIONS)
def test_production_refuses_routing_control_annotation(
    tmp_path: Path, annotation: str, value: str
) -> None:
    result = _render(
        tmp_path,
        {"ingress": {"annotations": {annotation: value}}},
    )
    output = _output(result)

    assert result.returncode != 0
    assert annotation in output
    assert _ANNOTATION_CONTRACT in output


@requires_helm
@pytest.mark.parametrize(("annotation", "value"), _BENIGN_ANNOTATIONS)
def test_production_accepts_unrelated_ingress_annotation(
    tmp_path: Path, annotation: str, value: str
) -> None:
    result = _render(
        tmp_path,
        {"ingress": {"annotations": {annotation: value}}},
    )
    output = _output(result)

    assert result.returncode == 0, output
    assert _ingress(output)["metadata"]["annotations"][annotation] == value


@requires_helm
def test_dev_profile_accepts_routing_control_annotation(tmp_path: Path) -> None:
    """The denylist belongs only to the production values contract."""
    helm = shutil.which("helm")
    assert helm is not None
    values = tmp_path / "values-dev.yaml"
    annotation = "nginx.ingress.kubernetes.io/rewrite-target"
    values.write_text(
        yaml.safe_dump(
            {
                "ingress": {
                    "enabled": True,
                    "annotations": {annotation: "/metrics"},
                }
            }
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [helm, "template", "agentflow", str(CHART_PATH), "--values", str(values)],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    output = _output(result)

    assert result.returncode == 0, output
    assert _ingress(output)["metadata"]["annotations"][annotation] == "/metrics"


@requires_helm
def test_production_ingress_disabled_ignores_routing_control_annotation(
    tmp_path: Path,
) -> None:
    """An external gateway keeps routing outside this chart's Ingress check."""
    result = _render(
        tmp_path,
        {
            "ingress": {
                "enabled": False,
                "annotations": {"nginx.ingress.kubernetes.io/rewrite-target": "/metrics"},
            }
        },
    )
    output = _output(result)

    assert result.returncode == 0, output
    assert "kind: Ingress" not in output


@pytest.mark.parametrize(
    "path",
    [
        PRODUCTION_VALUES,
        PROJECT_ROOT / "docs" / "operations" / "helm-deployment.md",
        PROJECT_ROOT / "CHANGELOG.md",
        PROJECT_ROOT / "docs" / "security-audit.md",
    ],
)
def test_operator_docs_name_annotation_denylist_and_boundary(path: Path) -> None:
    text = path.read_text(encoding="utf-8")

    for prefix in _ANNOTATION_PREFIXES:
        assert prefix in text
    for name in _ROUTING_CONTROL_NAMES:
        assert name in text
    assert "controller ConfigMap" in text
    assert "separately managed Ingress" in text
