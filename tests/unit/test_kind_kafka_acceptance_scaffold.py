"""Contract for the kind acceptance single-node Kafka/KRaft scaffold.

Acceptance/staging only — not a production Kafka topology. Pins the runtime
fixes proven on clean kind acceptance (service-link injection, controller
hairpin deadlock, probe windows, and required topic bootstrap).
"""

from __future__ import annotations

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = PROJECT_ROOT / "k8s" / "acceptance" / "kafka-kraft.yaml"

REQUIRED_TOPICS = ("orders.raw", "events.validated", "events.deadletter")
REQUIRED_IMAGE = "confluentinc/cp-kafka:7.7.0"
EXPECTED_HEAP_OPTS = "-Xms256m -Xmx512m"
CONTROLLER_VOTERS = "1@127.0.0.1:29093"
ACCEPTANCE_NAMESPACE = "agentflow"


def _load_documents() -> list[dict]:
    assert MANIFEST_PATH.is_file(), f"missing kind acceptance Kafka scaffold: {MANIFEST_PATH}"
    text = MANIFEST_PATH.read_text(encoding="utf-8")
    docs = [doc for doc in yaml.safe_load_all(text) if doc]
    assert docs, f"empty scaffold manifest: {MANIFEST_PATH}"
    return docs


def _by_kind(kind: str) -> list[dict]:
    return [doc for doc in _load_documents() if doc.get("kind") == kind]


def _env_map(container: dict) -> dict[str, str]:
    env = container.get("env") or []
    return {item["name"]: str(item["value"]) for item in env if "name" in item and "value" in item}


def _container_script(container: dict) -> str:
    parts: list[str] = []
    for key in ("command", "args"):
        value = container.get(key) or []
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
        else:
            parts.append(str(value))
    return "\n".join(parts)


def test_acceptance_kafka_scaffold_is_single_replica_acceptance_named() -> None:
    deployments = _by_kind("Deployment")
    assert len(deployments) == 1, "expected exactly one Kafka Deployment"
    dep = deployments[0]
    meta = dep["metadata"]
    labels = meta.get("labels") or {}

    assert meta["name"] == "kafka"
    assert meta["namespace"] == ACCEPTANCE_NAMESPACE
    assert labels.get("app") == "kafka"
    assert labels.get("agentflow.scaffold") == "kind-acceptance"
    assert dep["spec"]["replicas"] == 1


def test_acceptance_kafka_scaffold_uses_recreate_strategy() -> None:
    """Recreate avoids two pods sharing the same fixed KRaft node id."""
    dep = _by_kind("Deployment")[0]
    strategy = dep["spec"].get("strategy") or {}
    assert strategy.get("type") == "Recreate"


def test_acceptance_kafka_scaffold_disables_service_links() -> None:
    """Service-link injection sets KAFKA_PORT and breaks cp-kafka startup."""
    dep = _by_kind("Deployment")[0]
    pod_spec = dep["spec"]["template"]["spec"]
    assert pod_spec.get("enableServiceLinks") is False


def test_acceptance_kafka_scaffold_controller_voters_and_inter_broker() -> None:
    """Loopback voters avoid kind Service hairpin / no-Ready-endpoint deadlock."""
    dep = _by_kind("Deployment")[0]
    container = dep["spec"]["template"]["spec"]["containers"][0]
    env = _env_map(container)

    assert container["image"] == REQUIRED_IMAGE
    assert env["KAFKA_PROCESS_ROLES"] == "broker,controller"
    assert env["KAFKA_CONTROLLER_QUORUM_VOTERS"] == CONTROLLER_VOTERS
    assert env["KAFKA_INTER_BROKER_LISTENER_NAME"] == "PLAINTEXT"
    assert "kafka:29093" not in env["KAFKA_CONTROLLER_QUORUM_VOTERS"]


def test_acceptance_kafka_scaffold_caps_heap_for_colima() -> None:
    dep = _by_kind("Deployment")[0]
    container = dep["spec"]["template"]["spec"]["containers"][0]
    env = _env_map(container)

    assert env["KAFKA_HEAP_OPTS"] == EXPECTED_HEAP_OPTS


def test_acceptance_kafka_scaffold_service_exposes_broker_and_controller_ports() -> None:
    services = _by_kind("Service")
    assert len(services) == 1, "expected exactly one Kafka Service"
    svc = services[0]
    assert svc["metadata"]["name"] == "kafka"
    assert svc["metadata"]["namespace"] == ACCEPTANCE_NAMESPACE
    ports = {port["name"]: port["port"] for port in svc["spec"]["ports"]}
    assert ports["plaintext"] == 9092
    assert ports["controller"] == 29093


def test_acceptance_kafka_scaffold_probe_windows_match_proven_live_stand() -> None:
    dep = _by_kind("Deployment")[0]
    container = dep["spec"]["template"]["spec"]["containers"][0]
    readiness = container["readinessProbe"]
    liveness = container["livenessProbe"]

    assert readiness["initialDelaySeconds"] == 30
    assert readiness["periodSeconds"] == 5
    assert readiness["timeoutSeconds"] == 5
    assert readiness["failureThreshold"] == 24

    assert liveness["initialDelaySeconds"] == 90
    assert liveness["periodSeconds"] == 10
    assert liveness["timeoutSeconds"] == 5
    assert liveness["failureThreshold"] == 6


def test_acceptance_kafka_scaffold_bootstraps_required_topics() -> None:
    jobs = _by_kind("Job")
    assert len(jobs) == 1, "expected a topic-bootstrap Job"
    job = jobs[0]
    assert job["metadata"]["namespace"] == ACCEPTANCE_NAMESPACE
    assert "topic" in job["metadata"]["name"]

    container = job["spec"]["template"]["spec"]["containers"][0]
    script = _container_script(container)
    assert container["image"] == REQUIRED_IMAGE
    assert "--if-not-exists" in script
    assert "--partitions 1" in script
    assert "--replication-factor 1" in script
    for topic in REQUIRED_TOPICS:
        assert f"--topic {topic}" in script
