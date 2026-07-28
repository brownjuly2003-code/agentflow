FROM alpine:3.24.1@sha256:28bd5fe8b56d1bd048e5babf5b10710ebe0bae67db86916198a6eec434943f8b AS kafka-connect-artifact-fetcher

SHELL ["/bin/ash", "-eo", "pipefail", "-c"]

ARG DEBEZIUM_VERSION=3.6.0.Final
ARG POSTGRES_JDBC_VERSION=42.7.13
ARG JACKSON_VERSION=2.21.4
ARG JETTY_VERSION=12.0.36
ARG DEBEZIUM_POSTGRES_SHA256=f810048b2880fe559d47aea75091ccc2ad0249fbce93d3c1e303588b17b6a060
ARG DEBEZIUM_MYSQL_SHA256=99d6573c11b1ddd609995fbc4afe31de616c1034e68c34741dfdef9aacc9f5c6
ARG POSTGRES_JDBC_SHA256=6e0e4cc2d8cae902084f8a2b18728b073a6fd9d1f87c9d8bff8f298c18185b93
ARG JACKSON_CORE_SHA256=4b40a06396f239f8de2da57419adde6e94e5edc18a2171d471ea05eeed4e5c2d
ARG JACKSON_DATABIND_SHA256=3888e9e69ab66fbacaacc9aea0e9ffbf15368288e4aca468b024dba11c09fbf9
ARG JETTY_SECURITY_SHA256=e6fb70974291312c58ac84d8bf28c909d1800d1b3104020e7cd4db77391f9fb2

RUN mkdir -p /artifacts /debezium/mysql /debezium/postgres \
    && wget -q -O /tmp/debezium-postgres.tar.gz \
        "https://repo1.maven.org/maven2/io/debezium/debezium-connector-postgres/${DEBEZIUM_VERSION}/debezium-connector-postgres-${DEBEZIUM_VERSION}-plugin.tar.gz" \
    && echo "${DEBEZIUM_POSTGRES_SHA256}  /tmp/debezium-postgres.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/debezium-postgres.tar.gz -C /debezium/postgres --strip-components=1 \
    && wget -q -O /tmp/debezium-mysql.tar.gz \
        "https://repo1.maven.org/maven2/io/debezium/debezium-connector-mysql/${DEBEZIUM_VERSION}/debezium-connector-mysql-${DEBEZIUM_VERSION}-plugin.tar.gz" \
    && echo "${DEBEZIUM_MYSQL_SHA256}  /tmp/debezium-mysql.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/debezium-mysql.tar.gz -C /debezium/mysql --strip-components=1 \
    && find /debezium/postgres -type f -name 'postgresql-*.jar' -delete \
    && wget -q -O "/artifacts/postgresql-${POSTGRES_JDBC_VERSION}.jar" \
        "https://repo1.maven.org/maven2/org/postgresql/postgresql/${POSTGRES_JDBC_VERSION}/postgresql-${POSTGRES_JDBC_VERSION}.jar" \
    && echo "${POSTGRES_JDBC_SHA256}  /artifacts/postgresql-${POSTGRES_JDBC_VERSION}.jar" | sha256sum -c - \
    && wget -q -O "/artifacts/jackson-core-${JACKSON_VERSION}.jar" \
        "https://repo1.maven.org/maven2/com/fasterxml/jackson/core/jackson-core/${JACKSON_VERSION}/jackson-core-${JACKSON_VERSION}.jar" \
    && echo "${JACKSON_CORE_SHA256}  /artifacts/jackson-core-${JACKSON_VERSION}.jar" | sha256sum -c - \
    && wget -q -O "/artifacts/jackson-databind-${JACKSON_VERSION}.jar" \
        "https://repo1.maven.org/maven2/com/fasterxml/jackson/core/jackson-databind/${JACKSON_VERSION}/jackson-databind-${JACKSON_VERSION}.jar" \
    && echo "${JACKSON_DATABIND_SHA256}  /artifacts/jackson-databind-${JACKSON_VERSION}.jar" | sha256sum -c - \
    && wget -q -O "/artifacts/jetty-security-${JETTY_VERSION}.jar" \
        "https://repo1.maven.org/maven2/org/eclipse/jetty/jetty-security/${JETTY_VERSION}/jetty-security-${JETTY_VERSION}.jar" \
    && echo "${JETTY_SECURITY_SHA256}  /artifacts/jetty-security-${JETTY_VERSION}.jar" | sha256sum -c -

FROM apache/kafka:4.3.1@sha256:77e3df9054047a88b520d0cc46e16696d3b22022e1d580aeccd2632df6532837

ARG DEBEZIUM_PLUGIN_DIR=/usr/share/java/debezium

USER root

RUN apk upgrade --no-cache \
    && apk add --no-cache curl python3 \
    && rm -f \
        /opt/kafka/libs/jackson-core-*.jar \
        /opt/kafka/libs/jackson-databind-*.jar \
        /opt/kafka/libs/jetty-security-*.jar \
        /opt/kafka/libs/jline-*.jar

COPY --from=kafka-connect-artifact-fetcher /artifacts/jackson-core-2.21.4.jar /opt/kafka/libs/jackson-core-2.21.4.jar
COPY --from=kafka-connect-artifact-fetcher /artifacts/jackson-databind-2.21.4.jar /opt/kafka/libs/jackson-databind-2.21.4.jar
COPY --from=kafka-connect-artifact-fetcher /artifacts/jetty-security-12.0.36.jar /opt/kafka/libs/jetty-security-12.0.36.jar
COPY --from=kafka-connect-artifact-fetcher /debezium/ "${DEBEZIUM_PLUGIN_DIR}/"
COPY --from=kafka-connect-artifact-fetcher /artifacts/postgresql-42.7.13.jar "${DEBEZIUM_PLUGIN_DIR}/postgres/postgresql-42.7.13.jar"
COPY docker/kafka-connect/connect-distributed.properties /opt/kafka/config/agentflow-connect-distributed.properties

USER appuser

ENTRYPOINT ["/opt/kafka/bin/connect-distributed.sh"]
CMD ["/opt/kafka/config/agentflow-connect-distributed.properties"]
