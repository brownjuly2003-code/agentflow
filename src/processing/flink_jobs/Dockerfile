FROM flink:2.3.0-scala_2.12-java17@sha256:07745f54f8e5f0d3d1d351643b69bfbcbb426ba8720d6636d2940fd4638f6e58

ARG FLINK_VERSION=2.3.0
# The externalised Kafka connector is versioned <connector>-<flink minor> and
# its newest published build is 5.0.0-2.2 — there is no -2.3 artifact. Flink
# keeps @Public API stable inside a major, so the 2.2 build runs on a 2.3
# cluster; flink-smoke submits the real job against it to keep that honest.
ARG PYFLINK_KAFKA_JAR_VERSION=5.0.0-2.2
# Maven Central official SHA-1 sidecar / X-Checksum-Sha1 for this coordinate
# (Content-Length 10666527, observed 2026-08-12). No .sha256 sidecar is published.
ARG PYFLINK_KAFKA_JAR_SHA1=7bf2ded1144cb8aece05adcaccbc81b2ac3ef339
ARG PYFLINK_KAFKA_JAR_BYTES=10666527

# The Python manifest lives next to this Dockerfile (compose builds with
# context ./src). The assert below keeps its apache-flink pin from drifting
# away from the Flink binary distribution version above.
COPY processing/flink_jobs/requirements.txt /tmp/flink-requirements.txt

ARG CURL_GUARDS="--connect-timeout 30 --speed-limit 65536 --speed-time 60 --retry 5 --retry-all-errors"

USER root
# BuildKit cache reuses a verified JAR across CI's same-runner build retry.
# Cache hits skip the network; corrupt/partial entries are discarded.
RUN --mount=type=cache,id=flink-sql-connector-kafka-5.0.0-2.2,target=/var/cache/flink-connectors \
    apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl python3 python3-pip python3-venv \
    && test -e "/opt/flink/lib/flink-dist-${FLINK_VERSION}.jar" \
    && test -e "/opt/flink/opt/flink-python-${FLINK_VERSION}.jar" \
    && connector_jar="flink-sql-connector-kafka-${PYFLINK_KAFKA_JAR_VERSION}.jar" \
    && cache_jar="/var/cache/flink-connectors/${connector_jar}" \
    && install_jar="/opt/flink/lib/${connector_jar}" \
    && coord="org/apache/flink/flink-sql-connector-kafka/${PYFLINK_KAFKA_JAR_VERSION}/${connector_jar}" \
    && verify_jar() { \
         test -f "$1" \
         && test "$(stat -c%s "$1")" = "${PYFLINK_KAFKA_JAR_BYTES}" \
         && echo "${PYFLINK_KAFKA_JAR_SHA1}  $1" | sha1sum -c -; \
       } \
    && if ! verify_jar "${cache_jar}"; then \
         rm -f "${cache_jar}"; \
         mkdir -p /var/cache/flink-connectors; \
         tmp_jar="$(mktemp "${cache_jar}.tmp.XXXXXX")"; \
         acquired=0; \
         for base in \
           "https://repository.apache.org/content/repositories/releases" \
           "https://repo.maven.apache.org/maven2"; do \
           if curl -fsSL $CURL_GUARDS "${base}/${coord}" -o "${tmp_jar}" \
             && verify_jar "${tmp_jar}"; then \
             mv -f "${tmp_jar}" "${cache_jar}"; \
             acquired=1; \
             break; \
           fi; \
           rm -f "${tmp_jar}"; \
         done; \
         test "${acquired}" = "1"; \
       fi \
    && verify_jar "${cache_jar}" \
    && install -m 0644 "${cache_jar}" "${install_jar}" \
    && verify_jar "${install_jar}" \
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
