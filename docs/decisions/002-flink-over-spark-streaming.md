# ADR-002: Apache Flink over Spark Structured Streaming

## Status
Accepted

## Context
We need a stream processing engine that can handle 50k+ events/sec with sub-second latency, exactly-once semantics, and good Python support.

Candidates:
1. Apache Flink 1.19
2. Spark Structured Streaming 3.5
3. Kafka Streams (Java-only, ruled out for Python codebase)

## Decision
**Apache Flink** for all stream processing.

## Comparison

| Criterion | Flink | Spark Streaming |
|-----------|-------|-----------------|
| Latency (p50) | ~100ms | ~500ms-2s (micro-batch) |
| Event-time processing | Native, first-class | Supported but less ergonomic |
| Watermarks | Built-in, configurable | Limited watermark support |
| Exactly-once | Native with checkpoints | Requires careful configuration |
| Backpressure | Native flow control | Can cause micro-batch delays |
| Python API | PyFlink (maturing) | PySpark (mature) |
| Managed AWS service | Managed Flink | EMR Serverless |
| Batch support | Bounded streams (unified) | Native (strong) |

## Consequences

### Positive
- True event-time processing with watermarks — critical for late-arriving events
- Lower and more predictable latency (~200ms vs ~2s)
- Unified batch and stream in one engine
- Built-in state management with RocksDB backend

### Negative
- PyFlink is less mature than PySpark — fewer examples, thinner docs
- Smaller talent pool for Flink vs Spark
- Managed Flink on AWS is newer than EMR

### Mitigations
- Core processing logic in pure Python functions (testable without Flink)
- Comprehensive integration tests with testcontainers
- Team upskilling plan: Flink certification for 2 engineers
