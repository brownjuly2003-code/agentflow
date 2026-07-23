FROM flink:2.3.0-scala_2.12-java17@sha256:12a034b71a4d6d55227d14fe0ba69b0612c065a1dfaa756de4858fc56148c99c

ARG FLINK_VERSION=2.3.0
# The externalised Kafka connector is versioned <connector>-<flink minor> and
# its newest published build is 5.0.0-2.2 — there is no -2.3 artifact. Flink
# keeps @Public API stable inside a major, so the 2.2 build runs on a 2.3
# cluster; flink-smoke submits the real job against it to keep that honest.
ARG PYFLINK_KAFKA_JAR_VERSION=5.0.0-2.2

# The Python manifest lives next to this Dockerfile (compose builds with
# context ./src). The assert below keeps its apache-flink pin from drifting
# away from the Flink binary distribution version above.
COPY processing/flink_jobs/requirements.txt /tmp/flink-requirements.txt

ARG CURL_GUARDS="--connect-timeout 30 --speed-limit 65536 --speed-time 60 --retry 5 --retry-all-errors"

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl python3 python3-pip python3-venv \
    && test -e "/opt/flink/lib/flink-dist-${FLINK_VERSION}.jar" \
    && test -e "/opt/flink/opt/flink-python-${FLINK_VERSION}.jar" \
    && curl -fsSL $CURL_GUARDS "https://repo.maven.apache.org/maven2/org/apache/flink/flink-sql-connector-kafka/${PYFLINK_KAFKA_JAR_VERSION}/flink-sql-connector-kafka-${PYFLINK_KAFKA_JAR_VERSION}.jar" -o "/opt/flink/lib/flink-sql-connector-kafka-${PYFLINK_KAFKA_JAR_VERSION}.jar" \
    && mkdir -p /opt/flink/plugins/s3-fs-hadoop \
    && ln -s "/opt/flink/opt/flink-s3-fs-hadoop-${FLINK_VERSION}.jar" "/opt/flink/plugins/s3-fs-hadoop/flink-s3-fs-hadoop-${FLINK_VERSION}.jar" \
    && test -e "/opt/flink/plugins/s3-fs-hadoop/flink-s3-fs-hadoop-${FLINK_VERSION}.jar" \
    && python3 -m venv /opt/pyflink-venv \
    && /opt/pyflink-venv/bin/python -m pip install --no-cache-dir --upgrade pip \
    && /opt/pyflink-venv/bin/python -m pip install --no-cache-dir -r /tmp/flink-requirements.txt \
    && /opt/pyflink-venv/bin/python -c "from importlib.metadata import version; v = version('apache-flink'); assert v == '${FLINK_VERSION}', f'requirements.txt installed apache-flink {v}, ARG FLINK_VERSION is ${FLINK_VERSION}'" \
    && rm -rf /var/lib/apt/lists/* /tmp/flink-requirements.txt

WORKDIR /opt/agentflow
ENV PATH="/opt/pyflink-venv/bin:/opt/flink/bin:${PATH}"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYFLINK_CLIENT_EXECUTABLE=/opt/pyflink-venv/bin/python
ENV PYTHONPATH=/opt/agentflow

COPY --chown=flink:flink . /opt/agentflow/src
USER flink
