FROM python:3.11-slim-bookworm

ARG FLINK_VERSION=1.19.1
ARG SCALA_VERSION=2.12
ARG PYFLINK_KAFKA_JAR_VERSION=3.3.0-1.19

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates curl openjdk-17-jre-headless \
    && curl -fsSL "https://archive.apache.org/dist/flink/flink-${FLINK_VERSION}/flink-${FLINK_VERSION}-bin-scala_${SCALA_VERSION}.tgz" -o /tmp/flink.tgz \
    && tar -xzf /tmp/flink.tgz -C /opt \
    && ln -s "/opt/flink-${FLINK_VERSION}" /opt/flink \
    && curl -fsSL "https://repo.maven.apache.org/maven2/org/apache/flink/flink-sql-connector-kafka/${PYFLINK_KAFKA_JAR_VERSION}/flink-sql-connector-kafka-${PYFLINK_KAFKA_JAR_VERSION}.jar" -o "/opt/flink/lib/flink-sql-connector-kafka-${PYFLINK_KAFKA_JAR_VERSION}.jar" \
    && mkdir -p /opt/flink/plugins/s3-fs-hadoop \
    && ln -s "/opt/flink/opt/flink-s3-fs-hadoop-${FLINK_VERSION}.jar" "/opt/flink/plugins/s3-fs-hadoop/flink-s3-fs-hadoop-${FLINK_VERSION}.jar" \
    && python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir "apache-flink==${FLINK_VERSION}" confluent-kafka pydantic structlog \
    && rm -rf /var/lib/apt/lists/* /tmp/flink.tgz

WORKDIR /opt/agentflow
ENV FLINK_HOME=/opt/flink
ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
ENV PATH="/opt/flink/bin:${PATH}"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYFLINK_CLIENT_EXECUTABLE=/usr/local/bin/python
ENV PYTHONPATH=/opt/agentflow

COPY . /opt/agentflow/src

RUN cat <<'PY' > /opt/agentflow/sitecustomize.py
from datetime import timedelta as _timedelta

try:
    from pyflink.common import WatermarkStrategy
    from pyflink.common.time import Duration, Time
    from pyflink.datastream.state import StateTtlConfig
except Exception:
    pass
else:
    _original_watermark = WatermarkStrategy.for_bounded_out_of_orderness
    _original_ttl_builder = StateTtlConfig.new_builder

    def _patched_watermark(max_out_of_orderness):
        if isinstance(max_out_of_orderness, _timedelta):
            max_out_of_orderness = Duration.of_millis(int(max_out_of_orderness.total_seconds() * 1000))
        return _original_watermark(max_out_of_orderness)

    def _patched_ttl_builder(ttl):
        if isinstance(ttl, _timedelta):
            ttl = Time.milliseconds(int(ttl.total_seconds() * 1000))
        return _original_ttl_builder(ttl)

    WatermarkStrategy.for_bounded_out_of_orderness = staticmethod(_patched_watermark)
    StateTtlConfig.new_builder = staticmethod(_patched_ttl_builder)
PY
