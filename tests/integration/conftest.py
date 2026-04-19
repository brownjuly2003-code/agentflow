"""Kafka Testcontainers fixtures for integration tests."""

import os

import pytest


def pytest_collection_modifyitems(items):
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

    with kafka_module.KafkaContainer("confluentinc/cp-kafka:7.7.0") as kafka:
        yield kafka


@pytest.fixture
def kafka_bootstrap(kafka_container):
    return kafka_container.get_bootstrap_server()
