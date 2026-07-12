FROM python:3.11-slim-bookworm@sha256:721dc13fd1be0a771e54b72097634291d628d0007dee9da777e2ce676a9c998f

ARG FLINK_VERSION=2.3.0
ARG SCALA_VERSION=2.12
# The externalised Kafka connector is versioned <connector>-<flink minor> and
# its newest published build is 5.0.0-2.2 — there is no -2.3 artifact. Flink
# keeps @Public API stable inside a major, so the 2.2 build runs on a 2.3
# cluster; flink-smoke submits the real job against it to keep that honest.
ARG PYFLINK_KAFKA_JAR_VERSION=5.0.0-2.2

# The Python manifest lives next to this Dockerfile (compose builds with
# context ./src). The assert below keeps its apache-flink pin from drifting
# away from the Flink binary distribution version above.
COPY processing/flink_jobs/requirements.txt /tmp/flink-requirements.txt

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates curl openjdk-17-jre-headless \
    && curl -fsSL "https://archive.apache.org/dist/flink/flink-${FLINK_VERSION}/flink-${FLINK_VERSION}-bin-scala_${SCALA_VERSION}.tgz" -o /tmp/flink.tgz \
    && tar -xzf /tmp/flink.tgz -C /opt \
    && ln -s "/opt/flink-${FLINK_VERSION}" /opt/flink \
    && curl -fsSL "https://repo.maven.apache.org/maven2/org/apache/flink/flink-sql-connector-kafka/${PYFLINK_KAFKA_JAR_VERSION}/flink-sql-connector-kafka-${PYFLINK_KAFKA_JAR_VERSION}.jar" -o "/opt/flink/lib/flink-sql-connector-kafka-${PYFLINK_KAFKA_JAR_VERSION}.jar" \
    && mkdir -p /opt/flink/plugins/s3-fs-hadoop \
    && ln -s "/opt/flink/opt/flink-s3-fs-hadoop-${FLINK_VERSION}.jar" "/opt/flink/plugins/s3-fs-hadoop/flink-s3-fs-hadoop-${FLINK_VERSION}.jar" \
    && test -e "/opt/flink/plugins/s3-fs-hadoop/flink-s3-fs-hadoop-${FLINK_VERSION}.jar" \
    && python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r /tmp/flink-requirements.txt \
    && python -c "from importlib.metadata import version; v = version('apache-flink'); assert v == '${FLINK_VERSION}', f'requirements.txt installed apache-flink {v}, ARG FLINK_VERSION is ${FLINK_VERSION}'" \
    && rm -rf /var/lib/apt/lists/* /tmp/flink.tgz /tmp/flink-requirements.txt

WORKDIR /opt/agentflow
ENV FLINK_HOME=/opt/flink
ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
ENV PATH="/opt/flink/bin:${PATH}"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYFLINK_CLIENT_EXECUTABLE=/usr/local/bin/python
ENV PYTHONPATH=/opt/agentflow

COPY . /opt/agentflow/src
