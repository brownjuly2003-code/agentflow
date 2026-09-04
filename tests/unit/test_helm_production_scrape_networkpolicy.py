"""Production NetworkPolicy must admit the documented Prometheus scrape (F-T-32-4).

`/metrics` stays unauthenticated so in-cluster Prometheus can scrape the
ClusterIP Service. The NetworkPolicy is the actual allow-list: under the chart
default (`ingress-nginx` only) a Prometheus pod in a dedicated monitoring
namespace cannot reach the API port. The production overlay does not guess a
scrape namespace; the production contract refuses a render that is still
ingress-nginx-only — unless the operator sets
`networkPolicy.scrapeFromIngressNamespace=true`.

An empty `ingressFromNamespaces` list renders `ingress: []` (deny all) on every
profile. The production contract refuses that empty list because neither the
ingress controller nor Prometheus could reach the service port.

False-reject control: a valid production shape (scrape namespace enumerated, or
Prometheus co-located in the ingress-controller namespace with the named
exemption, or an entry selecting by a label other than
`kubernetes.io/metadata.name`) must still render. Those controls are written
against the existing `_render` helper and must stay green after the contract
tightens.
"""

from __future__ import annotations

import json
import re
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

_DEFAULT_INGRESS_NS = {"kubernetes.io/metadata.name": "ingress-nginx"}
_SCRAPE_AND_INGRESS_NS = [
    {"kubernetes.io/metadata.name": "ingress-nginx"},
    {"kubernetes.io/metadata.name": "monitoring"},
]
_COLOCATION_KEY = "scrapeFromIngressNamespace"
_HELM_DEPLOYMENT_DOC = PROJECT_ROOT / "docs" / "operations" / "helm-deployment.md"
_LIST_REPLACE_WARNING = (
    "Helm replaces lists instead of merging them — an environment file that "
    "names only the scrape namespace removes the ingress-controller entry and "
    "blocks the production Ingress."
)
_EMPTY_SELECTOR_CONTRACT_MESSAGE = (
    "networkPolicy.ingressFromNamespaces contains an empty selector {}: "
    "an empty namespaceSelector matches every namespace and publishes the "
    "service port (/metrics included) cluster-wide. Name the namespace label."
)


def _network_policy(output: str) -> dict:
    for doc in yaml.safe_load_all(output):
        if isinstance(doc, dict) and doc.get("kind") == "NetworkPolicy":
            return doc
    raise AssertionError(f"rendered output has no NetworkPolicy:\n{output}")


def _namespace_selector_names(policy: dict) -> list[str]:
    names: list[str] = []
    for rule in policy.get("spec", {}).get("ingress", []) or []:
        for source in rule.get("from", []) or []:
            labels = (source.get("namespaceSelector") or {}).get("matchLabels") or {}
            name = labels.get("kubernetes.io/metadata.name")
            if name:
                names.append(str(name))
    return names


@requires_helm
def test_control_compliant_production_render_still_accepted(tmp_path: Path) -> None:
    """Existing valid reference (production overlay + environment) must stay green."""
    result = _render(tmp_path)
    output = _output(result)

    assert result.returncode == 0, output
    assert "kind: NetworkPolicy" in output


@requires_helm
def test_control_scrape_namespace_enumerated_renders(tmp_path: Path) -> None:
    """Operator-supplied scrape namespace is a valid production shape."""
    result = _render(
        tmp_path,
        {"networkPolicy": {"ingressFromNamespaces": _SCRAPE_AND_INGRESS_NS}},
    )
    output = _output(result)

    assert result.returncode == 0, output
    names = _namespace_selector_names(_network_policy(output))
    assert "ingress-nginx" in names
    assert "monitoring" in names


@requires_helm
def test_control_prometheus_in_ingress_namespace_renders(tmp_path: Path) -> None:
    """Prometheus co-located with the ingress controller is valid when named."""
    result = _render(
        tmp_path,
        {
            "networkPolicy": {
                "ingressFromNamespaces": [_DEFAULT_INGRESS_NS],
                _COLOCATION_KEY: True,
            },
        },
    )
    output = _output(result)

    assert result.returncode == 0, output
    assert _namespace_selector_names(_network_policy(output)) == ["ingress-nginx"]


@requires_helm
def test_control_other_label_selector_without_namespace_name_renders(tmp_path: Path) -> None:
    """An entry that lacks kubernetes.io/metadata.name counts as other and passes."""
    result = _render(
        tmp_path,
        {
            "networkPolicy": {
                "ingressFromNamespaces": [
                    _DEFAULT_INGRESS_NS,
                    {"team": "observability"},
                ],
            },
        },
    )
    output = _output(result)

    assert result.returncode == 0, output
    names = _namespace_selector_names(_network_policy(output))
    assert "ingress-nginx" in names


@requires_helm
def test_production_render_refuses_chart_default_ingress_only_namespaces(
    tmp_path: Path,
) -> None:
    """The inherited chart default blocks scrape from a monitoring namespace."""
    result = _render(
        tmp_path,
        {"networkPolicy": {"ingressFromNamespaces": [_DEFAULT_INGRESS_NS]}},
    )
    output = _output(result)

    assert result.returncode != 0
    assert "ingressFromNamespaces" in output
    assert "ingress-nginx" in output
    assert "Prometheus" in output
    assert "networkPolicy.scrapeFromIngressNamespace=true" in output


@requires_helm
def test_unedited_production_overlay_refuses_ingress_only_namespaces(tmp_path: Path) -> None:
    """Unedited values-production.yaml forces a scrape-namespace decision."""
    helm = shutil.which("helm")
    assert helm is not None
    env = {
        key: dict(value) if isinstance(value, dict) else value
        for key, value in _ENVIRONMENT_VALUES.items()
        if key != "networkPolicy"
    }
    environment = tmp_path / "values-environment.yaml"
    environment.write_text(yaml.safe_dump(env), encoding="utf-8")
    result = subprocess.run(
        [
            helm,
            "template",
            "agentflow",
            str(CHART_PATH),
            "--values",
            str(PRODUCTION_VALUES),
            "--values",
            str(environment),
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    output = _output(result)

    assert result.returncode != 0
    assert "ingressFromNamespaces" in output
    assert "ingress-nginx" in output
    assert "networkPolicy.scrapeFromIngressNamespace=true" in output


@requires_helm
def test_production_render_refuses_ingress_nginx_with_extra_label(tmp_path: Path) -> None:
    result = _render(
        tmp_path,
        {
            "networkPolicy": {
                "ingressFromNamespaces": [
                    {"kubernetes.io/metadata.name": "ingress-nginx", "tier": "edge"},
                ],
            },
        },
    )
    output = _output(result)

    assert result.returncode != 0
    assert "ingressFromNamespaces" in output
    assert "ingress-nginx" in output


@requires_helm
def test_production_render_refuses_duplicate_ingress_nginx_selectors(tmp_path: Path) -> None:
    result = _render(
        tmp_path,
        {
            "networkPolicy": {
                "ingressFromNamespaces": [_DEFAULT_INGRESS_NS, _DEFAULT_INGRESS_NS],
            },
        },
    )
    output = _output(result)

    assert result.returncode != 0
    assert "ingressFromNamespaces" in output
    assert "ingress-nginx" in output


@requires_helm
def test_production_render_refuses_empty_ingress_from_namespaces(tmp_path: Path) -> None:
    result = _render(tmp_path, {"networkPolicy": {"ingressFromNamespaces": []}})
    output = _output(result)

    assert result.returncode != 0
    assert "ingressFromNamespaces" in output
    assert "ingress: []" in output
    assert "deny all" in output


@requires_helm
def test_scrape_from_ingress_namespace_does_not_admit_empty_list(
    tmp_path: Path,
) -> None:
    """Co-location opt-in does not open an empty allow-list.

    An empty list now renders `ingress: []` (deny all). The contract still
    refuses it because the scrape and the ingress controller could not reach
    the service port.
    """
    result = _render(
        tmp_path,
        {
            "networkPolicy": {
                "ingressFromNamespaces": [],
                _COLOCATION_KEY: True,
            },
        },
    )
    output = _output(result)

    assert result.returncode != 0
    assert "ingressFromNamespaces" in output
    assert "empty" in output
    assert "ingress: []" in output


@requires_helm
def test_empty_ingress_from_namespaces_renders_deny_all_on_dev(tmp_path: Path) -> None:
    """Dev/demo with enabled NetworkPolicy and an empty list must deny, not admit all."""
    helm = shutil.which("helm")
    assert helm is not None
    extra = tmp_path / "empty-from.yaml"
    extra.write_text(
        yaml.safe_dump({"networkPolicy": {"enabled": True, "ingressFromNamespaces": []}}),
        encoding="utf-8",
    )
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
    policy = _network_policy(output)
    assert policy["spec"]["ingress"] == []
    for rule in policy["spec"].get("ingress") or []:
        assert rule.get("from"), f"ingress rule without from admits every source: {rule}"


def test_values_schema_declares_scrape_from_ingress_namespace() -> None:
    schema = json.loads((CHART_PATH / "values.schema.json").read_text(encoding="utf-8"))
    network_policy = schema["properties"]["networkPolicy"]
    defaults = _load_yaml(CHART_PATH / "values.yaml")

    assert network_policy["additionalProperties"] is False
    assert network_policy["properties"][_COLOCATION_KEY] == {"type": "boolean"}
    assert defaults["networkPolicy"][_COLOCATION_KEY] is False


def test_production_overlay_ships_no_guessed_scrape_namespace() -> None:
    """Shipped production values must not invent a monitoring namespace."""
    overlay = _load_yaml(PRODUCTION_VALUES)
    defaults = _load_yaml(CHART_PATH / "values.yaml")
    from_ns = overlay["networkPolicy"]["ingressFromNamespaces"]
    names = [item.get("kubernetes.io/metadata.name") for item in from_ns if isinstance(item, dict)]

    assert (
        overlay["networkPolicy"]["ingressFromNamespaces"]
        == defaults["networkPolicy"]["ingressFromNamespaces"]
    )
    assert names == ["ingress-nginx"]
    assert overlay["networkPolicy"].get(_COLOCATION_KEY, False) is False
    text = PRODUCTION_VALUES.read_text(encoding="utf-8")
    assert "# - kubernetes.io/metadata.name: monitoring" in text
    assert f"networkPolicy.{_COLOCATION_KEY}: true" in text


def test_security_docs_agree_with_production_scrape_values() -> None:
    root = PRODUCTION_VALUES.parents[2]
    docs = (root / "docs" / "security-audit.md").read_text(encoding="utf-8")
    helm_docs = (root / "docs" / "operations" / "helm-deployment.md").read_text(encoding="utf-8")
    overlay_text = PRODUCTION_VALUES.read_text(encoding="utf-8")
    overlay = _load_yaml(PRODUCTION_VALUES)
    defaults = _load_yaml(CHART_PATH / "values.yaml")
    schema = json.loads((CHART_PATH / "values.schema.json").read_text(encoding="utf-8"))

    assert (
        overlay["networkPolicy"]["ingressFromNamespaces"]
        == defaults["networkPolicy"]["ingressFromNamespaces"]
    )
    assert schema["properties"]["networkPolicy"]["properties"][_COLOCATION_KEY] == {
        "type": "boolean"
    }
    assert defaults["networkPolicy"][_COLOCATION_KEY] is False
    assert _COLOCATION_KEY in docs
    assert _COLOCATION_KEY in helm_docs
    assert _COLOCATION_KEY in overlay_text


def _dev_render(tmp_path: Path, extra: dict) -> subprocess.CompletedProcess[str]:
    helm = shutil.which("helm")
    assert helm is not None
    extra_path = tmp_path / "extra.yaml"
    extra_path.write_text(yaml.safe_dump(extra), encoding="utf-8")
    return subprocess.run(
        [
            helm,
            "template",
            "agentflow",
            str(CHART_PATH),
            "--values",
            str(extra_path),
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _documented_ingress_from_namespaces_example() -> list:
    """The environment-values example in helm-deployment.md, parsed from the fence."""
    text = _HELM_DEPLOYMENT_DOC.read_text(encoding="utf-8")
    for fence in re.findall(r"```yaml\n(.*?)```", text, flags=re.DOTALL):
        loaded = yaml.safe_load(fence)
        if not isinstance(loaded, dict):
            continue
        from_ns = (loaded.get("networkPolicy") or {}).get("ingressFromNamespaces")
        if not isinstance(from_ns, list):
            continue
        names = [
            item.get("kubernetes.io/metadata.name") for item in from_ns if isinstance(item, dict)
        ]
        if "ingress-nginx" in names and any(name and name != "ingress-nginx" for name in names):
            return from_ns
    raise AssertionError(
        "docs/operations/helm-deployment.md has no yaml example that repeats "
        "the ingress-controller selector and a scrape namespace"
    )


def test_values_schema_requires_ingress_from_namespaces_items_are_label_maps() -> None:
    schema = json.loads((CHART_PATH / "values.schema.json").read_text(encoding="utf-8"))
    items = schema["properties"]["networkPolicy"]["properties"]["ingressFromNamespaces"]["items"]

    assert items["type"] == "object"
    assert items["additionalProperties"] == {"type": "string"}
    assert items["minProperties"] == 1


@requires_helm
def test_control_dev_render_accepts_label_map_ingress_from_namespaces_item(
    tmp_path: Path,
) -> None:
    """Shipped default shape (a string-to-string label map) must still render."""
    result = _dev_render(
        tmp_path,
        {
            "networkPolicy": {
                "enabled": True,
                "ingressFromNamespaces": [_DEFAULT_INGRESS_NS],
            }
        },
    )
    output = _output(result)

    assert result.returncode == 0, output
    assert _namespace_selector_names(_network_policy(output)) == ["ingress-nginx"]


@requires_helm
def test_dev_render_refuses_string_ingress_from_namespaces_item(tmp_path: Path) -> None:
    result = _dev_render(
        tmp_path,
        {
            "networkPolicy": {
                "enabled": True,
                "ingressFromNamespaces": ["monitoring"],
            }
        },
    )
    output = _output(result)

    assert result.returncode != 0
    assert "ingressFromNamespaces" in output


@requires_helm
def test_dev_render_refuses_null_ingress_from_namespaces_item(tmp_path: Path) -> None:
    result = _dev_render(
        tmp_path,
        {
            "networkPolicy": {
                "enabled": True,
                "ingressFromNamespaces": [None],
            }
        },
    )
    output = _output(result)

    assert result.returncode != 0
    assert "ingressFromNamespaces" in output


@requires_helm
def test_dev_render_refuses_empty_map_ingress_from_namespaces_item(tmp_path: Path) -> None:
    """An empty label map matches every namespace; schema must refuse it."""
    result = _dev_render(
        tmp_path,
        {
            "networkPolicy": {
                "enabled": True,
                "ingressFromNamespaces": [_DEFAULT_INGRESS_NS, {}],
            }
        },
    )
    output = _output(result)

    assert result.returncode != 0
    assert "ingressFromNamespaces" in output


def test_production_contract_source_refuses_empty_namespace_selector() -> None:
    contract = (CHART_PATH / "templates" / "production-contract.yaml").read_text(encoding="utf-8")
    assert _EMPTY_SELECTOR_CONTRACT_MESSAGE in contract


def test_helm_deployment_warns_that_helm_replaces_ingress_from_namespaces() -> None:
    text = _HELM_DEPLOYMENT_DOC.read_text(encoding="utf-8")
    collapsed = re.sub(r"\s+", " ", text)
    from_ns = _documented_ingress_from_namespaces_example()
    names = [item.get("kubernetes.io/metadata.name") for item in from_ns if isinstance(item, dict)]

    assert _LIST_REPLACE_WARNING in collapsed
    assert "ingress-nginx" in names
    assert any(name and name != "ingress-nginx" for name in names)


@requires_helm
def test_documented_environment_ingress_from_namespaces_keeps_ingress_and_scrape(
    tmp_path: Path,
) -> None:
    """The documented environment list must keep both selectors after Helm replace."""
    from_ns = _documented_ingress_from_namespaces_example()
    result = _render(tmp_path, {"networkPolicy": {"ingressFromNamespaces": from_ns}})
    output = _output(result)

    assert result.returncode == 0, output
    names = _namespace_selector_names(_network_policy(output))
    documented_names = [
        item.get("kubernetes.io/metadata.name")
        for item in from_ns
        if isinstance(item, dict) and item.get("kubernetes.io/metadata.name")
    ]
    assert "ingress-nginx" in documented_names
    assert any(name != "ingress-nginx" for name in documented_names)
    for name in documented_names:
        assert name in names
