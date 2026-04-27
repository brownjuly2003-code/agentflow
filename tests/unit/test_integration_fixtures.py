from types import SimpleNamespace

import pytest

from tests.integration import conftest as integration_conftest


def test_kafka_container_ignores_missing_container_on_teardown(monkeypatch):
    class FakeDockerError(Exception):
        pass

    class FakeNotFoundError(Exception):
        pass

    class FakeDockerClient:
        def ping(self):
            return True

        def close(self):
            return None

    class FakeKafkaContainer:
        def __init__(self, image):
            self.image = image

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            self.stop()

        def start(self):
            return self

        def stop(self):
            raise FakeNotFoundError("already removed")

    fake_docker = SimpleNamespace(from_env=lambda: FakeDockerClient())
    fake_errors = SimpleNamespace(DockerException=FakeDockerError, NotFound=FakeNotFoundError)
    fake_kafka_module = SimpleNamespace(KafkaContainer=FakeKafkaContainer)

    def fake_importorskip(name, **kwargs):
        del kwargs
        if name == "docker":
            return fake_docker
        if name == "docker.errors":
            return fake_errors
        if name == "testcontainers.kafka":
            return fake_kafka_module
        raise AssertionError(name)

    monkeypatch.setattr(integration_conftest.pytest, "importorskip", fake_importorskip)

    fixture = integration_conftest.kafka_container.__wrapped__()
    assert next(fixture).image == "confluentinc/cp-kafka:7.7.0"

    with pytest.raises(StopIteration):
        next(fixture)
