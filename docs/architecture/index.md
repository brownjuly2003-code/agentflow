# Architecture

AgentFlow separates source capture, stream processing, storage, semantic
serving, and agent-facing clients. The local path uses the same validation and
semantic concepts as the production-shaped path, but swaps managed
infrastructure for local services and DuckDB.

## C4 level 1: system context

```mermaid
flowchart TB
    support["Support agent"]
    ops["Ops agent"]
    merch["Merch agent"]
    apps["Operational systems\norders, payments, inventory"]
    dbs["Postgres / MySQL sources"]
    platform["AgentFlow\nreal-time data platform"]
    observability["Observability tools"]

    support -->|"entity lookup / query"| platform
    ops -->|"metrics / SLO / events"| platform
    merch -->|"catalog / metrics / search"| platform
    apps -->|"events"| platform
    dbs -->|"CDC"| platform
    platform -->|"metrics, traces, logs"| observability
```

## C4 level 2: containers

```mermaid
flowchart LR
    subgraph Sources
        producers["Kafka producers"]
        cdc["Debezium / Kafka Connect"]
        local["Local generator"]
    end

    subgraph Pipeline
        kafka["Kafka topics"]
        flink["Flink jobs"]
        quality["Schema and semantic validation"]
        dlq["Dead-letter topic"]
    end

    subgraph Storage
        duckdb["DuckDB serving store"]
        iceberg["Iceberg lakehouse tables"]
        clickhouse["Optional ClickHouse backend"]
    end

    subgraph Serving
        semantic["Semantic layer"]
        api["FastAPI v1"]
        background["Outbox, alerts, webhooks"]
    end

    subgraph Clients
        py["Python SDK"]
        ts["TypeScript SDK"]
        http["curl / direct HTTP"]
    end

    producers --> kafka
    cdc --> kafka
    local --> quality
    kafka --> flink
    flink --> quality
    quality -->|"valid"| duckdb
    quality -->|"valid"| iceberg
    quality -->|"invalid"| dlq
    iceberg -. "lakehouse storage" .-> semantic
    duckdb --> semantic
    clickhouse -. "configured serving backend" .-> semantic
    semantic --> api
    background --> api
    api --> py
    api --> ts
    api --> http
```

## Runtime data flow

```mermaid
flowchart TD
    raw["Raw event or CDC envelope"] --> normalize["Normalize to AgentFlow event"]
    normalize --> schema["Schema validation"]
    schema --> semantic["Semantic validation"]
    semantic --> enrich["Enrichment"]
    enrich --> store["Serving and lakehouse storage"]
    store --> query["Semantic layer query"]
    query --> response["Agent-facing response"]
    schema -->|"invalid"| deadletter["Dead-letter record"]
    semantic -->|"invalid"| deadletter
    deadletter --> replay["Replay or dismiss workflow"]
```

## Entity lookup sequence

```mermaid
sequenceDiagram
    participant Agent
    participant SDK
    participant API as FastAPI
    participant Auth as Auth and rate limit
    participant Semantic as Semantic layer
    participant Store as DuckDB / backend

    Agent->>SDK: getOrder("ORD-20260404-1001")
    SDK->>API: GET /v1/entity/order/ORD-20260404-1001
    API->>Auth: validate key, tenant, limits
    Auth-->>API: request context
    API->>Semantic: resolve entity lookup
    Semantic->>Store: parameterized query
    Store-->>Semantic: current row
    Semantic-->>API: entity payload + freshness
    API-->>SDK: JSON response + headers
    SDK-->>Agent: typed object
```

## CDC and dead-letter flow

```mermaid
flowchart LR
    pg["Postgres"] --> connect["Debezium connector"]
    mysql["MySQL"] --> connect
    connect --> raw["Kafka raw CDC topics"]
    raw --> normalizer["CDC normalizer"]
    normalizer --> validate["Validation and enrichment"]
    validate -->|"valid"| validated["events.validated"]
    validate -->|"invalid"| deadletter["events.deadletter"]
    validated --> serving["Serving tables"]
    deadletter --> ops["Dead-letter API"]
    ops -->|"correct and replay"| validated
    ops -->|"dismiss"| archive["Dismissed record"]
```

## Key boundaries

| Boundary | Purpose |
| --- | --- |
| Source capture | Turns application events and CDC envelopes into pipeline input |
| Validation | Prevents invalid data from becoming agent-visible state |
| Semantic layer | Gives agents entity, metric, contract, and query abstractions instead of raw tables |
| API auth | Applies API-key, tenant, entity-scope, and rate-limit checks |
| SDK contract | Keeps Python and TypeScript clients aligned with the v1 HTTP surface |
| Observability | Correlates request, pipeline, and background workflow behavior |
