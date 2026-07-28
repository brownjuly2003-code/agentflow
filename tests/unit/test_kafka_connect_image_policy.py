from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "docker" / "kafka-connect" / "Dockerfile"
WORKER_CONFIG = ROOT / "docker" / "kafka-connect" / "connect-distributed.properties"

ALPINE_BUILDER = (
    "FROM alpine:3.24.1@"
    "sha256:28bd5fe8b56d1bd048e5babf5b10710ebe0bae67db86916198a6eec434943f8b "
    "AS kafka-connect-artifact-fetcher"
)
APACHE_KAFKA_RUNTIME = (
    "FROM apache/kafka:4.3.1@"
    "sha256:77e3df9054047a88b520d0cc46e16696d3b22022e1d580aeccd2632df6532837"
)


def test_kafka_connect_runtime_uses_a_digest_pinned_apache_release() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert APACHE_KAFKA_RUNTIME in dockerfile
    assert "confluentinc/" not in dockerfile
    assert "ARG DEBEZIUM_VERSION=3.6.0.Final" in dockerfile
    assert "ARG POSTGRES_JDBC_VERSION=42.7.13" in dockerfile


def test_kafka_connect_downloads_are_checksum_verified_in_the_builder() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert dockerfile.splitlines()[0] == ALPINE_BUILDER
    builder_stage = dockerfile[: dockerfile.index(APACHE_KAFKA_RUNTIME)]
    assert 'SHELL ["/bin/ash", "-eo", "pipefail", "-c"]' in builder_stage
    for checksum in (
        "f810048b2880fe559d47aea75091ccc2ad0249fbce93d3c1e303588b17b6a060",
        "99d6573c11b1ddd609995fbc4afe31de616c1034e68c34741dfdef9aacc9f5c6",
        "6e0e4cc2d8cae902084f8a2b18728b073a6fd9d1f87c9d8bff8f298c18185b93",
        "4b40a06396f239f8de2da57419adde6e94e5edc18a2171d471ea05eeed4e5c2d",
        "3888e9e69ab66fbacaacc9aea0e9ffbf15368288e4aca468b024dba11c09fbf9",
        "e6fb70974291312c58ac84d8bf28c909d1800d1b3104020e7cd4db77391f9fb2",
    ):
        assert checksum in builder_stage
    assert builder_stage.count("sha256sum -c -") >= 6

    runtime_stage = dockerfile[dockerfile.index(APACHE_KAFKA_RUNTIME) :]
    assert "wget " not in runtime_stage
    assert "tar " not in runtime_stage


def test_kafka_connect_runtime_replaces_all_known_vulnerable_components() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    runtime_stage = dockerfile[dockerfile.index(APACHE_KAFKA_RUNTIME) :]

    assert "apk upgrade --no-cache" in runtime_stage
    assert "apk add --no-cache curl" in runtime_stage
    for vulnerable_jar in (
        "jackson-core-*.jar",
        "jackson-databind-*.jar",
        "jetty-security-*.jar",
        "jline-*.jar",
    ):
        assert vulnerable_jar in runtime_stage
    for fixed_jar in (
        "jackson-core-2.21.4.jar",
        "jackson-databind-2.21.4.jar",
        "jetty-security-12.0.36.jar",
        "postgresql-42.7.13.jar",
    ):
        assert fixed_jar in runtime_stage


def test_debezium_connectors_use_separate_plugin_classloader_directories() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert "mkdir -p /artifacts /debezium/mysql /debezium/postgres" in dockerfile
    assert "-C /debezium/postgres --strip-components=1" in dockerfile
    assert "-C /debezium/mysql --strip-components=1" in dockerfile
    assert "find /debezium/postgres -type f -name 'postgresql-*.jar' -delete" in dockerfile
    assert '"${DEBEZIUM_PLUGIN_DIR}/postgres/postgresql-42.7.13.jar"' in dockerfile


def test_kafka_connect_uses_a_static_worker_config_with_env_and_file_providers() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    worker_config = WORKER_CONFIG.read_text(encoding="utf-8")

    assert (
        "COPY docker/kafka-connect/connect-distributed.properties "
        "/opt/kafka/config/agentflow-connect-distributed.properties"
    ) in dockerfile
    assert 'ENTRYPOINT ["/opt/kafka/bin/connect-distributed.sh"]' in dockerfile
    assert 'CMD ["/opt/kafka/config/agentflow-connect-distributed.properties"]' in dockerfile

    for setting in (
        "bootstrap.servers=${env:CONNECT_BOOTSTRAP_SERVERS}",
        "rest.advertised.host.name=${env:CONNECT_REST_ADVERTISED_HOST_NAME}",
        "rest.port=${env:CONNECT_REST_PORT}",
        "group.id=${env:CONNECT_GROUP_ID}",
        "config.storage.topic=${env:CONNECT_CONFIG_STORAGE_TOPIC}",
        "offset.storage.topic=${env:CONNECT_OFFSET_STORAGE_TOPIC}",
        "status.storage.topic=${env:CONNECT_STATUS_STORAGE_TOPIC}",
        "key.converter=${env:CONNECT_KEY_CONVERTER}",
        "value.converter=${env:CONNECT_VALUE_CONVERTER}",
        "plugin.path=/usr/share/java/debezium",
        "config.providers=env,file",
        ("config.providers.env.class=org.apache.kafka.common.config.provider.EnvVarConfigProvider"),
        ("config.providers.file.class=org.apache.kafka.common.config.provider.FileConfigProvider"),
    ):
        assert setting in worker_config
    assert "${env:CONNECT_PLUGIN_PATH}" not in worker_config
