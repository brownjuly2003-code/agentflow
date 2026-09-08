"""Every egress rule this chart renders has to say where it may go (FB-09).

A Kubernetes egress rule with `ports:` and no `to:` allows those ports to
**every** address — other namespaces, the node network, the internet. The
chart's NetworkPolicy had exactly one rule with a selector (DNS); Redis, Kafka,
Iceberg, the object store, ClickHouse, OTLP and PostgreSQL were bare `ports:`
lists. So the "default-deny baseline" denied nothing on
6379/9092/8181/9000/8123/4317/5432, and a compromised pod could dial any of
them anywhere.

Two things changed and both are pinned here. Rules now carry
`networkPolicy.egressTo.<service>` destinations, and the production contract
refuses an empty list for every rule that renders. And the rules are gated on
the feature being configured: opening the ClickHouse port on a DuckDB install
was never permissiveness, it described a topology that does not exist.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.unit.test_helm_production_values_contract import (
    CHART_PATH,
    PROJECT_ROOT,
    _egress_to,
    _output,
    _render,
)

requires_helm = pytest.mark.skipif(
    shutil.which("helm") is None, reason="helm CLI is required for Helm render policy tests"
)

# The port each destination list guards, from values.yaml `egressPorts`.
_PORTS = {
    "redis": 6379,
    "kafka": 9092,
    "clickhouse": 8123,
    "otlp": 4317,
    "postgres": 5432,
    "icebergCatalog": 8181,
    "objectStore": 9000,
}

# What has to be switched on for each rule to render at all.
_FEATURE_VALUES: dict[str, dict] = {
    "redis": {"config": {"redisUrl": "rediss://redis.data.svc:6380/0"}},
    "clickhouse": {
        "serving": {
            "backend": "clickhouse",
            "clickhouse": {"host": "clickhouse.data.svc", "secure": True},
        }
    },
    "otlp": {"config": {"otlpEndpoint": "http://otel.observability.svc:4317"}},
    "postgres": {
        "controlPlane": {"store": "postgres", "postgres": {"existingSecret": "agentflow-pg"}}
    },
}

_PEER = [{"ipBlock": {"cidr": "10.30.9.0/24"}}]


def _primary_policy(output: str) -> dict:
    """The pod policy for the API/worker set, not the analytics-retention pair."""
    for doc in yaml.safe_load_all(output):
        if not doc or doc.get("kind") != "NetworkPolicy":
            continue
        if not doc["metadata"]["name"].endswith(("-egress", "-api-ingress")):
            return doc
    raise AssertionError(f"rendered output has no primary NetworkPolicy:\n{output}")


def _egress_ports(policy: dict) -> set[int]:
    return {
        entry["port"]
        for rule in policy["spec"]["egress"]
        for entry in rule.get("ports") or []
        if entry["protocol"] == "TCP"
    }


@requires_helm
def test_the_baseline_opens_no_port_for_a_service_the_install_does_not_run() -> None:
    """Chart defaults are DuckDB, no Redis URL, no OTLP endpoint, the embedded
    control plane and no lake materializer. Before, the policy still opened
    6379/8123/4317 to every address; the only rule those ports served was one
    nothing in the release could use."""
    helm = shutil.which("helm")
    assert helm is not None
    result = subprocess.run(
        [helm, "template", "agentflow", str(CHART_PATH), "--set", "networkPolicy.enabled=true"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, _output(result)

    ports = _egress_ports(_primary_policy(result.stdout))

    assert ports == {53, _PORTS["kafka"]}, (
        "the dev baseline should open DNS and Kafka only; every other port belongs "
        "to a service these values do not configure"
    )


@requires_helm
def test_every_rule_that_is_not_dns_names_its_destinations(tmp_path: Path) -> None:
    """The property the contract exists to produce. DNS is the exception it has
    always been -- kube-dns is selected by label, in whichever namespace."""
    result = _render(tmp_path)
    output = _output(result)
    assert result.returncode == 0, output

    for rule in _primary_policy(result.stdout)["spec"]["egress"]:
        assert rule.get("to"), f"egress rule reaches every address: {rule}"


@requires_helm
@pytest.mark.parametrize("service", sorted(_FEATURE_VALUES))
def test_production_refuses_a_rule_that_names_no_destination(tmp_path: Path, service: str) -> None:
    """Switching a store on adds a rule. Leaving its peers empty is not a
    narrower policy than naming them -- it is the widest one available."""
    result = _render(tmp_path, {**_FEATURE_VALUES[service], "networkPolicy": {}})
    output = _output(result)

    assert result.returncode != 0
    assert f"networkPolicy.egressTo.{service} is empty" in output
    assert str(_PORTS[service]) in output


@requires_helm
def test_production_refuses_the_kafka_rule_with_no_destination(tmp_path: Path) -> None:
    """Kafka renders unconditionally -- the API produces and the materializer
    and bridge consume -- so it is the one rule no feature switch can retire."""
    result = _render(tmp_path, {"networkPolicy": {"egressTo": _egress_to(kafka=[])}})
    output = _output(result)

    assert result.returncode != 0
    assert "networkPolicy.egressTo.kafka is empty" in output


@requires_helm
def test_a_feature_that_is_off_is_never_asked_for_destinations(tmp_path: Path) -> None:
    """The contract mirrors the render conditions rather than demanding all
    seven lists. An operator on DuckDB with an embedded control plane owes
    peers for Kafka and nothing else."""
    result = _render(tmp_path)
    output = _output(result)

    assert result.returncode == 0, output
    for service in ("clickhouse", "postgres", "redis", "otlp"):
        assert f"networkPolicy.egressTo.{service}" not in output


@requires_helm
@pytest.mark.parametrize("service", sorted(_FEATURE_VALUES))
def test_named_destinations_reach_the_rendered_policy(tmp_path: Path, service: str) -> None:
    """A clause that only checks values would pass while the template dropped
    them on the floor."""
    result = _render(
        tmp_path,
        {
            **_FEATURE_VALUES[service],
            "networkPolicy": {"egressTo": _egress_to(**{service: _PEER})},
        },
    )
    output = _output(result)
    assert result.returncode == 0, output

    rule = next(
        item
        for item in _primary_policy(result.stdout)["spec"]["egress"]
        if any(entry["port"] == _PORTS[service] for entry in item.get("ports") or [])
    )

    assert rule["to"] == _PEER


@requires_helm
def test_the_analytics_retention_policies_still_name_their_peers(tmp_path: Path) -> None:
    """These two were already selector-based. They are the shape the rest of
    the egress rules just moved to, so a regression here would be a quiet one."""
    result = _render(tmp_path)
    output = _output(result)
    assert result.returncode == 0, output

    policies = [
        doc
        for doc in yaml.safe_load_all(result.stdout)
        if doc
        and doc.get("kind") == "NetworkPolicy"
        and doc["metadata"]["name"].endswith(("-egress", "-api-ingress"))
    ]
    assert len(policies) == 2

    for policy in policies:
        for rule in policy["spec"].get("egress") or []:
            assert rule.get("to"), f"{policy['metadata']['name']} reaches every address: {rule}"
