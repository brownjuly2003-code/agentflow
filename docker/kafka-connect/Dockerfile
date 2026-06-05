FROM confluentinc/cp-kafka-connect-base:8.2.1@sha256:789f76d5e44654f7d6db46649a5ee6697006fd10cd1c13b87773a7f6885041b9

ARG DEBEZIUM_VERSION=3.5.0.Final
ARG DEBEZIUM_PLUGIN_DIR=/usr/share/java/debezium

USER root

RUN mkdir -p "${DEBEZIUM_PLUGIN_DIR}" \
    && curl -fsSL "https://repo1.maven.org/maven2/io/debezium/debezium-connector-postgres/${DEBEZIUM_VERSION}/debezium-connector-postgres-${DEBEZIUM_VERSION}-plugin.tar.gz" \
        | tar -xz -C "${DEBEZIUM_PLUGIN_DIR}" --strip-components=1 \
    && curl -fsSL "https://repo1.maven.org/maven2/io/debezium/debezium-connector-mysql/${DEBEZIUM_VERSION}/debezium-connector-mysql-${DEBEZIUM_VERSION}-plugin.tar.gz" \
        | tar -xz -C "${DEBEZIUM_PLUGIN_DIR}" --strip-components=1

USER appuser
