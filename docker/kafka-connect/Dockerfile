FROM confluentinc/cp-kafka-connect-base:7.9.8@sha256:54f3a9791b1a9c939eec00268fbb4c348c98a1e475af28e241be81a2b97b56d9

ARG DEBEZIUM_VERSION=3.5.0.Final
ARG DEBEZIUM_PLUGIN_DIR=/usr/share/java/debezium

USER root

RUN mkdir -p "${DEBEZIUM_PLUGIN_DIR}" \
    && curl -fsSL "https://repo1.maven.org/maven2/io/debezium/debezium-connector-postgres/${DEBEZIUM_VERSION}/debezium-connector-postgres-${DEBEZIUM_VERSION}-plugin.tar.gz" \
        | tar -xz -C "${DEBEZIUM_PLUGIN_DIR}" --strip-components=1 \
    && curl -fsSL "https://repo1.maven.org/maven2/io/debezium/debezium-connector-mysql/${DEBEZIUM_VERSION}/debezium-connector-mysql-${DEBEZIUM_VERSION}-plugin.tar.gz" \
        | tar -xz -C "${DEBEZIUM_PLUGIN_DIR}" --strip-components=1

USER appuser
