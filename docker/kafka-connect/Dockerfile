FROM confluentinc/cp-kafka-connect-base:7.9.7@sha256:93b9afd3e7f8003381401464e4e4fa3dbe5e3766bcbc99de12afd41dc2904055

ARG DEBEZIUM_VERSION=3.5.0.Final
ARG DEBEZIUM_PLUGIN_DIR=/usr/share/java/debezium

USER root

RUN mkdir -p "${DEBEZIUM_PLUGIN_DIR}" \
    && curl -fsSL "https://repo1.maven.org/maven2/io/debezium/debezium-connector-postgres/${DEBEZIUM_VERSION}/debezium-connector-postgres-${DEBEZIUM_VERSION}-plugin.tar.gz" \
        | tar -xz -C "${DEBEZIUM_PLUGIN_DIR}" --strip-components=1 \
    && curl -fsSL "https://repo1.maven.org/maven2/io/debezium/debezium-connector-mysql/${DEBEZIUM_VERSION}/debezium-connector-mysql-${DEBEZIUM_VERSION}-plugin.tar.gz" \
        | tar -xz -C "${DEBEZIUM_PLUGIN_DIR}" --strip-components=1

USER appuser
