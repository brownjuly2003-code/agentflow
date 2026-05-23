"""Kafka Testcontainers fixtures for integration tests."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
KIND_CLUSTER_NAME = "agentflow-a05-test"


@pytest.fixture(autouse=True)
def _default_open_auth(request, monkeypatch):
    """Integration tests historically ran without an api_keys.yaml and relied
    on middleware to passthrough when keys were unconfigured. After the
    fail-closed default (Codex audit p2_1 #5 / p2_2 #1), every TestClient
    that does not explicitly configure keys now returns 503. To keep the
    legacy behaviour for tests that do not exercise auth, set
    ``AGENTFLOW_AUTH_DISABLED=true`` here. Tests that intentionally probe
    fail-closed (``test_tenant_isolation``, ``test_cors`` and a few unit
    tests) opt out via ``@pytest.mark.requires_auth_enforcement`` or
    ``monkeypatch.delenv`` on their own fixture.
    """
    if request.node.get_closest_marker("requires_auth_enforcement"):
        return
    monkeypatch.setenv("AGENTFLOW_AUTH_DISABLED", "true")


def pytest_configure(config):
    config.addinivalue_line("markers", "kind: marks tests requiring a kind cluster")
    config.addinivalue_line(
        "markers",
        "requires_auth_enforcement: opt out of the autouse AGENTFLOW_AUTH_DISABLED override",
    )


def pytest_collection_modifyitems(config, items):
    if not config.option.markexpr:
        skip_kind = pytest.mark.skip(reason="kind tests require explicit marker selection")
        for item in items:
            if "kind" in item.keywords:
                item.add_marker(skip_kind)

    if os.getenv("SKIP_DOCKER_TESTS") != "1":
        return

    skip_marker = pytest.mark.skip(reason="SKIP_DOCKER_TESTS=1")
    for item in items:
        if "requires_docker" in item.keywords:
            item.add_marker(skip_marker)


@pytest.fixture(scope="session")
def kafka_container():
    if os.getenv("SKIP_DOCKER_TESTS") == "1":
        pytest.skip("SKIP_DOCKER_TESTS=1")

    docker = pytest.importorskip("docker", reason="docker SDK is required for Testcontainers")
    docker_errors = pytest.importorskip(
        "docker.errors",
        reason="docker SDK is required for Testcontainers",
    )
    kafka_module = pytest.importorskip(
        "testcontainers.kafka",
        reason="testcontainers[kafka] is required for Kafka integration tests",
    )

    client = docker.from_env()
    try:
        client.ping()
    except (docker_errors.DockerException, OSError) as exc:
        pytest.skip(f"Docker is unavailable: {exc}")
    finally:
        client.close()

    kafka = kafka_module.KafkaContainer("confluentinc/cp-kafka:7.7.0").start()
    try:
        yield kafka
    finally:
        try:
            kafka.stop()
        except docker_errors.NotFound:
            pass


@pytest.fixture
def kafka_bootstrap(kafka_container):
    return kafka_container.get_bootstrap_server()


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


@pytest.fixture(scope="session")
def kind_cluster():
    """Provide a Kubernetes cluster context for helm live-validation tests.

    Default behaviour (CI + local kind): create a throwaway kind cluster
    named ``agentflow-a05-test`` and tear it down on teardown.

    Reuse mode (external staging / shared cluster): set
    ``AGENTFLOW_LIVE_REUSE_CLUSTER=1`` to skip the kind create/delete cycle
    and run validation against the active kubectl context. Useful for
    pointing the helm-schema tests at a real staging cluster via
    ``KUBECONFIG=/path/to/staging.kubeconfig`` without provisioning kind.

    The reuse path still requires the ``helm`` CLI but skips the kind/docker
    preflight, so tests can run on managed control planes (EKS, GKE, AKS)
    that do not expose a local docker socket. ``AGENTFLOW_KIND_CLUSTER``
    selects an alternate cluster name when not in reuse mode.
    """
    if os.getenv("SKIP_DOCKER_TESTS") == "1":
        pytest.skip("SKIP_DOCKER_TESTS=1")
    if shutil.which("helm") is None:
        pytest.skip("helm CLI is required for kind tests")

    reuse = _truthy(os.getenv("AGENTFLOW_LIVE_REUSE_CLUSTER"))
    if reuse:
        kubeconfig = os.getenv("KUBECONFIG", "<default>")
        # The reuse path delegates cluster ownership to the caller; helm
        # picks up the active kubectl context. We yield a synthetic
        # cluster_name string so parametrized tests can still log the
        # target context name if needed.
        yield f"reuse:{kubeconfig}"
        return

    if shutil.which("kind") is None:
        pytest.skip("kind CLI is required for kind tests")
    if shutil.which("docker") is None:
        pytest.skip("Docker CLI is required for kind tests")

    docker = subprocess.run(
        ["docker", "info"],
        text=True,
        capture_output=True,
        check=False,
    )
    if docker.returncode != 0:
        pytest.skip(f"Docker is unavailable: {docker.stderr or docker.stdout}")

    cluster_name = os.getenv("AGENTFLOW_KIND_CLUSTER", KIND_CLUSTER_NAME)
    kind_config = PROJECT_ROOT / "k8s" / "kind-config.yaml"

    subprocess.run(
        ["kind", "delete", "cluster", "--name", cluster_name],
        text=True,
        capture_output=True,
        check=False,
    )
    create = subprocess.run(
        ["kind", "create", "cluster", "--config", str(kind_config), "--name", cluster_name],
        text=True,
        capture_output=True,
        check=False,
    )
    if create.returncode != 0:
        pytest.fail(f"kind create cluster failed:\n{create.stdout}\n{create.stderr}")

    try:
        yield cluster_name
    finally:
        subprocess.run(
            ["kind", "delete", "cluster", "--name", cluster_name],
            text=True,
            capture_output=True,
            check=False,
        )
