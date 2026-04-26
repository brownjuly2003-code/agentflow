FROM confluentinc/cp-kafka-connect-base:7.7.0

ARG DEBEZIUM_VERSION=3.5.0.Final
ARG DEBEZIUM_PLUGIN_DIR=/usr/share/java/debezium

USER root

RUN mkdir -p "${DEBEZIUM_PLUGIN_DIR}" \
    && curl -fsSL "https://repo1.maven.org/maven2/io/debezium/debezium-connector-postgres/${DEBEZIUM_VERSION}/debezium-connector-postgres-${DEBEZIUM_VERSION}-plugin.tar.gz" \
        | tar -xz -C "${DEBEZIUM_PLUGIN_DIR}" --strip-components=1 \
    && curl -fsSL "https://repo1.maven.org/maven2/io/debezium/debezium-connector-mysql/${DEBEZIUM_VERSION}/debezium-connector-mysql-${DEBEZIUM_VERSION}-plugin.tar.gz" \
        | tar -xz -C "${DEBEZIUM_PLUGIN_DIR}" --strip-components=1

USER appuser
