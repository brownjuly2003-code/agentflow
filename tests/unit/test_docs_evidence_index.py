from __future__ import annotations

import hashlib
import re
import subprocess
import tomllib
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = ROOT / "docs" / "evidence"
INDEX = EVIDENCE_DIR / "INDEX.md"
STATUS = ROOT / "docs" / "STATUS.md"
CLAIMS = ROOT / "config" / "project_claims.toml"
ARCHITECTURE = ROOT / "docs" / "architecture.md"
CHANGELOG = ROOT / "CHANGELOG.md"
DV2_DEMO_EVIDENCE = ROOT / "docs" / "dv2-multi-branch" / "demo_evidence.md"
DOCUMENTATION_PLAN = ROOT / "plan_26_08_2026.md"

SECURITY_DEPENDENCY_HEADING = "## Security and dependency records"
ACCEPTANCE_HEADING = "## Golden topology acceptance records"
REQUIRED_FIELDS = (
    "identity",
    "date",
    "result",
    "supersedes",
    "superseded by",
    "claim boundary",
)
PROTECTED_DIGESTS = {
    "docs/evidence/security-s12-2026-07-09.md": (
        "4b2223a35e5817214171aedf988b814e2bed97a08bfaa2f817c17d5e05e9108a"
    ),
    "docs/evidence/security-runtime-image-trivy-2026-07-30.md": (
        "6bbb2ebb5ff7f98db11e4f1ceb1af099116ccba806edac2ffc1221db60238d28"
    ),
    "docs/evidence/dependency-compatibility-2026-07-30.md": (
        "79618c9eea6aa31c18a7d17558c995bd424abf620f4e901b2542d1cc3031635f"
    ),
}
ENTITY_HOT_PATH_HEADING = "## Historical entity hot-path optimization records"
ENTITY_BASELINE_RECORD = "docs/perf/entity-profile-2026-04-24.md"
ENTITY_PII_CACHE_RECORD = "docs/perf/entity-profile-after-pii-masker-cache.md"
ENTITY_TENANT_CACHE_RECORD = "docs/perf/entity-profile-after-tenant-qualification-cache.md"
ENTITY_HOT_PATH_RECORDS = (
    ENTITY_BASELINE_RECORD,
    ENTITY_PII_CACHE_RECORD,
    ENTITY_TENANT_CACHE_RECORD,
)
ENTITY_HOT_PATH_DATES = {
    ENTITY_BASELINE_RECORD: "2026-04-24",
    ENTITY_PII_CACHE_RECORD: "2026-04-24",
    ENTITY_TENANT_CACHE_RECORD: "2026-04-25",
}
ENTITY_HOT_PATH_DIGESTS = {
    ENTITY_BASELINE_RECORD: ("99904b66387dcd002095d9fe17458891099de81ff03d2719837038266f252c99"),
    ENTITY_PII_CACHE_RECORD: ("27ba68bb1ef0541f72afe7055fec8f81d011c1688638b32f7f858fc4745667aa"),
    ENTITY_TENANT_CACHE_RECORD: (
        "2728e47a30eab0cde0a175759c86e2de9ee3dfc61d7d5751b62f7c76517952fa"
    ),
}
PERF_NON_IDENTITY_HEADING = "## Classified non-identity performance paths"
PERF_NON_IDENTITY_FIELDS = (
    "path",
    "class",
    "status/claim owner",
    "evidence relationship",
)
PERF_NON_IDENTITY_PATHS = {
    "docs/perf/benchmark-split-decision.md",
    "docs/perf/bridge-ch-native-apply-q1-2026-07-09.md",
    "docs/perf/entity-benchmark-contract.md",
    "docs/perf/freshness-benchmark.md",
    "docs/perf/load-benchmark-latest.md",
    "docs/perf/public-production-hardware-benchmark-plan.md",
    "docs/perf/throughput-realpath.md",
}
PERF_NON_IDENTITY_PHRASES = {
    "docs/perf/benchmark-split-decision.md": (
        "dated decision",
        "executable ci gate",
        "not a current status owner",
        "not an evidence identity",
    ),
    "docs/perf/bridge-ch-native-apply-q1-2026-07-09.md": (
        "implementation companion",
        "q1.2",
        "throughput-realpath-q12-2026-07-09.md",
        "not an evidence identity",
    ),
    "docs/perf/entity-benchmark-contract.md": (
        "current benchmark reference",
        "scripts/profile_entity.py",
        "not a measured result",
        "not an evidence identity",
    ),
    "docs/perf/freshness-benchmark.md": (
        "current benchmark lifecycle reference",
        "scripts/benchmark_freshness.py",
        ".artifacts/freshness",
        "not a measured result",
    ),
    "docs/perf/load-benchmark-latest.md": (
        "current benchmark lifecycle reference",
        "scripts/run_benchmark.py",
        ".artifacts/benchmark",
        "not a measured result",
    ),
    "docs/perf/public-production-hardware-benchmark-plan.md": (
        "operator plan",
        "arm-server-benchmark-2026-06-05.md",
        "dedicated production-class",
        "not an evidence identity",
    ),
    "docs/perf/throughput-realpath.md": (
        "current benchmark lifecycle reference",
        "scripts/benchmark_throughput_realpath.py",
        ".artifacts/throughput",
        "not a measured result",
    ),
}
ENTITY_HOT_PATH_FACTS = {
    ENTITY_BASELINE_RECORD: (
        "composite historical dossier",
        "97a1902",
        "windows 11",
        "18 logical cores",
        "15.5 gb",
        "python 3.13.7",
        "redis in docker",
        "duckdb",
        "p50/p95/p99 179.29/615.62/936.34 ms",
        "68.57 rps",
        "2000/2000",
        "5b57cf4",
        "p50/p95/p99 165.89/620.51/962.22 ms",
        "70.49 rps",
    ),
    ENTITY_PII_CACHE_RECORD: (
        "220f94c",
        "p50/p95/p99 56.65/233.78/360.97 ms",
        "193.73 rps",
        "2000/2000",
        "-61%",
    ),
    ENTITY_TENANT_CACHE_RECORD: (
        "best-of-3",
        "p50 193.29 -> 113.01 ms",
        "p95 242.42 -> 140.88 ms",
        "p99 288.85 -> 167.14 ms",
        "81.10 -> 138.08 rps",
        "42.13%",
        "open auth",
        "worst after 261.46 ms",
        "best before 288.85 ms",
    ),
}
ENTITY_HOT_PATH_BOUNDARIES = {
    ENTITY_BASELINE_RECORD: (
        "composite dossier",
        "expanded after the original date",
        "profiling overhead",
        "not directly comparable",
        "historical src/serving paths",
        "not current ownership",
        "local-development",
        "not a ci or cross-host benchmark",
        "not a current-code benchmark",
        "production sla",
        "production acceptance",
        "candidate",
    ),
    ENTITY_PII_CACHE_RECORD: (
        "point-in-time",
        "not a stable current baseline",
        "later dossier refresh",
        "962.22 ms",
        "source-stated hypotheses",
        "not proved causes",
        "not a ci or cross-host benchmark",
        "production sla",
        "production acceptance",
        "candidate",
    ),
    ENTITY_TENANT_CACHE_RECORD: (
        "creation-commit date",
        "source has no date field",
        "5b57cf4",
        "aae27bf",
        "exact after-run bytes are not commit-bound",
        "spread above 10%",
        "hardware and dependency versions are not inherited",
        "not a ci or cross-host benchmark",
        "production sla",
        "production acceptance",
        "candidate",
    ),
}
OPENAPI_DIVERGENCE_HEADING = "## Historical OpenAPI contract divergence diagnostic"
OPENAPI_DIVERGENCE_RECORD = "docs/perf/test_openapi_compliance-divergence-2026-04-25.md"
OPENAPI_DIVERGENCE_DATE = "2026-04-25"
OPENAPI_DIVERGENCE_DIGEST = "aeecc15d9d1892259259f9fd49d147939c97a81178c4e36fec03d278eb746c6f"
OPENAPI_DIVERGENCE_FACTS = (
    "python 3.13.7",
    "fastapi 0.128.0",
    "pydantic 2.12.5",
    "starlette 0.50.0",
    "fastapi 0.135.3",
    "fastapi 0.136.1",
    "validationerror",
    "input",
    "ctx",
    "ruling out python 3.13",
    "fastapi-owned",
    "project-owned schemas and paths",
)
OPENAPI_DIVERGENCE_BOUNDARIES = (
    "historical local diagnostic",
    "fastapi-version-specific",
    "not a full python/fastapi/pydantic/starlette compatibility matrix",
    "does not establish runtime api acceptance",
    "production compatibility",
    "an sla",
    "production acceptance",
    "candidate",
)
HISTORICAL_AUTH_BENCH_HEADING = "## Historical authentication performance baseline"
HISTORICAL_AUTH_BENCH_RECORD = "docs/perf/auth-bench-2026-05-26.md"
HISTORICAL_AUTH_BENCH_DATE = "2026-05-26"
HISTORICAL_AUTH_BENCH_DIGEST = "da2ba9f6e47da56bb3d982ed4b435e58c78b602ec20dea1e1e2cb3c272fec9ad"
HISTORICAL_AUTH_BENCH_FACTS = (
    "intel ultra 5 125h",
    "windows 11",
    "python 3.13",
    "bcrypt_rounds=12",
    "n=20",
    "3 trials",
    "hit-last p95 8146.6 ms",
    "miss-all p95 8221.9 ms",
    "rate_limit_rpm=120",
    "5,000 calls",
    "p95 0.006 ms",
    "argon2id",
    "34 ms",
    "0.1 ms",
)
HISTORICAL_AUTH_BENCH_BOUNDARIES = (
    "historical bcrypt",
    "single windows 11 laptop",
    "cool limited",
    "microbenchmark",
    "not a served-api",
    "not a concurrent-load",
    "legacy entries",
    "key_lookup",
    "current indexed argon2id",
    "closure-note comparisons",
    "not a production latency sla",
    "production acceptance",
    "candidate",
)
CI_PERFORMANCE_HEADING = "## CI performance interpretation records"
CI_HARDWARE_GAP_RECORD = "docs/perf/ci-hardware-gap-2026-05-24.md"
CI_USAGE_WRITE_RECORD = "docs/perf/usage-write-bifurcation-2026-07-09.md"
CI_PERFORMANCE_RECORDS = (CI_HARDWARE_GAP_RECORD, CI_USAGE_WRITE_RECORD)
CI_PERFORMANCE_DATES = {
    CI_HARDWARE_GAP_RECORD: "2026-05-24",
    CI_USAGE_WRITE_RECORD: "2026-07-09",
}
CI_PERFORMANCE_DIGESTS = {
    CI_HARDWARE_GAP_RECORD: ("b259d746e4231cea11a974417bfdce88b29d55693889d2d943a4a6c6d4859761"),
    CI_USAGE_WRITE_RECORD: ("db324b94b1903d058a1eca9287a952566a21c629bfcb41980b776bc9f413526e"),
}
CI_PERFORMANCE_FACTS = {
    CI_HARDWARE_GAP_RECORD: (
        "936 ms",
        "167 ms",
        "-82%",
        "68",
        "138 rps",
        "600-800 ms",
        "740-980 ms",
        "1.3x",
        "900 ms",
        "1100 ms",
        "1200 ms",
        "p99 < 200 ms",
    ),
    CI_USAGE_WRITE_RECORD: (
        "29.4",
        "29.1",
        "28.9",
        "1.7%",
        "37.0",
        "46.2",
        "1.5x",
        "10x",
        "1/s",
        "34 ms",
        "31.4 rps",
        "37.9 rps",
        "37.2 rps",
        "background",
        "batch",
    ),
}
CI_PERFORMANCE_BOUNDARIES = {
    CI_HARDWARE_GAP_RECORD: (
        "point-in-time",
        "shared",
        "2-core",
        "4-7 gb",
        "does not prove every later ci tail",
        "does not authorize future threshold relaxation",
        "production latency sla",
        "production acceptance",
        "candidate",
    ),
    CI_USAGE_WRITE_RECORD: (
        "finding n1",
        "runner-speed reading",
        "does not supersede the a03",
        "runner variability",
        "durability",
        "crash",
        "admin read",
        "not billing",
        "not rate limiting",
        "production throughput sla",
        "production acceptance",
        "candidate",
    ),
}
ARM_BENCHMARK_HEADING = "## ARM shared-runner benchmark packet"
ARM_BENCHMARK_RECORD = "docs/perf/arm-server-benchmark-2026-06-05.md"
ARM_REPORT_COMPANION = "docs/perf/arm-benchmark-2026-06-05/arm-benchmark.md"
ARM_HOST_COMPANION = "docs/perf/arm-benchmark-2026-06-05/arm-host-metadata.md"
ARM_JSON_COMPANION = "docs/perf/arm-benchmark-2026-06-05/arm-current.json"
ARM_BENCHMARK_DATE = "2026-06-05"
ARM_PACKET_DIGESTS = {
    ARM_BENCHMARK_RECORD: ("a88427346c891915652a3ba57fc9e018d28628ad58f1d36207f84e1b74a73452"),
    ARM_REPORT_COMPANION: ("7b89d09404487c9dbf05eddf673c8a4c0721e1d3cdc1efd650769b3d9d67056b"),
    ARM_HOST_COMPANION: ("39693a4921e167284f8a4028ca22979c33c62d7438a4caf54d3316a2c13a320e"),
    ARM_JSON_COMPANION: ("68d3398350caf25083882074dc340f1e12b444751e712bac81865cbb04fbdd62"),
}
ARM_BENCHMARK_FACTS = (
    "ubuntu-24.04-arm",
    "neoverse-n2",
    "4 vcpu",
    "15.6 gb",
    "python 3.11.15",
    "dispatch-only",
    "27012731848",
    "60e0f3d",
    "50 users",
    "10/s",
    "60 s",
    "10 s warmup",
    "554 requests",
    "zero failures",
    "37.41 rps",
    "p50 6.0 ms",
    "p95 44.0 ms",
    "p99 150.0 ms",
    "worst entity p50 4.0 ms",
    "worst entity p99 150.0 ms",
)
ARM_BENCHMARK_BOUNDARIES = (
    "shared ci runner",
    "not a dedicated 16-vcpu",
    "no c8g.4xlarge performance claim",
    "duckdb",
    "synthetic",
    "not strictly comparable",
    "not a regression claim",
    "not production-class hardware",
    "not a production latency sla",
    "production acceptance",
    "candidate",
)
CLICKHOUSE_SERVING_HEADING = "## ClickHouse serving-path verification record"
CLICKHOUSE_SERVING_RECORD = "docs/perf/clickhouse-serving-verify-2026-07-02.md"
CLICKHOUSE_SERVING_DATE = "2026-07-02"
CLICKHOUSE_SERVING_DIGEST = "1cb01b6733b624fd6cc71baca714c4e6ff06a55ec2f676a152365a7edae9d530"
CLICKHOUSE_SERVING_FACTS = (
    "adr 0006 phase 1",
    "clickhouse 26.7.1.368",
    "wsl ubuntu 22.04",
    "no docker",
    "60/60",
    "orders_v2=13",
    "pipeline_events=73",
    "2799.65",
    "top-3 products",
    "3279.57",
    "exactly 1 row",
    "api_ready",
    "0 dispatcher/scan errors",
    "no false positives",
)
CLICKHOUSE_SERVING_BOUNDARIES = (
    "single-node",
    "single-writer demo profile",
    "multi-writer version ordering",
    "auth disabled",
    "placeholder-unhealthy",
    "no equivalent p50/p95",
    "behavior",
    "not a latency figure",
    "phase 2 pii-governance",
    "not a supersession",
    "production acceptance",
    "candidate",
)
CLICKHOUSE_PII_HEADING = "## ClickHouse PII-governance verification records"
CLICKHOUSE_PII_0702_RECORD = "docs/perf/vault-pii-governance-verify-2026-07-02.md"
CLICKHOUSE_PII_0703_RECORD = "docs/perf/vault-pii-governance-verify-2026-07-03.md"
CLICKHOUSE_PII_DATES = {
    CLICKHOUSE_PII_0702_RECORD: "2026-07-02",
    CLICKHOUSE_PII_0703_RECORD: "2026-07-03",
}
CLICKHOUSE_PII_DIGESTS = {
    CLICKHOUSE_PII_0702_RECORD: (
        "9febe54c7bd99b88afb0138e7d85e2a138c9b77a6b1e9f758f4ab2e4cdc294fe"
    ),
    CLICKHOUSE_PII_0703_RECORD: (
        "ad27d5ea81c02e363fce41dea460486b74690c7a6e581bc80064dcc3299eb8ac"
    ),
}
CLICKHOUSE_PII_0702_FACTS = (
    "26.7.1.368",
    "32/32",
    "2,000",
    "msk 800",
    "dxb 200",
    "safe subquery",
    "idempotent",
)
CLICKHOUSE_PII_0703_FACTS = (
    "26.7.1.492",
    "29/29",
    "0 fail",
    "0 warn",
    "2,500",
    "msk 2,190",
    "dxb 60",
    "current",
)
CLICKHOUSE_PII_0702_BOUNDARIES = (
    "historical",
    "standalone",
    "wsl",
    "synthetic",
    "postgresql",
    "promoted cdc",
    "production admin identity",
    "external penetration test",
    "production acceptance",
    "candidate",
)
CLICKHOUSE_PII_0703_BOUNDARIES = (
    "current clickhouse",
    "standalone",
    "synthetic",
    "not promoted cdc",
    "`default` admin",
    "production identity split",
    "postgresql",
    "cross-engine",
    "kubernetes",
    "external penetration test",
    "production acceptance",
    "candidate",
)
POSTGRESQL_PII_HEADING = "## PostgreSQL PII-governance verification records"
POSTGRESQL_PII_0702_RECORD = "docs/perf/vault-pii-governance-pg-verify-2026-07-02.md"
POSTGRESQL_PII_0703_RECORD = "docs/perf/vault-pii-governance-pg-verify-2026-07-03.md"
POSTGRESQL_PII_DATES = {
    POSTGRESQL_PII_0702_RECORD: "2026-07-02",
    POSTGRESQL_PII_0703_RECORD: "2026-07-03",
}
POSTGRESQL_PII_DIGESTS = {
    POSTGRESQL_PII_0702_RECORD: (
        "1d6f3ebe183ce098d2ad49b519ad46171cb5d9f6bae9cc5edbdc1d85a428266b"
    ),
    POSTGRESQL_PII_0703_RECORD: (
        "f4234235d1c28b37e72389e37521c0f46c13a428a7691d77544cf8f6d3dbc55e"
    ),
}
POSTGRESQL_PII_0702_FACTS = (
    "postgresql 17.5",
    "33/33",
    "10-row",
    "msk 8",
    "dxb 2",
    "column acl",
    "default-deny",
    "four-file idempotent",
)
POSTGRESQL_PII_0703_FACTS = (
    "postgresql 17.5",
    "33/33",
    "0 fail",
    "0 warn",
    "10-row",
    "msk 8",
    "dxb 2",
    "`1c__msk`",
    "`pg_ops__msk`",
    "`mp__msk`",
    "four governance files",
)
POSTGRESQL_PII_BOUNDARIES = (
    "standalone windows",
    "deterministic demo seed",
    "not promoted cdc",
    "admin/owner sees all",
    "production identity split",
    "dbt marts",
    "`bv_order_canonical_mat`",
    "clickhouse",
    "cross-engine",
    "kubernetes",
    "external penetration test",
    "production sla",
    "production acceptance",
    "candidate",
)
POSTGRESQL_RUNTIME_HEADING = "## PostgreSQL control-plane and canonical-order verification records"
CONTROL_PLANE_PG_RECORD = "docs/perf/control-plane-pg-verify-2026-07-03.md"
BV_ORDER_CANONICAL_PG_RECORD = "docs/perf/bv-order-canonical-pg-smoke-2026-07-06.md"
POSTGRESQL_RUNTIME_DATES = {
    CONTROL_PLANE_PG_RECORD: "2026-07-03",
    BV_ORDER_CANONICAL_PG_RECORD: "2026-07-06",
}
POSTGRESQL_RUNTIME_DIGESTS = {
    CONTROL_PLANE_PG_RECORD: ("1fed01fd91d09548d44342a78d00093d0e3a41cf8c831ed91d8c9ce85e69260c"),
    BV_ORDER_CANONICAL_PG_RECORD: (
        "4844cb202105780b4466e19f0fca15f2d71e6a64ed46dbd7cda071d1aa2dfd7a"
    ),
}
CONTROL_PLANE_PG_FACTS = (
    "postgresql 17.5",
    "31/31",
    "19.45s",
    "psycopg 3.3.4",
    "8 threads",
    "4 threads",
    "restart re-drive",
    "outbox",
    "alert-tick",
    "two app boots",
    "api_usage",
)
CONTROL_PLANE_PG_BOUNDARIES = (
    "standalone windows",
    "trust auth",
    "no pooling",
    "one connection per method",
    "not a production deployment",
    "not an sla",
    "production acceptance",
    "candidate",
)
BV_ORDER_CANONICAL_PG_FACTS = (
    "postgresql 16.14",
    "17/17",
    "0 fail",
    "8 deterministic orders",
    "197166.67",
    "latest-wins",
    "soft-delete",
    "7 of 8",
    "5%",
    "20%",
)
BV_ORDER_CANONICAL_PG_BOUNDARIES = (
    "mac",
    "colima/docker",
    "standalone seed smoke",
    "not promoted cdc",
    "cdc-to-serving",
    "not integrated with the control plane",
    "production acceptance",
    "candidate",
)
NL_SQL_EVALUATION_HEADING = "## NL-to-SQL evaluation records"
RULE_BASED_NL_SQL_RECORD = "docs/perf/nl-sql-eval-2026-07-01.md"
SONNET_5_NL_SQL_RECORD = "docs/perf/nl-sql-eval-sonnet5-2026-07-01.md"
NL_SQL_EVALUATION_DATES = {
    RULE_BASED_NL_SQL_RECORD: "2026-07-01",
    SONNET_5_NL_SQL_RECORD: "2026-07-01",
}
NL_SQL_EVALUATION_DIGESTS = {
    RULE_BASED_NL_SQL_RECORD: ("c1de34750781650ed249c50feb66451cec031ab17e8837aebc66e67d644921a8"),
    SONNET_5_NL_SQL_RECORD: ("472cb424b3866f675817fd8f3e1e7b1d887f98675926ff7472c2d97a2df23e8a"),
}
RULE_BASED_NL_SQL_FACTS = (
    "rule-based",
    "shipped default",
    "27.8%",
    "5/18",
    "62.5%",
    "5/8",
    "0.0%",
    "0/10",
)
SONNET_5_NL_SQL_FACTS = (
    "sonnet 5",
    "gracekelly",
    "opt-in",
    "100.0%",
    "18/18",
    "8/8",
    "10/10",
    "single generation pass",
    "no repairs",
    "11-24 s",
    "4.5 min",
)
RULE_BASED_NL_SQL_BOUNDARIES = (
    "direct translator",
    "time windows",
    "no-op",
    "pii deny-gate",
    "88.9%",
    "companion record",
    "not a production",
    "candidate",
)
SONNET_5_NL_SQL_BOUNDARIES = (
    "18 curated demo questions",
    "not a benchmark",
    "live and non-deterministic",
    "not pinned in ci",
    "direct translator",
    "pii deny-gate",
    "not a production",
    "candidate",
)
HISTORICAL_STREAMING_HOP_HEADING = "## Historical streaming-hop freshness record"
HISTORICAL_STREAMING_HOP_RECORD = "docs/perf/freshness-realpath-2026-06-30.md"
HISTORICAL_STREAMING_HOP_DATE = "2026-06-30"
HISTORICAL_STREAMING_HOP_DIGEST = "8ee9d878e24012530ee654fd75cd1f6338e96d24fdedb5f60a1dca2e7cfb408b"
HISTORICAL_STREAMING_HOP_FACTS = (
    "deproject-mac",
    "macos 13.7.8",
    "intel i5-7500",
    "colima",
    "6 gib / 4 cpu",
    "flink 2.2.1-java17",
    "kafka 7.7.0",
    "python 3.11.15",
    "n=30",
    "0 misses",
    "p50 2.50 s",
    "p95 10.11 s",
    "p99 15.42 s",
    "mean 3.33 s",
)
HISTORICAL_STREAMING_HOP_BOUNDARIES = (
    "historical streaming-hop-only",
    "orders.raw",
    "events.validated",
    "does not include the serving bridge",
    "clickhouse",
    "redis",
    "api",
    "not event-to-metric",
    "s8",
    "current full-path claim owner",
    "not a supersession",
    "single-node mac/colima",
    "not an sla",
    "production acceptance",
    "candidate",
)
CURRENT_FRESHNESS_HEADING = "## Current freshness evidence records"
REAL_PATH_FRESHNESS_RECORD = "docs/perf/freshness-e2e-realpath.md"
DEMO_FRESHNESS_RECORD = "docs/archive/performance/freshness-benchmark-2026-06-06.md"
CURRENT_FRESHNESS_DATES = {
    REAL_PATH_FRESHNESS_RECORD: "2026-07-09",
    DEMO_FRESHNESS_RECORD: "2026-06-06",
}
CURRENT_FRESHNESS_DIGESTS = {
    REAL_PATH_FRESHNESS_RECORD: (
        "a7715b090f1593924a5503d18ed932c92681f874083a99625f2f0f9fa7050c88"
    ),
    DEMO_FRESHNESS_RECORD: ("371f62ad7ecc64954ba42fe5ae24b2c30615429e2cf53bca6d88c402fd449f2d"),
}
REAL_PATH_FRESHNESS_BOUNDARIES = (
    "single mac/colima stand",
    "revenue metric",
    "one miss",
    "not an sla",
    "demo shortcut",
    "production acceptance",
)
DEMO_FRESHNESS_BOUNDARIES = (
    "in-process duckdb shortcut",
    "pre-s7",
    "windows",
    "fakeredis",
    "kafka",
    "flink",
    "bridge",
    "clickhouse",
    "current production invalidation wiring",
    "production acceptance",
)
E4_REPLICA_HEADING = "## E4 replica-correctness evidence records"
E4_TWO_POD_RECORD = "docs/perf/e4-2pod-topology-2026-07-09.md"
E4_CHECK4_RECORD = "docs/perf/e4-check4-alert-single-page-2026-07-17.md"
E4_REPLICA_DATES = {
    E4_TWO_POD_RECORD: "2026-07-09",
    E4_CHECK4_RECORD: "2026-07-17",
}
E4_REPLICA_DIGESTS = {
    E4_TWO_POD_RECORD: ("39bf695eb3e7346bfc18acdb1487dfd2e8bc394ebe045b4e7bf9df721b1959ae"),
    E4_CHECK4_RECORD: ("4af1aaf1963bd1747de678a28d6d08de6733f15ef7e44cb01216ab425cf76c3a"),
}
E4_TWO_POD_BOUNDARIES = (
    "checks 1-2",
    "two ready pods",
    "postgres",
    "8 round-robin",
    "explicit a-to-b",
    "does not claim checks 3-4",
    "hq-demo",
    "production acceptance",
)
E4_CHECK4_BOUNDARIES = (
    "checks 1-4 pass",
    "exactly one delivery",
    "exactly one alert",
    "agentflow-staging",
    "local pre-push",
    "httpbin",
    "durable persistence",
    "production acceptance",
)
HISTORICAL_E4_HEADING = "## Historical E4 intermediate replica-correctness records"
E4_REPLICA_TOPOLOGY_RECORD = "docs/perf/e4-replica-topology-2026-07-11.md"
E4_CHECK3_RECORD = "docs/perf/e4-check3-exactly-one-delivery-2026-07-16.md"
HISTORICAL_E4_DATES = {
    E4_REPLICA_TOPOLOGY_RECORD: "2026-07-11",
    E4_CHECK3_RECORD: "2026-07-16",
}
HISTORICAL_E4_DIGESTS = {
    E4_REPLICA_TOPOLOGY_RECORD: (
        "dcab8c990386afa3dff065fb07be2195cc40bb20d0328c0f1441b2d7c148a571"
    ),
    E4_CHECK3_RECORD: ("6bf8d6773997e69d1634eddcb3a7fdf2aa881a404af360e7d762ed22ca283bf8"),
}
E4_REPLICA_TOPOLOGY_BOUNDARIES = (
    "historical",
    "intermediate",
    "checks 1-2",
    "agentflow-staging",
    "2026-07-06",
    "9935bdc",
    "does not claim checks 3-4",
    "exactly-one delivery",
    "alert single-page",
    "hq-demo",
    "a-to-b",
    "production acceptance",
    "candidate",
)
E4_CHECK3_BOUNDARIES = (
    "historical",
    "intermediate",
    "checks 1-3 pass",
    "exactly one delivery",
    "replica-e4-858cce874ac04494",
    "22fbae6",
    "delivery half",
    "does not claim check 4",
    "alert single-page",
    "not a current status owner",
    "production acceptance",
    "candidate",
)
CURRENT_ENDURANCE_SCALE_HEADING = "## Current endurance and scale evidence records"
S11_SOAK_RECORD = "docs/perf/soak-s11-2026-07-10.md"
S13_SCALE_RECORD = "docs/perf/scale-own-data-2026-07-11.md"
RSS_REVERIFY_RECORD = "docs/perf/rss-reverify-183-2026-07-11.md"
CURRENT_ENDURANCE_SCALE_DATES = {
    S11_SOAK_RECORD: "2026-07-10",
    S13_SCALE_RECORD: "2026-07-11",
}
CURRENT_ENDURANCE_SCALE_DIGESTS = {
    S11_SOAK_RECORD: ("040e3f2c473b1a52426f0d4e77cefa2dc26e35fe3db09d1c453697eb9f1eaf91"),
    S13_SCALE_RECORD: ("cebea4fe43c31380f589cf7e5dcf8706ef20314f1f2d104cb6ed06c8c52c6e5b"),
}
S11_STATUS_CLAIM = "4 h endurance soak (real path + API reads)"
S11_STATUS_RESULT = (
    "bounded lag (peak 2 915 → 0), bridge RSS/FD flat, one faulted batch "
    "replayed exactly-once by the journal guard, **zero cache drift**"
)
S13_STATUS_CLAIM = "At-scale on own data (S13)"
S13_STATUS_RESULT = (
    "**51.2 M rows / 2.87 M orders / 4 years of legend history**, analyst "
    "queries 20–730 ms, all 17 at-scale correctness checks pass"
)
S11_SOAK_BOUNDARIES = (
    "4 h",
    "real-path",
    "api-read",
    "deproject-mac",
    "colima",
    "bounded",
    "2 915",
    "journal guard",
    "exactly-once",
    "zero cache drift",
    "1 540 429 855.37",
    "682 679",
    "rss-reverify-183-2026-07-11",
    "scoped partial supersession",
    "api rss",
    "175 mb",
    "1.67 gb",
    "not a production sla",
    "production acceptance",
    "candidate",
)
S13_SCALE_BOUNDARIES = (
    "51.2 m rows",
    "2.87 m orders",
    "4 years",
    "20–730 ms",
    "17 at-scale",
    "in-database",
    "single-node",
    "laptop-class",
    "not streaming",
    "demo-scale",
    "production sla",
    "production acceptance",
    "candidate",
)
RSS_REVERIFY_HEADING = "## API RSS fix re-verification record"
RSS_REVERIFY_DATE = "2026-07-11"
RSS_REVERIFY_DIGEST = "ad0b57d79eee5fdaf7b00f435647c4bacd5a7ee2ae2d1a147f43394e7e5b414b"
RSS_REVERIFY_RESULT_FACTS = (
    "97 min",
    "98 one-minute samples",
    "1.371 m",
    "1.732 m",
    "77.3 mb → 100.9 mb",
    "+7.5 mb/h",
    "+3.2 mb/h",
    "q4 below q3",
    "185 mb",
    "reclaimed",
    "149–152",
    "1 149 / 1 149",
    "0 errors",
    "issue #183",
    "closed live",
)
RSS_REVERIFY_BOUNDARIES = (
    "scoped partial supersession",
    "api rss leak finding only",
    "full-path endurance remains s11-owned",
    "flink hop was bypassed",
    "events.validated",
    "97-minute",
    "not a four-hour",
    "not a production sla",
    "production acceptance",
    "candidate",
)
CURRENT_S10_THROUGHPUT_HEADING = "## Current S10 throughput evidence records"
S10_BURST_BASELINE_RECORD = "docs/archive/performance/throughput-realpath-2026-07-09.md"
S10_PACED_R4_RECORD = "docs/perf/throughput-realpath-paced100-4h-r4-2026-07-19.md"
S10_PACED_R1_RECORD = "docs/perf/throughput-realpath-paced100-4h-2026-07-18.md"
S10_PACED_R3_RECORD = "docs/perf/throughput-realpath-paced100-4h-r3-2026-07-19.md"
S10_Q12_RECORD = "docs/perf/throughput-realpath-q12-2026-07-09.md"
S10_Q13_RECORD = "docs/perf/throughput-realpath-q13-2026-07-09.md"
S10_Q14_RECORD = "docs/perf/throughput-realpath-q14-2026-07-10.md"
S10_100EPS_TRY_RECORD = "docs/perf/throughput-realpath-100eps-try-2026-07-17.md"
S10_PACED_10M_RECORD = "docs/perf/throughput-realpath-paced100-2026-07-17.md"
S10_PACED_1H_RECORD = "docs/perf/throughput-realpath-paced100-1h-2026-07-17.md"
CURRENT_S10_THROUGHPUT_DATES = {
    S10_BURST_BASELINE_RECORD: "2026-07-09",
    S10_PACED_R4_RECORD: "2026-07-19",
}
CURRENT_S10_THROUGHPUT_DIGESTS = {
    S10_BURST_BASELINE_RECORD: ("f029493f3d6cf26c2ecaf527c27d47b17d0869af2e222da12a35e0f54e04292f"),
    S10_PACED_R4_RECORD: ("08027f210934070053de3cdabd3065d7bb0a0dc8d5a9387b77880b45cd6adbda"),
}
S10_INTERMEDIATE_RECORDS = (
    S10_Q12_RECORD,
    S10_Q13_RECORD,
    S10_Q14_RECORD,
    S10_100EPS_TRY_RECORD,
    S10_PACED_10M_RECORD,
    S10_PACED_1H_RECORD,
    S10_PACED_R1_RECORD,
    S10_PACED_R3_RECORD,
)
S10_BASELINE_STATUS_HEADING = "## Proven"
S10_BASELINE_STATUS_CLAIM = "Real-path throughput measured"
S10_BASELINE_STATUS_RESULT = "produce ~700 eps; bridge apply is the ceiling (see below)"
S10_R4_STATUS_HEADING = "## Bridge write-path throughput — drain ceiling measured"
S10_R4_STATUS_CLAIM = "Paced **4 h** @ 100 eps produce (r4)"
S10_R4_STATUS_RESULT = (
    "**99.9 apply / 99.9 flink / 100.0 produce** — 1 440 000 events, "
    "dup = 0, failures = 0, lag 0 → 0, 0 Flink restarts"
)
S10_BURST_BASELINE_BOUNDARIES = (
    "pre-q1.2",
    "canonical s10",
    "burst",
    "400",
    "699",
    "7.97",
    "deproject-mac",
    "colima",
    "later best sustained",
    "current freshness headline",
    "not a direct supersession chain",
    "production sla",
    "production acceptance",
    "candidate",
)
S10_PACED_R4_BOUNDARIES = (
    "four-hour",
    "paced",
    "serving-path",
    "1 440 000",
    "100.0",
    "99.9",
    "produced",
    "delivered",
    "duplicates 0",
    "apply failures 0",
    "1956",
    "484/484",
    "never restarted",
    "current four-hour paced-gate outcome",
    "historical facts remain valid",
    "already-closed serving-path gate",
    "golden full-soak",
    "remains open",
    "blocked_host_capacity",
    "pre-materializer",
    "does not merge",
    "not a direct supersession chain",
    "production acceptance",
    "candidate",
)
HISTORICAL_PACED_4H_HEADING = "## Historical four-hour paced S10 predecessor records"
HISTORICAL_PACED_4H_DATES = {
    S10_PACED_R1_RECORD: "2026-07-18",
    S10_PACED_R3_RECORD: "2026-07-19",
}
HISTORICAL_PACED_4H_DIGESTS = {
    S10_PACED_R1_RECORD: ("c63ead23c4b9992459f8ec3f1f28abe36c68516847464f100d82df960f0b693f"),
    S10_PACED_R3_RECORD: ("f56e80447eb315e93d1cfce60f5a9c1078b9595c8089d0fb18cce0ed21c02247"),
}
S10_PACED_R1_RESULT_FACTS = (
    "2026-07-18t00:23:20z",
    "05:03:25z",
    "05afb32",
    "1 440 000",
    "100.0 eps",
    "1 424 309",
    "84.8 eps",
    "1 132 164",
    "67.4 eps",
    "0 / 292 145",
    "0 → 0",
    "1939",
    "99–100 %",
    "116",
    "exit 127",
    "1 424 309 = 1 132 164 + 292 145",
    "fail",
)
S10_PACED_R3_RESULT_FACTS = (
    "2026-07-19t01:26z",
    "06:07z",
    "05afb32",
    "1 440 000",
    "14 430 s",
    "1 031 462",
    "408 538",
    "100 % of delivered",
    "0 / 0",
    "0 → 0",
    "2015",
    "0 restarts",
    "578/578",
    "4.7 h",
    "2 h 52 m",
    "73 %",
    "formal fail",
)
S10_PACED_R1_BOUNDARIES = (
    "historical",
    "stand disk exhaustion",
    "not an apply-path defect",
    "healthy for about 2.5 h",
    "multi-hour sustained >=100 eps remains open",
    "current four-hour paced-gate outcome only",
    "historical facts remain valid",
    "pre-materializer",
    "golden full-soak",
    "blocked_host_capacity",
    "production sla",
    "production acceptance",
    "candidate",
)
S10_PACED_R3_BOUNDARIES = (
    "historical",
    "harness delivery-accounting failure",
    "408 538 lost client-side",
    "serving path processed every delivered event exactly once",
    "16 s broker fencing",
    "actual load for 2 h 52 m",
    "multi-hour sustained >=100 eps remains open",
    "current four-hour paced-gate outcome only",
    "historical facts remain valid",
    "pre-materializer",
    "golden full-soak",
    "blocked_host_capacity",
    "production sla",
    "production acceptance",
    "candidate",
)
Q12_PREDECESSOR_HEADING = "## Q1.2 predecessor S10 throughput record"
Q12_PREDECESSOR_DATE = "2026-07-09"
Q12_PREDECESSOR_DIGEST = "a9d6ff046f678ec428ea437676d8007c1fa23de35e46147aac451aff4fcb54c3"
Q12_PREDECESSOR_RESULT_FACTS = (
    "2026-07-09t18:00:02+00:00",
    "deproject-mac",
    "5a7ed6f",
    "skip_local_store",
    "no scratch duckdb",
    "colima",
    "6 gib",
    "4 cpu",
    "400-event",
    "unpaced",
    "warm canonical",
    "217 eps",
    "flink hop = bridge apply = 11.4 eps",
    "400 / 0 / 0",
    "35.2 s",
    "213",
    "about 1.4x",
    ">=80 target missed",
    "api not started",
)
Q12_PREDECESSOR_BOUNDARIES = (
    "historical intermediate",
    "q1.2",
    "root of the narrow",
    "does not supersede",
    "pre-q1.2 baseline",
    "cold run was noisy",
    "not a 10x win",
    "low tens",
    "does not claim hundreds",
    "host/driver variance",
    "not the product ceiling",
    "400-event",
    "q1.3",
    "later apply-path outcome only",
    "sustained",
    "production sla",
    "production acceptance",
    "golden full-soak",
    "remains open",
    "candidate",
)
Q13_Q14_INTERMEDIATE_S10_HEADING = "## Q1.3/Q1.4 intermediate S10 throughput records"
Q13_Q14_INTERMEDIATE_S10_DATES = {
    S10_Q13_RECORD: "2026-07-09",
    S10_Q14_RECORD: "2026-07-10",
}
Q13_Q14_INTERMEDIATE_S10_DIGESTS = {
    S10_Q13_RECORD: ("5671f60feac077d8fe9684f3c75e0a315edcb44676a97725af936db39ca0c96f"),
    S10_Q14_RECORD: ("6c131f1887c219e186e7f709f547935596091da4cfddffc2ad3d4237552a8f90"),
}
Q13_Q14_NON_SUPERSESSION_RECORDS = (
    S10_BURST_BASELINE_RECORD,
    S10_100EPS_TRY_RECORD,
    S10_PACED_10M_RECORD,
    S10_PACED_1H_RECORD,
    S10_PACED_R1_RECORD,
    S10_PACED_R3_RECORD,
    S10_PACED_R4_RECORD,
)
S10_Q13_RESULT_FACTS = (
    "2026-07-09t18:08z",
    "deproject-mac",
    "q13-ch-batch-apply",
    "88a3de4",
    "5bd2189",
    "clickhouse-only",
    "no duckdb",
    "unpaced",
    "400-event",
    "647",
    "flink hop = bridge apply = 22.9",
    "failures 0",
    "17.5 s",
    "218",
    "2.9x",
    "2.0x",
    ">=80",
    "missed",
)
S10_Q14_RESULT_FACTS = (
    "2026-07-10",
    "deproject-mac",
    "colima",
    "6 gib",
    "4 cpu",
    "macos 13.7.8",
    "intel",
    "one flink taskmanager",
    "13a242d",
    "clickhouse-only",
    "no duckdb",
    "unpaced",
    "400-event",
    "376",
    "flink hop = bridge apply = 87.4",
    "0 / 0",
    "4.58 s",
    "peak lag 0",
    "3.8x",
    "11x",
    ">=80",
    "met",
    "10 non-empty",
    "800",
    "mean 80",
    "p50 >32",
)
S10_Q13_BOUNDARIES = (
    "intermediate",
    "optimization",
    "sustained-rate",
    "production sla",
    "production acceptance",
    "current-best",
    "400-event",
    "apply-path",
    "q1.2",
    "q1.4",
    "candidate",
    "golden full-soak",
    "remains open",
)
S10_Q14_BOUNDARIES = (
    "docs/status.md",
    "readme",
    "400-event",
    "intermediate",
    "broader s10",
    "sustained",
    ">=100",
    "multi-hour",
    "production sla",
    "production acceptance",
    "107.3",
    "10m",
    "1h",
    "r4",
    "not direct supersession",
    "candidate",
    "golden full-soak",
    "remains open",
)
PACED_10M_1H_HEADING = "## Paced 10-minute and one-hour S10 throughput records"
PACED_10M_1H_DATES = {
    S10_PACED_10M_RECORD: "2026-07-17",
    S10_PACED_1H_RECORD: "2026-07-17",
}
PACED_10M_1H_DIGESTS = {
    S10_PACED_10M_RECORD: ("3d8ebc375f899b99b156dbfc57010eaade2a5c44516cbe5b693d2e7ac14d175f"),
    S10_PACED_1H_RECORD: ("3b6db0774dc305d683b8fec256618f688e3d06a6a6e0fad3bfbce8b523b47361"),
}
PACED_10M_1H_OTHER_RECORDS = (
    S10_BURST_BASELINE_RECORD,
    S10_Q13_RECORD,
    S10_Q14_RECORD,
    S10_100EPS_TRY_RECORD,
    S10_PACED_R1_RECORD,
    S10_PACED_R3_RECORD,
    S10_PACED_R4_RECORD,
)
PACED_10M_STATUS_STEP = "Paced 10 min @ 100 eps produce"
PACED_10M_STATUS_RESULT = "**96.5 apply / 97.1 flink / 100 produce**"
PACED_1H_STATUS_STEP = "Paced **1 h** @ 100 eps produce"
PACED_1H_STATUS_RESULT = "**99.5 apply / 99.5 flink / 100 produce**"
S10_PACED_10M_RESULT_FACTS = (
    "2026-07-16t22:52",
    "23:03z",
    "deproject-mac",
    "colima",
    "6 gib",
    "4 cpu",
    "4631299",
    "one flink taskmanager",
    "100.0 eps",
    "60 000",
    "600.0 s",
    "97.1 eps",
    "96.5 eps",
    "59 654",
    "618.1 s",
    "0 / 0",
    "0 → 0",
    "1037",
    "pass",
)
S10_PACED_1H_RESULT_FACTS = (
    "2026-07-16t23:30z",
    "2026-07-17t00:30z",
    "deproject-mac",
    "colima",
    "6 gib",
    "4 cpu",
    "b5d9ce0",
    "one flink taskmanager",
    "100.0 eps",
    "360 000",
    "3600.0 s",
    "99.5 eps",
    "3617 s",
    "0 / 0",
    "0 → 0",
    "1679",
    "pass",
)
S10_PACED_10M_BOUNDARIES = (
    "paced",
    "10-minute",
    "first paced",
    "duration milestone",
    "not a supersession chain",
    "historical facts remain valid",
    "does not claim all 60 000 applied",
    "multi-hour",
    "four-hour r4",
    "pre-materializer",
    "golden full-soak",
    "blocked_host_capacity",
    "production sla",
    "production acceptance",
    "candidate",
)
S10_PACED_1H_BOUNDARIES = (
    "paced",
    "one continuous hour",
    "duration milestone",
    "not a supersession chain",
    "historical facts remain valid",
    "not multi-hour",
    "four-hour r4",
    "pre-materializer",
    "golden full-soak",
    "blocked_host_capacity",
    "production sla",
    "production acceptance",
    "candidate",
)
FINITE_100EPS_DRAIN_HEADING = "## Finite 2000-event S10 drain record"
FINITE_100EPS_DRAIN_DATE = "2026-07-17"
FINITE_100EPS_DRAIN_DIGEST = "6266c36fd694fc9b447f1cfbc2e177fb9c750f4aff6409102dc1ccdffb8172b7"
FINITE_100EPS_DRAIN_OTHER_RECORDS = (
    S10_BURST_BASELINE_RECORD,
    S10_Q13_RECORD,
    S10_Q14_RECORD,
    S10_PACED_10M_RECORD,
    S10_PACED_1H_RECORD,
    S10_PACED_R1_RECORD,
    S10_PACED_R3_RECORD,
    S10_PACED_R4_RECORD,
)
FINITE_100EPS_STATUS_STEP = "Stretch try — 2000-event drain on same Mac class"
FINITE_100EPS_STATUS_RESULT = "**107.3 eps**"
FINITE_100EPS_DRAIN_RESULT_FACTS = (
    "2026-07-16t22:28–22:29z",
    "deproject-mac",
    "colima",
    "6 gib",
    "4 cpu",
    "macos 13.7.8",
    "intel",
    "88c9804",
    "clickhouse-only",
    "one flink taskmanager",
    "finite",
    "2000-event",
    "produce 2216 eps",
    "flink hop = bridge apply = 107.3 eps",
    "0 / 0",
    "18.65 s",
    "187",
    ">=100",
    "single drain window",
)
FINITE_100EPS_DRAIN_BOUNDARIES = (
    "finite produce + catch-up drain",
    "not a sustained",
    "paced-ingress",
    "multi-hour",
    "production sla",
    "production acceptance",
    "does not supersede",
    "q1.4",
    "10-minute",
    "one-hour",
    "four-hour r4",
    "different windows",
    "historical facts remain valid",
    "pre-materializer",
    "clickhouse-only",
    "golden full-soak",
    "blocked_host_capacity",
    "candidate",
)
GOLDEN_ACCEPTANCE_DIGESTS = {
    "docs/perf/golden-flink-submission-2026-07-30.md": (
        "f1494f0f7664816e8be01151af2406e82bcab9a4348af30839dcead039112f21"
    ),
    "docs/perf/golden-operator-acceptance-2026-07-30.md": (
        "31ba968526adab529b93b55440aab3d5e0037c60f83d44ebb5bebfbeeedaa861"
    ),
    "docs/perf/live-iceberg-materialization-2026-08-01.md": (
        "a155f2f10b57acd00d5d74f80c36afdd04a3a501513e3e3dcb806a4c65b0ecc2"
    ),
    "docs/perf/full-lake-to-serving-e2e-2026-08-01.md": (
        "0ffa18a977c4ee3ac96f02a0b57046c26197b9c3796cc88ba672b477e204312b"
    ),
}
GOLDEN_ACCEPTANCE_DATE = "2026-07-30"
LAKE_TO_SERVING_DATE = "2026-08-01"
SUBMISSION_RECORD = "docs/perf/golden-flink-submission-2026-07-30.md"
OPERATOR_RECORD = "docs/perf/golden-operator-acceptance-2026-07-30.md"
ICEBERG_RECORD = "docs/perf/live-iceberg-materialization-2026-08-01.md"
LAKE_TO_SERVING_RECORD = "docs/perf/full-lake-to-serving-e2e-2026-08-01.md"
SUBMISSION_COMMIT = "ca82be5a84a58ae37dd71ef80e785deb8e70dcad"
OPERATOR_COMMIT = "36ed1ecc250ac6c82ccc6f27de1b76a301b17a41"
ICEBERG_RUNTIME = "ed03fc47"
OPERATOR_STAND = "36ed1ec"
GOLDEN_ACCEPTANCE_DATES = {
    SUBMISSION_RECORD: GOLDEN_ACCEPTANCE_DATE,
    OPERATOR_RECORD: GOLDEN_ACCEPTANCE_DATE,
    ICEBERG_RECORD: LAKE_TO_SERVING_DATE,
    LAKE_TO_SERVING_RECORD: LAKE_TO_SERVING_DATE,
}
UNCLAIMED_BOUNDARIES = (
    "full lake-to-serving production e2e",
    "restore/replay",
    "fresh 4h soak plus rollback after traffic",
    "external penetration test",
    "production acceptance",
)
ICEBERG_UNCLAIMED_BOUNDARIES = (
    "kafka source",
    "clickhouse/api",
    "restore/replay",
    "fresh soak or rollback",
    "external penetration test",
    "npm approval",
    "operator acceptance of ed03fc47",
    "production acceptance",
)
LAKE_TO_SERVING_UNCLAIMED_BOUNDARIES = (
    "same-sha operator acceptance",
    "multi-tenant acceptance",
    "restore/replay",
    "fresh soak or rollback",
    "external penetration test",
    "npm approval",
    "production acceptance",
)
CHECKPOINT_READINESS_HEADING = "## Checkpoint and readiness acceptance records"
CHECKPOINT_RECORD = "docs/perf/checkpoint-restore-replay-2026-08-02.md"
READINESS_RECORD = "docs/perf/ready-baselined-checkpoint-hold-2026-08-03.md"
CHECKPOINT_BLOCKER_RECORD = "docs/perf/checkpoint-restore-replay-capacity-blocker-2026-08-01.md"
CANARY_TRAFFIC_RECORD = "docs/perf/golden-4h-soak-canary-failure-2026-08-02.md"
CHECKPOINT_DATE = "2026-08-02"
READINESS_DATE = "2026-08-03"
CHECKPOINT_RUNTIME = "ed03fc47"
CHECKPOINT_TTL_SECONDS = "565"
READINESS_HOLD_SECONDS = "930"
READINESS_COMPLETED_FROM = "7675"
READINESS_COMPLETED_TO = "8614"
STARTUP_FAILURE_CAUSE = "NOT_ALL_REQUIRED_TASKS_RUNNING"
CHECKPOINT_READINESS_DATES = {
    CHECKPOINT_RECORD: CHECKPOINT_DATE,
    READINESS_RECORD: READINESS_DATE,
}
CHECKPOINT_READINESS_DIGESTS = {
    CHECKPOINT_RECORD: ("310e71a056393b6f174d2138438b47a69ea7421ee69c41076da23ee64ef65161"),
    READINESS_RECORD: ("183d001e511a6e333edde00d5d738785d8f35a4d33aa5c602195116275659952"),
}
CHECKPOINT_BLOCKER_DIGEST = "b1288e175d29909f2599d1802a24968098e196851168ff9c032cd21697e0a944"
CHECKPOINT_UNCLAIMED_BOUNDARIES = (
    "four-hour soak",
    "helm rollback",
    "same-sha",
    "external penetration",
    "npm",
    "production acceptance",
)
READINESS_UNCLAIMED_BOUNDARIES = (
    "canary2",
    "four-hour soak",
    "rollback",
    "external penetration",
    "production acceptance",
)
F10_HEADING = "## F-10 rollback and soak-capacity records (2026-08-23)"
ROLLBACK_RECORD = "corrected-rollback-pair-runtime-20260823-01.md"
SOAK_CAPACITY_RECORD = "ci-soak-f02-capacity-decision-20260823-01.md"
PROJECT_CLOSURE = ROOT / "docs" / "PROJECT_CLOSURE.md"
F10_DATE = "2026-08-23"
F10_DATES = {
    ROLLBACK_RECORD: F10_DATE,
    SOAK_CAPACITY_RECORD: F10_DATE,
}
F10_DIGESTS = {
    ROLLBACK_RECORD: ("fc963bd0062a5b41ca13edfd640df0f497fcde8d8030ff1d23387980c6e84fae"),
    SOAK_CAPACITY_RECORD: ("f6e3f906f449816d4fb7a583a4b64ac724c56be794203837608ddbd6f43d3fe9"),
}
F10_SHARED_UNCLAIMED_BOUNDARIES = (
    "fresh four-hour soak plus rollback after traffic",
    "production acceptance",
    "deploy",
    "publication",
)
KIND_SOAK_HEADING = "## Kind-residual canary and latest soak records"
KIND_RESIDUAL_RECORD = "docs/perf/golden-4h-canary2-fix4-kind-residual-pass-2026-08-07.md"
SOAK_05_RECORD = "docs/perf/golden-4h-soak-05-failure-2026-08-08.md"
SOAK_START_RECORD = "docs/perf/golden-4h-soak-start-2026-08-07.md"
KIND_RESIDUAL_DATE = "2026-08-07"
SOAK_05_DATE = "2026-08-08"
KIND_SOAK_DATES = {
    KIND_RESIDUAL_RECORD: KIND_RESIDUAL_DATE,
    SOAK_05_RECORD: SOAK_05_DATE,
}
KIND_SOAK_DIGESTS = {
    KIND_RESIDUAL_RECORD: ("86715d0b29a36f2d5669099e6b85aeceb3abadce7fab7d82f239bf6062f9c1e9"),
    SOAK_05_RECORD: ("30c95061ce0596aeb9612027f47919a9f4f4e22a168a3f25ff70dee7a465a202"),
}
SOAK_START_DIGEST = "cfec64254a5d35f7d3124441ad20784a81b69b3907a27be64cf2062fbb7251ec"
CANARY_TRAFFIC_DIGEST = "fa9460c0c7af678546680c6a9889780fc51b4abf492025878daeee5648b30adc"
KIND_RESIDUAL_UNCLAIMED_BOUNDARIES = (
    "dual-mean >=90",
    "four-hour soak",
    "helm rollback",
    "production acceptance",
)
SOAK_UNCLAIMED_BOUNDARIES = (
    "soak pass",
    "dual-mean pass",
    "rollback pass",
    "production acceptance",
)
SOAK_RCA_HEADING = "## Golden soak cross-run causal analysis"
SOAK_RCA_RECORD = "docs/perf/golden-4h-soak-failures-01-05-rca-2026-08-09.md"
SOAK_RCA_DATE = "2026-08-09"
SOAK_RCA_DIGEST = "3f501d06bd85e6c1b38d34767089b57f5369bff8d6081f2bc90306868a4ac9c3"
SOAK_RCA_FACTS = (
    "read-only",
    "five consumed soak attempts",
    "-01",
    "-05",
    "no soak pass",
    "dual_mean_90",
    "not started",
    "unresolved_flink_terminal_failure",
    "0/2",
    "container-runtime",
    "kafka data loss",
    "1,440,000/1,440,000",
    "99.99979",
    "guest-clock backward jumps",
)
SOAK_RCA_BOUNDARIES = (
    "complementary",
    "not a supersession",
    "clock jump alone",
    "producer failure",
    "kafka failure",
    "oom",
    "verifier load",
    "pod-topology failure",
    "one exact flink exception",
    "post-failure recovery",
    "consumed",
    "does not authorize",
    "rerun",
    "live remediation",
    "helm rollback",
    "production elevation",
    "candidate",
)
HISTORICAL_CANARY_SOAK_HEADING = "## Historical canary-failure and soak-start records"
RESOURCE_BLOCKER_RECORD = "docs/perf/golden-4h-soak-rollback-resource-blocker-2026-08-01.md"
CANARY_TRAFFIC_DATE = "2026-08-02"
SOAK_START_DATE = "2026-08-07"
HISTORICAL_CANARY_SOAK_DATES = {
    CANARY_TRAFFIC_RECORD: CANARY_TRAFFIC_DATE,
    SOAK_START_RECORD: SOAK_START_DATE,
}
HISTORICAL_CANARY_SOAK_DIGESTS = {
    CANARY_TRAFFIC_RECORD: CANARY_TRAFFIC_DIGEST,
    SOAK_START_RECORD: SOAK_START_DIGEST,
}
RESOURCE_BLOCKER_DIGEST = "3504c46afc276d5725576bcc0a1caa2415cf02e6b6bb3febe8e9fc22a070b8d5"
CANARY_FAILURE_UNCLAIMED_BOUNDARIES = (
    "four-hour soak",
    "rollback",
    "production acceptance",
)
SOAK_START_UNCLAIMED_BOUNDARIES = (
    "soak pass",
    "mean >=90",
    "rollback pass",
    "production acceptance",
)
HISTORICAL_CAPACITY_BLOCKERS_HEADING = "## Historical capacity-blocker records"
CAPACITY_BLOCKER_DATE = "2026-08-01"
HISTORICAL_CAPACITY_BLOCKER_DATES = {
    CHECKPOINT_BLOCKER_RECORD: CAPACITY_BLOCKER_DATE,
    RESOURCE_BLOCKER_RECORD: CAPACITY_BLOCKER_DATE,
}
HISTORICAL_CAPACITY_BLOCKER_DIGESTS = {
    CHECKPOINT_BLOCKER_RECORD: CHECKPOINT_BLOCKER_DIGEST,
    RESOURCE_BLOCKER_RECORD: RESOURCE_BLOCKER_DIGEST,
}
CHECKPOINT_BLOCKER_UNCLAIMED_BOUNDARIES = (
    "restore/replay acceptance",
    "e1/e2",
    "ttl",
    "four-hour soak",
    "rollback",
    "production acceptance",
)
SOAK_RESOURCE_BLOCKER_UNCLAIMED_BOUNDARIES = (
    "canary",
    "four-hour soak",
    "rollback",
    "checkpoint restore/replay",
    "production acceptance",
)

LINK_RE = re.compile(r"\[[^]]+\]\(([^)#?]+\.md)\)")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SEPARATOR_CELL_RE = re.compile(r":?-{3,}:?")


def _section(text: str, heading: str) -> str:
    start = text.index(heading) + len(heading)
    end = text.find("\n## ", start)
    return text[start:] if end == -1 else text[start:end]


def _normalize_field(cell: str) -> str:
    return re.sub(r"[\s_-]+", " ", cell.strip().lower())


def _markdown_table(section: str) -> tuple[list[str], list[list[str]]]:
    raw_rows: list[list[str]] = []
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        raw_rows.append(cells)

    assert raw_rows, "section has no Markdown table"
    headers = [_normalize_field(cell) for cell in raw_rows[0]]
    body = raw_rows[1:]
    if body and all(SEPARATOR_CELL_RE.fullmatch(cell.replace(" ", "")) for cell in body[0]):
        body = body[1:]
    return headers, body


def _rows_for_heading(heading: str) -> list[dict[str, str]]:
    section = _section(INDEX.read_text(encoding="utf-8"), heading)
    headers, body = _markdown_table(section)
    rows: list[dict[str, str]] = []
    for cells in body:
        assert len(cells) == len(headers), (
            f"expected {len(headers)} columns, got {len(cells)}: {cells!r}"
        )
        rows.append(dict(zip(headers, cells, strict=True)))
    assert rows, f"{heading} table has no data rows"
    return rows


def _security_dependency_rows() -> list[dict[str, str]]:
    return _rows_for_heading(SECURITY_DEPENDENCY_HEADING)


def _entity_hot_path_rows() -> list[dict[str, str]]:
    return _rows_for_heading(ENTITY_HOT_PATH_HEADING)


def _entity_hot_path_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _entity_hot_path_rows()]


def _openapi_divergence_rows() -> list[dict[str, str]]:
    return _rows_for_heading(OPENAPI_DIVERGENCE_HEADING)


def _openapi_divergence_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _openapi_divergence_rows()]


def _historical_auth_bench_rows() -> list[dict[str, str]]:
    return _rows_for_heading(HISTORICAL_AUTH_BENCH_HEADING)


def _historical_auth_bench_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _historical_auth_bench_rows()]


def _ci_performance_rows() -> list[dict[str, str]]:
    return _rows_for_heading(CI_PERFORMANCE_HEADING)


def _ci_performance_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _ci_performance_rows()]


def _arm_benchmark_rows() -> list[dict[str, str]]:
    return _rows_for_heading(ARM_BENCHMARK_HEADING)


def _arm_benchmark_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _arm_benchmark_rows()]


def _clickhouse_serving_rows() -> list[dict[str, str]]:
    return _rows_for_heading(CLICKHOUSE_SERVING_HEADING)


def _clickhouse_serving_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _clickhouse_serving_rows()]


def _clickhouse_pii_rows() -> list[dict[str, str]]:
    return _rows_for_heading(CLICKHOUSE_PII_HEADING)


def _clickhouse_pii_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _clickhouse_pii_rows()]


def _postgresql_pii_rows() -> list[dict[str, str]]:
    return _rows_for_heading(POSTGRESQL_PII_HEADING)


def _postgresql_pii_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _postgresql_pii_rows()]


def _postgresql_runtime_rows() -> list[dict[str, str]]:
    return _rows_for_heading(POSTGRESQL_RUNTIME_HEADING)


def _postgresql_runtime_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _postgresql_runtime_rows()]


def _nl_sql_evaluation_rows() -> list[dict[str, str]]:
    return _rows_for_heading(NL_SQL_EVALUATION_HEADING)


def _nl_sql_evaluation_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _nl_sql_evaluation_rows()]


def _historical_streaming_hop_rows() -> list[dict[str, str]]:
    return _rows_for_heading(HISTORICAL_STREAMING_HOP_HEADING)


def _historical_streaming_hop_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _historical_streaming_hop_rows()]


def _current_freshness_rows() -> list[dict[str, str]]:
    return _rows_for_heading(CURRENT_FRESHNESS_HEADING)


def _current_freshness_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _current_freshness_rows()]


def _e4_replica_rows() -> list[dict[str, str]]:
    return _rows_for_heading(E4_REPLICA_HEADING)


def _e4_replica_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _e4_replica_rows()]


def _historical_e4_rows() -> list[dict[str, str]]:
    return _rows_for_heading(HISTORICAL_E4_HEADING)


def _historical_e4_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _historical_e4_rows()]


def _current_endurance_scale_rows() -> list[dict[str, str]]:
    return _rows_for_heading(CURRENT_ENDURANCE_SCALE_HEADING)


def _current_endurance_scale_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _current_endurance_scale_rows()]


def _rss_reverify_rows() -> list[dict[str, str]]:
    return _rows_for_heading(RSS_REVERIFY_HEADING)


def _rss_reverify_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _rss_reverify_rows()]


def _current_s10_throughput_rows() -> list[dict[str, str]]:
    return _rows_for_heading(CURRENT_S10_THROUGHPUT_HEADING)


def _current_s10_throughput_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _current_s10_throughput_rows()]


def _historical_paced_4h_rows() -> list[dict[str, str]]:
    return _rows_for_heading(HISTORICAL_PACED_4H_HEADING)


def _historical_paced_4h_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _historical_paced_4h_rows()]


def _q12_predecessor_rows() -> list[dict[str, str]]:
    return _rows_for_heading(Q12_PREDECESSOR_HEADING)


def _q12_predecessor_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _q12_predecessor_rows()]


def _q13_q14_intermediate_s10_rows() -> list[dict[str, str]]:
    return _rows_for_heading(Q13_Q14_INTERMEDIATE_S10_HEADING)


def _q13_q14_intermediate_s10_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _q13_q14_intermediate_s10_rows()]


def _paced_10m_1h_rows() -> list[dict[str, str]]:
    return _rows_for_heading(PACED_10M_1H_HEADING)


def _paced_10m_1h_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _paced_10m_1h_rows()]


def _finite_100eps_drain_rows() -> list[dict[str, str]]:
    return _rows_for_heading(FINITE_100EPS_DRAIN_HEADING)


def _finite_100eps_drain_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _finite_100eps_drain_rows()]


def _status_table_rows(heading: str) -> list[dict[str, str]]:
    section = _section(STATUS.read_text(encoding="utf-8"), heading)
    headers, body = _markdown_table(section)
    rows: list[dict[str, str]] = []
    for cells in body:
        assert len(cells) == len(headers), (
            f"expected {len(headers)} columns, got {len(cells)}: {cells!r}"
        )
        rows.append(dict(zip(headers, cells, strict=True)))
    return rows


def _status_cell_record_paths(cell: str) -> list[str]:
    return [
        (STATUS.parent / target).resolve().relative_to(ROOT).as_posix()
        for target in LINK_RE.findall(cell)
    ]


def _acceptance_rows() -> list[dict[str, str]]:
    return _rows_for_heading(ACCEPTANCE_HEADING)


def _on_disk_evidence_records() -> set[str]:
    return {
        path.relative_to(ROOT).as_posix()
        for path in EVIDENCE_DIR.glob("*.md")
        if path.name != "INDEX.md"
    }


def _resolve_index_link(target: str) -> str:
    return (INDEX.parent / target).resolve().relative_to(ROOT).as_posix()


def _tracked_perf_markdown_paths() -> set[str]:
    completed = subprocess.run(
        ["git", "ls-files", "--", "docs/perf"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return {
        line.strip().replace("\\", "/")
        for line in completed.stdout.splitlines()
        if line.strip().endswith(".md")
    }


def _represented_perf_markdown_paths() -> set[str]:
    tracked = _tracked_perf_markdown_paths()
    represented: set[str] = set()
    for target in LINK_RE.findall(INDEX.read_text(encoding="utf-8")):
        target_without_fragment = target.split("#", 1)[0]
        if not target_without_fragment:
            continue
        resolved = _resolve_index_link(target_without_fragment)
        if resolved in tracked:
            represented.add(resolved)
    return represented


def _catalogue_rows() -> list[dict[str, str]]:
    lines = INDEX.read_text(encoding="utf-8").splitlines()
    rows: list[dict[str, str]] = []
    line_index = 0
    while line_index < len(lines):
        if not lines[line_index].startswith("|"):
            line_index += 1
            continue
        table_lines: list[str] = []
        while line_index < len(lines) and lines[line_index].startswith("|"):
            table_lines.append(lines[line_index])
            line_index += 1
        headers, body = _markdown_table("\n".join(table_lines))
        if headers != list(REQUIRED_FIELDS):
            continue
        for cells in body:
            assert len(cells) == len(headers), (
                f"expected {len(headers)} columns, got {len(cells)}: {cells!r}"
            )
            rows.append(dict(zip(headers, cells, strict=True)))
    return rows


def _catalogue_rows_by_path() -> dict[str, dict[str, str]]:
    rows_by_path: dict[str, dict[str, str]] = {}
    for row in _catalogue_rows():
        path = _identity_path(row["identity"])
        assert path not in rows_by_path, f"duplicate evidence identity: {path}"
        rows_by_path[path] = row
    return rows_by_path


def _identity_path(cell: str) -> str:
    matches = LINK_RE.findall(cell)
    assert matches, f"identity cell has no markdown path: {cell!r}"
    assert len(matches) == 1, f"identity cell must name one record: {cell!r}"
    return _resolve_index_link(matches[0])


def _indexed_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _security_dependency_rows()]


def _acceptance_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _acceptance_rows()]


def _checkpoint_readiness_rows() -> list[dict[str, str]]:
    return _rows_for_heading(CHECKPOINT_READINESS_HEADING)


def _checkpoint_readiness_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _checkpoint_readiness_rows()]


def _f10_rows() -> list[dict[str, str]]:
    return _rows_for_heading(F10_HEADING)


def _f10_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _f10_rows()]


def _kind_soak_rows() -> list[dict[str, str]]:
    return _rows_for_heading(KIND_SOAK_HEADING)


def _kind_soak_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _kind_soak_rows()]


def _soak_rca_rows() -> list[dict[str, str]]:
    return _rows_for_heading(SOAK_RCA_HEADING)


def _soak_rca_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _soak_rca_rows()]


def _historical_canary_soak_rows() -> list[dict[str, str]]:
    return _rows_for_heading(HISTORICAL_CANARY_SOAK_HEADING)


def _historical_canary_soak_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _historical_canary_soak_rows()]


def _historical_capacity_blocker_rows() -> list[dict[str, str]]:
    return _rows_for_heading(HISTORICAL_CAPACITY_BLOCKERS_HEADING)


def _historical_capacity_blocker_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _historical_capacity_blocker_rows()]


def _project_closure_record_links() -> set[str]:
    found: set[str] = set()
    for target in LINK_RE.findall(PROJECT_CLOSURE.read_text(encoding="utf-8")):
        resolved = (PROJECT_CLOSURE.parent / target).resolve()
        try:
            found.add(resolved.relative_to(ROOT).as_posix())
        except ValueError:
            continue
    return found


def _status_record_links() -> set[str]:
    found: set[str] = set()
    for target in LINK_RE.findall(STATUS.read_text(encoding="utf-8")):
        resolved = (STATUS.parent / target).resolve()
        try:
            found.add(resolved.relative_to(ROOT).as_posix())
        except ValueError:
            continue
    return found


def _row_text(row: dict[str, str]) -> str:
    return f"{row.get('result', '')} {row.get('claim boundary', '')}".lower()


def _status_evidence_links() -> set[str]:
    found: set[str] = set()
    for target in LINK_RE.findall(STATUS.read_text(encoding="utf-8")):
        resolved = (STATUS.parent / target).resolve()
        try:
            relative = resolved.relative_to(ROOT).as_posix()
        except ValueError:
            continue
        if Path(relative).parent.as_posix() != "docs/evidence":
            continue
        if Path(relative).name == "INDEX.md":
            continue
        found.add(relative)
    return found


def _assert_supersession_cell(cell: str) -> None:
    if cell == "None":
        return
    targets = LINK_RE.findall(cell)
    remainder = LINK_RE.sub("", cell).strip()
    assert targets, f"supersession cell invents an unnamed target: {cell!r}"
    assert remainder == "", f"supersession cell has unnamed leftover text: {cell!r}"
    for target in targets:
        path = ROOT / _resolve_index_link(target)
        assert path.is_file(), f"supersession target does not exist: {target!r}"


def test_security_dependency_index_lists_each_evidence_record_once() -> None:
    indexed = _indexed_record_paths()
    on_disk = _on_disk_evidence_records()

    assert set(indexed) == on_disk
    assert Counter(indexed) == Counter(on_disk)


def test_security_dependency_index_exposes_required_nonempty_fields() -> None:
    rows = _security_dependency_rows()
    headers = list(rows[0])

    assert headers == list(REQUIRED_FIELDS)
    for row in rows:
        for field in REQUIRED_FIELDS:
            assert row[field].strip(), f"{field} is empty in {row!r}"
        assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]


def test_status_evidence_links_match_indexed_records() -> None:
    indexed = set(_indexed_record_paths())

    assert indexed == _status_evidence_links()
    assert indexed == _on_disk_evidence_records()


def test_protected_evidence_records_keep_published_digests() -> None:
    for relative, expected in PROTECTED_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected


def test_supersession_fields_are_none_or_existing_paths() -> None:
    for row in _security_dependency_rows():
        _assert_supersession_cell(row.get("supersedes", ""))
        _assert_supersession_cell(row.get("superseded by", ""))


def test_entity_hot_path_index_lists_three_bounded_records() -> None:
    text = INDEX.read_text(encoding="utf-8")
    security_at = text.index(SECURITY_DEPENDENCY_HEADING)
    entity_at = text.index(ENTITY_HOT_PATH_HEADING)
    openapi_at = text.index(OPENAPI_DIVERGENCE_HEADING)
    indexed = _entity_hot_path_record_paths()
    rows = _entity_hot_path_rows()

    assert security_at < entity_at < openapi_at
    assert indexed == list(ENTITY_HOT_PATH_RECORDS)
    assert Counter(indexed) == Counter(ENTITY_HOT_PATH_RECORDS)
    assert len(rows) == 3
    for row in rows:
        assert list(row) == list(REQUIRED_FIELDS)
        for field in REQUIRED_FIELDS:
            assert row[field].strip(), f"{field} is empty in {row!r}"
        assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
        record = _identity_path(row["identity"])
        assert row["date"] == ENTITY_HOT_PATH_DATES[record]
        assert (ROOT / record).is_file()
        targets = LINK_RE.findall(row["identity"])
        assert targets[0].startswith("../perf/"), row["identity"]


def test_entity_hot_path_records_are_complementary_not_supersession() -> None:
    section = " ".join(
        _section(INDEX.read_text(encoding="utf-8"), ENTITY_HOT_PATH_HEADING).lower().split()
    )

    assert "three human-authored identities" in section
    assert "json/svg companions" in section
    assert "not separate evidence identities" in section
    assert "complementary stages" in section
    assert "not a document supersession chain" in section
    assert "not a monotonic performance trajectory" in section
    for row in _entity_hot_path_rows():
        assert row["supersedes"] == "None"
        assert row["superseded by"] == "None"
        _assert_supersession_cell(row["supersedes"])
        _assert_supersession_cell(row["superseded by"])


def test_entity_hot_path_records_keep_published_digests() -> None:
    assert _entity_hot_path_record_paths() == list(ENTITY_HOT_PATH_RECORDS)
    for relative, expected in ENTITY_HOT_PATH_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected


def test_entity_hot_path_sources_and_plan_match_the_index() -> None:
    sources = {
        record: (ROOT / record).read_text(encoding="utf-8") for record in ENTITY_HOT_PATH_RECORDS
    }
    perf_readme = (ROOT / "docs" / "perf" / "README.md").read_text(encoding="utf-8")
    ci_gap = (ROOT / CI_HARDWARE_GAP_RECORD).read_text(encoding="utf-8")
    ci_gap_normalized = " ".join(ci_gap.split())
    index_normalized = " ".join(INDEX.read_text(encoding="utf-8").split())
    plan = DOCUMENTATION_PLAN.read_text(encoding="utf-8").lower()
    tracked_perf = _tracked_perf_markdown_paths()
    represented_perf = _represented_perf_markdown_paths()
    remaining_perf = tracked_perf - represented_perf

    assert "written by hand" in perf_readme
    assert ENTITY_TENANT_CACHE_RECORD in ci_gap
    assert "936 ms to 167 ms" in ci_gap
    assert "throughput 68 → 138 RPS" in ci_gap_normalized
    assert "for inventory only" in index_normalized.lower()
    assert (
        "representation does not make navigation or supporting companions evidence identities"
        in (index_normalized.lower())
    )
    assert (len(tracked_perf), len(represented_perf), len(remaining_perf)) == (58, 58, 0)
    assert not remaining_perf
    assert PERF_NON_IDENTITY_PATHS <= represented_perf
    assert "latest refresh" in sources[ENTITY_BASELINE_RECORD].lower()
    assert "97a190248a943b5ef6910881be4b9c010eceb33f" in sources[ENTITY_BASELINE_RECORD]
    assert "5b57cf4" in sources[ENTITY_BASELINE_RECORD]
    assert "**date:** 2026-04-24" in sources[ENTITY_PII_CACHE_RECORD].lower()
    assert "**head:** `220f94c`" in sources[ENTITY_PII_CACHE_RECORD].lower()
    assert "all 2000 requests succeeded" in sources[ENTITY_PII_CACHE_RECORD].lower()
    assert (
        "**head measured:** `5b57cf4020f8c7f0138e313d47ab644c2b33f6a4`"
        in sources[ENTITY_TENANT_CACHE_RECORD].lower()
    )
    assert "p99 spread above" in sources[ENTITY_TENANT_CACHE_RECORD].lower()
    assert "historical entity hot-path optimization records sub-slice" in plan
    for digest in ENTITY_HOT_PATH_DIGESTS.values():
        assert digest in plan
    assert "пункт 5 закрыт" in plan


def test_perf_inventory_classifies_non_identity_paths_without_manufacturing_records() -> None:
    rows = _rows_for_heading(PERF_NON_IDENTITY_HEADING)
    listed = [_identity_path(row["path"]) for row in rows]
    tracked = _tracked_perf_markdown_paths()
    represented = _represented_perf_markdown_paths()
    identities = set(_catalogue_rows_by_path())
    index_text = " ".join(INDEX.read_text(encoding="utf-8").lower().split())
    plan = " ".join(DOCUMENTATION_PLAN.read_text(encoding="utf-8").lower().split())

    assert list(rows[0]) == list(PERF_NON_IDENTITY_FIELDS)
    assert set(listed) == PERF_NON_IDENTITY_PATHS
    assert Counter(listed) == Counter(PERF_NON_IDENTITY_PATHS)
    assert PERF_NON_IDENTITY_PATHS.isdisjoint(identities)
    assert (len(tracked), len(represented), len(tracked - represented)) == (58, 58, 0)
    assert "catalogue identity rows below are **immutable records**" in index_text
    assert "classified non-identity paths below retain their stated lifecycle" in index_text
    assert "outside this immutability rule" in index_text
    for row, path in zip(rows, listed, strict=True):
        assert (ROOT / path).is_file()
        row_text = " ".join(row.values()).lower()
        for phrase in PERF_NON_IDENTITY_PHRASES[path]:
            assert phrase in row_text
    assert "- [x] **5. упорядочить evidence.**" in plan
    assert "status/orphan/supersession closure audit" in plan
    assert "58 tracked `docs/perf` markdown paths, 58" in plan
    assert "0 остаются unrepresented" in plan


def test_status_perf_claims_link_to_indexed_identities() -> None:
    identities = set(_catalogue_rows_by_path())
    status_perf_links = {
        path for path in _status_record_links() if Path(path).parent.as_posix() == "docs/perf"
    }
    bridge_rows = _status_table_rows(S10_R4_STATUS_HEADING)
    expected_bridge_records = (
        S10_BURST_BASELINE_RECORD,
        S10_Q12_RECORD,
        S10_Q13_RECORD,
        S10_Q14_RECORD,
        S10_100EPS_TRY_RECORD,
        S10_PACED_10M_RECORD,
        S10_PACED_1H_RECORD,
        S10_PACED_R4_RECORD,
    )

    assert status_perf_links <= identities
    assert len(bridge_rows) == len(expected_bridge_records)
    for row, expected in zip(bridge_rows, expected_bridge_records, strict=True):
        links = _status_cell_record_paths(row["state"])
        assert links == [expected], f"status claim lacks one indexed identity: {row!r}"


def test_catalogue_supersession_links_are_existing_and_reciprocal() -> None:
    rows_by_path = _catalogue_rows_by_path()
    reciprocal_fields = {
        "supersedes": "superseded by",
        "superseded by": "supersedes",
    }

    for source, row in rows_by_path.items():
        for field, reciprocal_field in reciprocal_fields.items():
            _assert_supersession_cell(row[field])
            for target in LINK_RE.findall(row[field]):
                target_path = _resolve_index_link(target)
                assert target_path in rows_by_path, f"{source} {field} non-identity {target_path}"
                reciprocal_targets = {
                    _resolve_index_link(link)
                    for link in LINK_RE.findall(rows_by_path[target_path][reciprocal_field])
                }
                assert source in reciprocal_targets, (
                    f"{source} {field} {target_path} without reciprocal {reciprocal_field}"
                )


def test_entity_hot_path_results_and_boundaries_remain_conservative() -> None:
    rows_by_record = {_identity_path(row["identity"]): row for row in _entity_hot_path_rows()}
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))

    assert set(rows_by_record) == set(ENTITY_HOT_PATH_RECORDS)
    for record, phrases in ENTITY_HOT_PATH_FACTS.items():
        row_text = _row_text(rows_by_record[record])
        for phrase in phrases:
            assert phrase in row_text
    for record, phrases in ENTITY_HOT_PATH_BOUNDARIES.items():
        row_text = _row_text(rows_by_record[record])
        for phrase in phrases:
            assert phrase in row_text
    assert manifest["production"]["status"] == "candidate"


def test_openapi_divergence_index_lists_one_bounded_record() -> None:
    text = INDEX.read_text(encoding="utf-8")
    security_at = text.index(SECURITY_DEPENDENCY_HEADING)
    divergence_at = text.index(OPENAPI_DIVERGENCE_HEADING)
    auth_at = text.index(HISTORICAL_AUTH_BENCH_HEADING)
    indexed = _openapi_divergence_record_paths()
    rows = _openapi_divergence_rows()

    assert security_at < divergence_at < auth_at
    assert indexed == [OPENAPI_DIVERGENCE_RECORD]
    assert Counter(indexed) == Counter((OPENAPI_DIVERGENCE_RECORD,))
    assert len(rows) == 1
    row = rows[0]
    assert list(row) == list(REQUIRED_FIELDS)
    for field in REQUIRED_FIELDS:
        assert row[field].strip(), f"{field} is empty in {row!r}"
    assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
    assert row["date"] == OPENAPI_DIVERGENCE_DATE
    assert (ROOT / OPENAPI_DIVERGENCE_RECORD).is_file()
    targets = LINK_RE.findall(row["identity"])
    assert targets[0].startswith("../perf/"), row["identity"]


def test_openapi_divergence_is_one_diagnostic_not_supersession() -> None:
    section = " ".join(
        _section(INDEX.read_text(encoding="utf-8"), OPENAPI_DIVERGENCE_HEADING).lower().split()
    )
    row = _openapi_divergence_rows()[0]

    assert "one immutable diagnostic identity" in section
    assert "not a document supersession chain" in section
    assert row["supersedes"] == "None"
    assert row["superseded by"] == "None"
    _assert_supersession_cell(row["supersedes"])
    _assert_supersession_cell(row["superseded by"])


def test_openapi_divergence_record_keeps_published_digest() -> None:
    assert _openapi_divergence_record_paths() == [OPENAPI_DIVERGENCE_RECORD]
    digest = hashlib.sha256((ROOT / OPENAPI_DIVERGENCE_RECORD).read_bytes()).hexdigest()
    assert digest == OPENAPI_DIVERGENCE_DIGEST


def test_openapi_divergence_sources_and_plan_match_the_index() -> None:
    source = (ROOT / OPENAPI_DIVERGENCE_RECORD).read_text(encoding="utf-8")
    index = INDEX.read_text(encoding="utf-8")
    contract_test = (ROOT / "tests" / "contract" / "test_openapi_compliance.py").read_text(
        encoding="utf-8"
    )
    exporter = (ROOT / "scripts" / "export_openapi.py").read_text(encoding="utf-8")
    exporter_test = (ROOT / "tests" / "unit" / "test_export_openapi.py").read_text(encoding="utf-8")
    plan = DOCUMENTATION_PLAN.read_text(encoding="utf-8").lower()

    assert "test_documented_openapi_snapshot_matches_live_api" in source
    assert "python 3.13 passed" in source.lower()
    for phrase in (
        "FastAPI 0.128.0",
        "Pydantic 2.12.5",
        "Starlette 0.50.0",
        "FastAPI 0.135.3",
        "FastAPI 0.136.1",
        "`components.schemas.ValidationError.properties.input` and `ctx`",
        "strict for project-owned schemas and paths",
    ):
        assert phrase in source
    assert "(../perf/README.md)" in index
    assert "_normalize_openapi_schemas" in contract_test
    assert "_normalize_fastapi_validation_error_schema" in exporter
    assert "_normalize_fastapi_validation_error_schema" in exporter_test
    for implementation in (contract_test, exporter):
        assert 'properties.pop("input", None)' in implementation
        assert 'properties.pop("ctx", None)' in implementation
    assert "historical openapi contract divergence diagnostic sub-slice" in plan
    assert OPENAPI_DIVERGENCE_DIGEST in plan
    assert "пункт 5 остаётся открыт" in plan


def test_openapi_divergence_result_and_boundary_remain_conservative() -> None:
    row = _openapi_divergence_rows()[0]
    row_text = _row_text(row)
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))

    for phrase in OPENAPI_DIVERGENCE_FACTS:
        assert phrase in row_text
    for phrase in OPENAPI_DIVERGENCE_BOUNDARIES:
        assert phrase in row_text
    assert manifest["production"]["status"] == "candidate"


def test_historical_auth_bench_index_lists_one_bounded_record() -> None:
    text = INDEX.read_text(encoding="utf-8")
    security_at = text.index(SECURITY_DEPENDENCY_HEADING)
    auth_at = text.index(HISTORICAL_AUTH_BENCH_HEADING)
    serving_at = text.index(CLICKHOUSE_SERVING_HEADING)
    indexed = _historical_auth_bench_record_paths()
    rows = _historical_auth_bench_rows()

    assert security_at < auth_at < serving_at
    assert indexed == [HISTORICAL_AUTH_BENCH_RECORD]
    assert Counter(indexed) == Counter((HISTORICAL_AUTH_BENCH_RECORD,))
    assert list(rows[0]) == list(REQUIRED_FIELDS)
    assert len(rows) == 1
    row = rows[0]
    for field in REQUIRED_FIELDS:
        assert row[field].strip(), f"{field} is empty in {row!r}"
    assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
    assert row["date"] == HISTORICAL_AUTH_BENCH_DATE
    assert (ROOT / HISTORICAL_AUTH_BENCH_RECORD).is_file()
    targets = LINK_RE.findall(row["identity"])
    assert targets[0].startswith("../perf/"), row["identity"]


def test_historical_auth_bench_is_one_identity_not_document_supersession() -> None:
    section = " ".join(
        _section(INDEX.read_text(encoding="utf-8"), HISTORICAL_AUTH_BENCH_HEADING).lower().split()
    )
    row = _historical_auth_bench_rows()[0]

    assert "same immutable identity" in section
    assert "not a document supersession chain" in section
    assert row["supersedes"] == "None"
    assert row["superseded by"] == "None"
    _assert_supersession_cell(row["supersedes"])
    _assert_supersession_cell(row["superseded by"])


def test_historical_auth_bench_record_keeps_published_digest() -> None:
    assert _historical_auth_bench_record_paths() == [HISTORICAL_AUTH_BENCH_RECORD]
    digest = hashlib.sha256((ROOT / HISTORICAL_AUTH_BENCH_RECORD).read_bytes()).hexdigest()
    assert digest == HISTORICAL_AUTH_BENCH_DIGEST


def test_historical_auth_bench_sources_and_plan_match_the_index() -> None:
    source = (ROOT / HISTORICAL_AUTH_BENCH_RECORD).read_text(encoding="utf-8")
    runbook = (ROOT / "docs" / "runbooks" / "auth-401-spike.md").read_text(encoding="utf-8")
    changelog = CHANGELOG.read_text(encoding="utf-8")
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))
    plan = DOCUMENTATION_PLAN.read_text(encoding="utf-8").lower()

    assert "scripts/perf/auth_bench.py" in source
    assert Path(HISTORICAL_AUTH_BENCH_RECORD).name in runbook
    assert HISTORICAL_AUTH_BENCH_RECORD in changelog
    assert HISTORICAL_AUTH_BENCH_RECORD not in manifest["required_evidence"]
    assert "historical authentication performance baseline sub-slice" in plan
    assert HISTORICAL_AUTH_BENCH_DIGEST in plan
    assert "пункт 5 остаётся открыт" in plan


def test_historical_auth_bench_result_and_boundary_remain_conservative() -> None:
    row = _historical_auth_bench_rows()[0]
    historical = _row_text(row)
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))

    for phrase in HISTORICAL_AUTH_BENCH_FACTS:
        assert phrase in historical
    for phrase in HISTORICAL_AUTH_BENCH_BOUNDARIES:
        assert phrase in historical
    assert manifest["production"]["status"] == "candidate"


def test_ci_performance_interpretation_index_lists_two_bounded_records() -> None:
    text = INDEX.read_text(encoding="utf-8")
    auth_at = text.index(HISTORICAL_AUTH_BENCH_HEADING)
    performance_at = text.index(CI_PERFORMANCE_HEADING)
    serving_at = text.index(CLICKHOUSE_SERVING_HEADING)
    indexed = _ci_performance_record_paths()
    rows = _ci_performance_rows()

    assert auth_at < performance_at < serving_at
    assert indexed == list(CI_PERFORMANCE_RECORDS)
    assert Counter(indexed) == Counter(CI_PERFORMANCE_RECORDS)
    assert len(rows) == 2
    for row in rows:
        assert list(row) == list(REQUIRED_FIELDS)
        for field in REQUIRED_FIELDS:
            assert row[field].strip(), f"{field} is empty in {row!r}"
        assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
        record = _identity_path(row["identity"])
        assert row["date"] == CI_PERFORMANCE_DATES[record]
        assert (ROOT / record).is_file()
        targets = LINK_RE.findall(row["identity"])
        assert targets[0].startswith("../perf/"), row["identity"]


def test_ci_performance_records_are_complementary_not_document_supersession() -> None:
    section = " ".join(
        _section(INDEX.read_text(encoding="utf-8"), CI_PERFORMANCE_HEADING).lower().split()
    )

    assert "complementary" in section
    assert "does not supersede the a03 document" in section
    for row in _ci_performance_rows():
        assert row["supersedes"] == "None"
        assert row["superseded by"] == "None"
        _assert_supersession_cell(row["supersedes"])
        _assert_supersession_cell(row["superseded by"])


def test_ci_performance_records_keep_published_digests() -> None:
    assert _ci_performance_record_paths() == list(CI_PERFORMANCE_RECORDS)
    for relative, expected in CI_PERFORMANCE_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected


def test_ci_performance_sources_and_plan_match_the_index() -> None:
    assert _ci_performance_record_paths() == list(CI_PERFORMANCE_RECORDS)
    baseline = (ROOT / "docs" / "benchmark-baseline.json").read_text(encoding="utf-8")
    release_status = (ROOT / "docs" / "dv2-multi-branch" / "RELEASE_STATUS.md").read_text(
        encoding="utf-8"
    )
    readiness = (ROOT / "docs" / "release-readiness.md").read_text(encoding="utf-8")
    legacy_plan = (ROOT / "plan_07_07_26.md").read_text(encoding="utf-8").lower()
    usage_writer = (
        ROOT / "src" / "agentflow_runtime" / "serving" / "api" / "auth" / "usage_writer.py"
    ).read_text(encoding="utf-8")
    plan = DOCUMENTATION_PLAN.read_text(encoding="utf-8").lower()

    assert CI_HARDWARE_GAP_RECORD in baseline
    assert CI_HARDWARE_GAP_RECORD in release_status
    assert CI_HARDWARE_GAP_RECORD in readiness
    assert CI_USAGE_WRITE_RECORD in legacy_plan
    assert "не раннер" in legacy_plan
    assert CI_USAGE_WRITE_RECORD in usage_writer
    assert "ci performance interpretation evidence pair sub-slice" in plan
    for digest in CI_PERFORMANCE_DIGESTS.values():
        assert digest in plan
    assert "пункт 5 остаётся открыт" in plan


def test_ci_performance_results_and_boundaries_remain_conservative() -> None:
    rows_by_record = {_identity_path(row["identity"]): row for row in _ci_performance_rows()}
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))

    assert set(rows_by_record) == set(CI_PERFORMANCE_RECORDS)
    for record, phrases in CI_PERFORMANCE_FACTS.items():
        row_text = _row_text(rows_by_record[record])
        for phrase in phrases:
            assert phrase in row_text
    for record, phrases in CI_PERFORMANCE_BOUNDARIES.items():
        row_text = _row_text(rows_by_record[record])
        for phrase in phrases:
            assert phrase in row_text
    assert manifest["production"]["status"] == "candidate"


def test_arm_shared_runner_index_lists_one_bounded_identity() -> None:
    text = INDEX.read_text(encoding="utf-8")
    ci_at = text.index(CI_PERFORMANCE_HEADING)
    arm_at = text.index(ARM_BENCHMARK_HEADING)
    serving_at = text.index(CLICKHOUSE_SERVING_HEADING)
    rows = _arm_benchmark_rows()
    indexed = _arm_benchmark_record_paths()

    assert ci_at < arm_at < serving_at
    assert indexed == [ARM_BENCHMARK_RECORD]
    assert Counter(indexed) == Counter((ARM_BENCHMARK_RECORD,))
    assert len(rows) == 1
    row = rows[0]
    assert list(row) == list(REQUIRED_FIELDS)
    for field in REQUIRED_FIELDS:
        assert row[field].strip(), f"{field} is empty in {row!r}"
    assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
    assert row["date"] == ARM_BENCHMARK_DATE
    assert (ROOT / ARM_BENCHMARK_RECORD).is_file()
    targets = LINK_RE.findall(row["identity"])
    assert targets[0].startswith("../perf/"), row["identity"]


def test_arm_shared_runner_generated_companions_are_not_separate_identities() -> None:
    section = _section(INDEX.read_text(encoding="utf-8"), ARM_BENCHMARK_HEADING)
    section_text = " ".join(section.lower().split())
    resolved_markdown_links = {_resolve_index_link(target) for target in LINK_RE.findall(section)}
    row = _arm_benchmark_rows()[0]

    assert "one immutable benchmark identity" in section_text
    assert "generated companions" in section_text
    assert "not separate evidence identities" in section_text
    assert resolved_markdown_links == {
        ARM_BENCHMARK_RECORD,
        ARM_REPORT_COMPANION,
        ARM_HOST_COMPANION,
    }
    assert ARM_JSON_COMPANION in section
    assert _arm_benchmark_record_paths() == [ARM_BENCHMARK_RECORD]
    assert row["supersedes"] == "None"
    assert row["superseded by"] == "None"
    _assert_supersession_cell(row["supersedes"])
    _assert_supersession_cell(row["superseded by"])


def test_arm_shared_runner_packet_keeps_published_digests() -> None:
    assert _arm_benchmark_record_paths() == [ARM_BENCHMARK_RECORD]
    for relative, expected in ARM_PACKET_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected


def test_arm_shared_runner_sources_and_plan_match_the_index() -> None:
    assert _arm_benchmark_record_paths() == [ARM_BENCHMARK_RECORD]
    summary = (ROOT / ARM_BENCHMARK_RECORD).read_text(encoding="utf-8")
    hardware_plan = (
        ROOT / "docs" / "perf" / "public-production-hardware-benchmark-plan.md"
    ).read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "benchmark-arm.yml").read_text(encoding="utf-8")
    workflow_tests = (ROOT / "tests" / "unit" / "test_benchmark_arm_workflow.py").read_text(
        encoding="utf-8"
    )
    plan = DOCUMENTATION_PLAN.read_text(encoding="utf-8").lower()

    assert "actions/runs/27012731848" in summary
    assert "commit: `60e0f3d`" in summary.lower()
    assert Path(ARM_BENCHMARK_RECORD).name in hardware_plan
    assert ARM_BENCHMARK_RECORD in CHANGELOG.read_text(encoding="utf-8")
    assert "workflow_dispatch" in workflow
    assert "runs-on: ubuntu-24.04-arm" in workflow
    for companion in (ARM_REPORT_COMPANION, ARM_HOST_COMPANION, ARM_JSON_COMPANION):
        assert Path(companion).name in workflow
        assert Path(companion).name in workflow_tests
    assert "arm shared-runner benchmark packet sub-slice" in plan
    for digest in ARM_PACKET_DIGESTS.values():
        assert digest in plan
    assert "пункт 5 остаётся открыт" in plan


def test_arm_shared_runner_result_and_boundary_remain_conservative() -> None:
    row = _arm_benchmark_rows()[0]
    row_text = _row_text(row)
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))

    for phrase in ARM_BENCHMARK_FACTS:
        assert phrase in row_text
    for phrase in ARM_BENCHMARK_BOUNDARIES:
        assert phrase in row_text
    assert manifest["production"]["status"] == "candidate"


def test_clickhouse_serving_index_lists_one_bounded_record() -> None:
    text = INDEX.read_text(encoding="utf-8")
    security_at = text.index(SECURITY_DEPENDENCY_HEADING)
    serving_at = text.index(CLICKHOUSE_SERVING_HEADING)
    pii_at = text.index(CLICKHOUSE_PII_HEADING)
    indexed = _clickhouse_serving_record_paths()
    rows = _clickhouse_serving_rows()

    assert security_at < serving_at < pii_at
    assert indexed == [CLICKHOUSE_SERVING_RECORD]
    assert Counter(indexed) == Counter((CLICKHOUSE_SERVING_RECORD,))
    assert list(rows[0]) == list(REQUIRED_FIELDS)
    assert len(rows) == 1
    row = rows[0]
    for field in REQUIRED_FIELDS:
        assert row[field].strip(), f"{field} is empty in {row!r}"
    assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
    assert row["date"] == CLICKHOUSE_SERVING_DATE
    assert (ROOT / CLICKHOUSE_SERVING_RECORD).is_file()
    targets = LINK_RE.findall(row["identity"])
    assert targets[0].startswith("../perf/"), row["identity"]


def test_clickhouse_serving_is_separate_from_pii_not_supersession() -> None:
    section = " ".join(
        _section(INDEX.read_text(encoding="utf-8"), CLICKHOUSE_SERVING_HEADING).lower().split()
    )
    row = _clickhouse_serving_rows()[0]
    pii_rows = _clickhouse_pii_rows()

    assert "phase 1 serving surface" in section
    assert "separate from phase 2 pii-governance" in section
    assert "not a supersession" in section
    assert row["supersedes"] == "None"
    assert row["superseded by"] == "None"
    _assert_supersession_cell(row["supersedes"])
    _assert_supersession_cell(row["superseded by"])
    for pii_row in pii_rows:
        assert CLICKHOUSE_SERVING_RECORD not in pii_row["supersedes"]
        assert CLICKHOUSE_SERVING_RECORD not in pii_row["superseded by"]


def test_clickhouse_serving_record_keeps_published_digest() -> None:
    assert _clickhouse_serving_record_paths() == [CLICKHOUSE_SERVING_RECORD]
    digest = hashlib.sha256((ROOT / CLICKHOUSE_SERVING_RECORD).read_bytes()).hexdigest()
    assert digest == CLICKHOUSE_SERVING_DIGEST


def test_clickhouse_serving_sources_and_plan_match_the_index() -> None:
    migration = (ROOT / "docs" / "clickhouse-migration.md").read_text(encoding="utf-8")
    cutover = (ROOT / "docs" / "plans" / "clickhouse-cutover-plan.md").read_text(encoding="utf-8")
    phase_2 = (ROOT / CLICKHOUSE_PII_0702_RECORD).read_text(encoding="utf-8")
    plan = DOCUMENTATION_PLAN.read_text(encoding="utf-8").lower()

    assert Path(CLICKHOUSE_SERVING_RECORD).name in migration
    assert CLICKHOUSE_SERVING_RECORD in cutover
    assert Path(CLICKHOUSE_SERVING_RECORD).name in phase_2
    assert "clickhouse serving-path verification sub-slice" in plan
    assert CLICKHOUSE_SERVING_DIGEST in plan
    assert "пункт 5 остаётся открыт" in plan


def test_clickhouse_serving_result_and_boundary_remain_conservative() -> None:
    row = _clickhouse_serving_rows()[0]
    serving = _row_text(row)
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))

    for phrase in CLICKHOUSE_SERVING_FACTS:
        assert phrase in serving
    for phrase in CLICKHOUSE_SERVING_BOUNDARIES:
        assert phrase in serving
    assert manifest["production"]["status"] == "candidate"


def test_clickhouse_pii_index_lists_the_bounded_pair_with_required_fields() -> None:
    text = INDEX.read_text(encoding="utf-8")
    security_at = text.index(SECURITY_DEPENDENCY_HEADING)
    clickhouse_pii_at = text.index(CLICKHOUSE_PII_HEADING)
    freshness_at = text.index(CURRENT_FRESHNESS_HEADING)
    indexed = _clickhouse_pii_record_paths()
    expected = (CLICKHOUSE_PII_0702_RECORD, CLICKHOUSE_PII_0703_RECORD)
    rows = _clickhouse_pii_rows()

    assert security_at < clickhouse_pii_at < freshness_at
    assert indexed == list(expected)
    assert Counter(indexed) == Counter(expected)
    assert list(rows[0]) == list(REQUIRED_FIELDS)
    assert len(rows) == 2
    for row in rows:
        for field in REQUIRED_FIELDS:
            assert row[field].strip(), f"{field} is empty in {row!r}"
        assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
        identity = _identity_path(row["identity"])
        assert row["date"] == CLICKHOUSE_PII_DATES[identity]
        assert (ROOT / identity).is_file(), f"indexed identity is missing: {identity}"
        targets = LINK_RE.findall(row["identity"])
        assert targets[0].startswith("../perf/"), row["identity"]


def test_clickhouse_pii_refresh_is_a_narrow_reciprocal_supersession() -> None:
    section = " ".join(
        _section(INDEX.read_text(encoding="utf-8"), CLICKHOUSE_PII_HEADING).lower().split()
    )
    rows = {_identity_path(row["identity"]): row for row in _clickhouse_pii_rows()}
    earlier = rows[CLICKHOUSE_PII_0702_RECORD]
    current = rows[CLICKHOUSE_PII_0703_RECORD]

    assert "latest clickhouse live verification outcome" in section
    assert "historical facts remain valid" in section
    assert "separate postgresql" in section
    assert earlier["supersedes"] == "None"
    assert [
        _resolve_index_link(target) for target in LINK_RE.findall(earlier["superseded by"])
    ] == [CLICKHOUSE_PII_0703_RECORD]
    assert [_resolve_index_link(target) for target in LINK_RE.findall(current["supersedes"])] == [
        CLICKHOUSE_PII_0702_RECORD
    ]
    assert current["superseded by"] == "None"
    for row in rows.values():
        _assert_supersession_cell(row["supersedes"])
        _assert_supersession_cell(row["superseded by"])
        supersession_text = f"{row['supersedes']} {row['superseded by']}"
        assert "vault-pii-governance-pg-verify" not in supersession_text


def test_clickhouse_pii_records_keep_published_digests() -> None:
    indexed = set(_clickhouse_pii_record_paths())

    assert indexed == set(CLICKHOUSE_PII_DIGESTS)
    for relative, expected in CLICKHOUSE_PII_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected


def test_clickhouse_pii_canonical_claims_and_plan_match_the_index() -> None:
    indexed = set(_clickhouse_pii_record_paths())
    architecture = ARCHITECTURE.read_text(encoding="utf-8")
    changelog = CHANGELOG.read_text(encoding="utf-8")
    demo_evidence = DV2_DEMO_EVIDENCE.read_text(encoding="utf-8")
    plan = DOCUMENTATION_PLAN.read_text(encoding="utf-8").lower()

    assert indexed == {CLICKHOUSE_PII_0702_RECORD, CLICKHOUSE_PII_0703_RECORD}
    assert CLICKHOUSE_PII_0702_RECORD in changelog
    assert CLICKHOUSE_PII_0703_RECORD in architecture
    assert Path(CLICKHOUSE_PII_0703_RECORD).name in demo_evidence
    assert "clickhouse pii-governance evidence sub-slice" in plan
    for digest in CLICKHOUSE_PII_DIGESTS.values():
        assert digest in plan
    assert "пункт 5 остаётся открыт" in plan


def test_clickhouse_pii_results_and_boundaries_remain_conservative() -> None:
    rows = {_identity_path(row["identity"]): row for row in _clickhouse_pii_rows()}
    earlier = _row_text(rows[CLICKHOUSE_PII_0702_RECORD])
    current = _row_text(rows[CLICKHOUSE_PII_0703_RECORD])
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))

    for phrase in CLICKHOUSE_PII_0702_FACTS:
        assert phrase in earlier
    for phrase in CLICKHOUSE_PII_0703_FACTS:
        assert phrase in current
    for phrase in CLICKHOUSE_PII_0702_BOUNDARIES:
        assert phrase in earlier
    for phrase in CLICKHOUSE_PII_0703_BOUNDARIES:
        assert phrase in current
    assert manifest["production"]["status"] == "candidate"


def test_postgresql_pii_index_lists_the_bounded_pair_with_required_fields() -> None:
    text = INDEX.read_text(encoding="utf-8")
    clickhouse_pii_at = text.index(CLICKHOUSE_PII_HEADING)
    postgresql_pii_at = text.index(POSTGRESQL_PII_HEADING)
    freshness_at = text.index(CURRENT_FRESHNESS_HEADING)
    indexed = _postgresql_pii_record_paths()
    expected = (POSTGRESQL_PII_0702_RECORD, POSTGRESQL_PII_0703_RECORD)
    rows = _postgresql_pii_rows()

    assert clickhouse_pii_at < postgresql_pii_at < freshness_at
    assert indexed == list(expected)
    assert Counter(indexed) == Counter(expected)
    assert list(rows[0]) == list(REQUIRED_FIELDS)
    assert len(rows) == 2
    for row in rows:
        for field in REQUIRED_FIELDS:
            assert row[field].strip(), f"{field} is empty in {row!r}"
        assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
        identity = _identity_path(row["identity"])
        assert row["date"] == POSTGRESQL_PII_DATES[identity]
        assert (ROOT / identity).is_file(), f"indexed identity is missing: {identity}"
        targets = LINK_RE.findall(row["identity"])
        assert targets[0].startswith("../perf/"), row["identity"]


def test_postgresql_pii_refresh_is_a_narrow_reciprocal_supersession() -> None:
    section = " ".join(
        _section(INDEX.read_text(encoding="utf-8"), POSTGRESQL_PII_HEADING).lower().split()
    )
    rows = {_identity_path(row["identity"]): row for row in _postgresql_pii_rows()}
    earlier = rows[POSTGRESQL_PII_0702_RECORD]
    current = rows[POSTGRESQL_PII_0703_RECORD]

    assert "latest postgresql live-verification outcome" in section
    assert "historical facts remain valid" in section
    assert "clickhouse" in section
    assert earlier["supersedes"] == "None"
    assert [
        _resolve_index_link(target) for target in LINK_RE.findall(earlier["superseded by"])
    ] == [POSTGRESQL_PII_0703_RECORD]
    assert [_resolve_index_link(target) for target in LINK_RE.findall(current["supersedes"])] == [
        POSTGRESQL_PII_0702_RECORD
    ]
    assert current["superseded by"] == "None"
    for row in rows.values():
        _assert_supersession_cell(row["supersedes"])
        _assert_supersession_cell(row["superseded by"])
        supersession_text = f"{row['supersedes']} {row['superseded by']}"
        assert Path(CLICKHOUSE_PII_0702_RECORD).name not in supersession_text
        assert Path(CLICKHOUSE_PII_0703_RECORD).name not in supersession_text


def test_postgresql_pii_records_keep_published_digests() -> None:
    indexed = set(_postgresql_pii_record_paths())

    assert indexed == set(POSTGRESQL_PII_DIGESTS)
    for relative, expected in POSTGRESQL_PII_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected


def test_postgresql_pii_canonical_claims_and_plan_match_the_index() -> None:
    indexed = set(_postgresql_pii_record_paths())
    changelog = CHANGELOG.read_text(encoding="utf-8")
    demo_evidence = DV2_DEMO_EVIDENCE.read_text(encoding="utf-8")
    plan = DOCUMENTATION_PLAN.read_text(encoding="utf-8").lower()

    assert indexed == {POSTGRESQL_PII_0702_RECORD, POSTGRESQL_PII_0703_RECORD}
    assert "docs/perf/vault-pii-governance-pg-verify-2026-07-0{2,3}.md" in changelog
    assert Path(POSTGRESQL_PII_0703_RECORD).name in demo_evidence
    assert "postgresql pii-governance evidence sub-slice" in plan
    for digest in POSTGRESQL_PII_DIGESTS.values():
        assert digest in plan
    assert "пункт 5 остаётся открыт" in plan


def test_postgresql_pii_results_and_boundaries_remain_conservative() -> None:
    rows = {_identity_path(row["identity"]): row for row in _postgresql_pii_rows()}
    earlier = _row_text(rows[POSTGRESQL_PII_0702_RECORD])
    current = _row_text(rows[POSTGRESQL_PII_0703_RECORD])
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))

    for phrase in POSTGRESQL_PII_0702_FACTS:
        assert phrase in earlier
    for phrase in POSTGRESQL_PII_0703_FACTS:
        assert phrase in current
    for phrase in POSTGRESQL_PII_BOUNDARIES:
        assert phrase in earlier
        assert phrase in current
    assert manifest["production"]["status"] == "candidate"


def test_postgresql_runtime_index_lists_the_bounded_pair_with_required_fields() -> None:
    text = INDEX.read_text(encoding="utf-8")
    postgresql_pii_at = text.index(POSTGRESQL_PII_HEADING)
    runtime_at = text.index(POSTGRESQL_RUNTIME_HEADING)
    freshness_at = text.index(CURRENT_FRESHNESS_HEADING)
    indexed = _postgresql_runtime_record_paths()
    expected = (CONTROL_PLANE_PG_RECORD, BV_ORDER_CANONICAL_PG_RECORD)
    rows = _postgresql_runtime_rows()

    assert postgresql_pii_at < runtime_at < freshness_at
    assert indexed == list(expected)
    assert Counter(indexed) == Counter(expected)
    assert list(rows[0]) == list(REQUIRED_FIELDS)
    assert len(rows) == 2
    for row in rows:
        for field in REQUIRED_FIELDS:
            assert row[field].strip(), f"{field} is empty in {row!r}"
        assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
        identity = _identity_path(row["identity"])
        assert row["date"] == POSTGRESQL_RUNTIME_DATES[identity]
        assert (ROOT / identity).is_file(), f"indexed identity is missing: {identity}"
        targets = LINK_RE.findall(row["identity"])
        assert targets[0].startswith("../perf/"), row["identity"]


def test_postgresql_runtime_records_are_complementary_not_supersession() -> None:
    section = " ".join(
        _section(INDEX.read_text(encoding="utf-8"), POSTGRESQL_RUNTIME_HEADING).lower().split()
    )
    rows = _postgresql_runtime_rows()

    assert "complementary" in section
    assert "not a supersession chain" in section
    assert "separate runtime surfaces" in section
    assert "different postgresql versions and hosts" in section
    for row in rows:
        assert row["supersedes"] == "None"
        assert row["superseded by"] == "None"
        _assert_supersession_cell(row["supersedes"])
        _assert_supersession_cell(row["superseded by"])


def test_postgresql_runtime_records_keep_published_digests() -> None:
    indexed = set(_postgresql_runtime_record_paths())

    assert indexed == set(POSTGRESQL_RUNTIME_DIGESTS)
    for relative, expected in POSTGRESQL_RUNTIME_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected


def test_postgresql_runtime_sources_and_plan_match_the_index() -> None:
    indexed = set(_postgresql_runtime_record_paths())
    control_plane_adr = (
        ROOT / "docs" / "decisions" / "0010-control-plane-externalization-postgres.md"
    ).read_text(encoding="utf-8")
    order_record = (ROOT / BV_ORDER_CANONICAL_PG_RECORD).read_text(encoding="utf-8")
    plan = DOCUMENTATION_PLAN.read_text(encoding="utf-8").lower()

    assert indexed == {CONTROL_PLANE_PG_RECORD, BV_ORDER_CANONICAL_PG_RECORD}
    assert CONTROL_PLANE_PG_RECORD in control_plane_adr
    assert "warehouse/agentflow/dv2/postgres/smoke/README.md" in order_record
    assert "postgresql runtime verification evidence sub-slice" in plan
    for digest in POSTGRESQL_RUNTIME_DIGESTS.values():
        assert digest in plan
    assert "пункт 5 остаётся открыт" in plan


def test_postgresql_runtime_results_and_boundaries_remain_conservative() -> None:
    rows = {_identity_path(row["identity"]): row for row in _postgresql_runtime_rows()}
    control_plane = _row_text(rows[CONTROL_PLANE_PG_RECORD])
    canonical_order = _row_text(rows[BV_ORDER_CANONICAL_PG_RECORD])
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))

    for phrase in CONTROL_PLANE_PG_FACTS:
        assert phrase in control_plane
    for phrase in CONTROL_PLANE_PG_BOUNDARIES:
        assert phrase in control_plane
    for phrase in BV_ORDER_CANONICAL_PG_FACTS:
        assert phrase in canonical_order
    for phrase in BV_ORDER_CANONICAL_PG_BOUNDARIES:
        assert phrase in canonical_order
    assert manifest["production"]["status"] == "candidate"


def test_nl_sql_evidence_index_lists_bounded_pair_with_required_fields() -> None:
    text = INDEX.read_text(encoding="utf-8")
    runtime_at = text.index(POSTGRESQL_RUNTIME_HEADING)
    nl_sql_at = text.index(NL_SQL_EVALUATION_HEADING)
    freshness_at = text.index(CURRENT_FRESHNESS_HEADING)
    indexed = _nl_sql_evaluation_record_paths()
    expected = (RULE_BASED_NL_SQL_RECORD, SONNET_5_NL_SQL_RECORD)
    rows = _nl_sql_evaluation_rows()

    assert runtime_at < nl_sql_at < freshness_at
    assert indexed == list(expected)
    assert Counter(indexed) == Counter(expected)
    assert list(rows[0]) == list(REQUIRED_FIELDS)
    assert len(rows) == 2
    for row in rows:
        for field in REQUIRED_FIELDS:
            assert row[field].strip(), f"{field} is empty in {row!r}"
        assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
        identity = _identity_path(row["identity"])
        assert row["date"] == NL_SQL_EVALUATION_DATES[identity]
        assert (ROOT / identity).is_file(), f"indexed identity is missing: {identity}"
        targets = LINK_RE.findall(row["identity"])
        assert targets[0].startswith("../perf/"), row["identity"]


def test_nl_sql_evidence_records_are_complementary_not_supersession() -> None:
    section = " ".join(
        _section(INDEX.read_text(encoding="utf-8"), NL_SQL_EVALUATION_HEADING).lower().split()
    )
    rows = _nl_sql_evaluation_rows()

    assert "complementary engine configurations" in section
    assert "not a supersession chain" in section
    assert "same 18-question harness" in section
    for row in rows:
        assert row["supersedes"] == "None"
        assert row["superseded by"] == "None"
        _assert_supersession_cell(row["supersedes"])
        _assert_supersession_cell(row["superseded by"])


def test_nl_sql_evidence_records_keep_published_digests() -> None:
    indexed = set(_nl_sql_evaluation_record_paths())

    assert indexed == set(NL_SQL_EVALUATION_DIGESTS)
    for relative, expected in NL_SQL_EVALUATION_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected


def test_nl_sql_evidence_source_links_and_plan_match_the_index() -> None:
    indexed = set(_nl_sql_evaluation_record_paths())
    adr = (ROOT / "docs" / "decisions" / "0008-adopt-nl-sql-engine.md").read_text(encoding="utf-8")
    baseline = (ROOT / RULE_BASED_NL_SQL_RECORD).read_text(encoding="utf-8")
    sonnet = (ROOT / SONNET_5_NL_SQL_RECORD).read_text(encoding="utf-8")
    plan = DOCUMENTATION_PLAN.read_text(encoding="utf-8").lower()

    assert indexed == {RULE_BASED_NL_SQL_RECORD, SONNET_5_NL_SQL_RECORD}
    assert SONNET_5_NL_SQL_RECORD in adr
    assert Path(SONNET_5_NL_SQL_RECORD).name in baseline
    assert Path(RULE_BASED_NL_SQL_RECORD).name in sonnet
    assert "nl→sql evaluation evidence pair sub-slice" in plan
    for digest in NL_SQL_EVALUATION_DIGESTS.values():
        assert digest in plan
    assert "пункт 5 остаётся открыт" in plan


def test_nl_sql_evidence_results_and_boundaries_remain_conservative() -> None:
    rows = {_identity_path(row["identity"]): row for row in _nl_sql_evaluation_rows()}
    rule_based = _row_text(rows[RULE_BASED_NL_SQL_RECORD])
    sonnet = _row_text(rows[SONNET_5_NL_SQL_RECORD])
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))

    for phrase in RULE_BASED_NL_SQL_FACTS:
        assert phrase in rule_based
    for phrase in RULE_BASED_NL_SQL_BOUNDARIES:
        assert phrase in rule_based
    for phrase in SONNET_5_NL_SQL_FACTS:
        assert phrase in sonnet
    for phrase in SONNET_5_NL_SQL_BOUNDARIES:
        assert phrase in sonnet
    assert manifest["production"]["status"] == "candidate"


def test_golden_acceptance_index_lists_the_bounded_pair_once() -> None:
    indexed = _acceptance_record_paths()
    expected = (
        SUBMISSION_RECORD,
        OPERATOR_RECORD,
        ICEBERG_RECORD,
        LAKE_TO_SERVING_RECORD,
    )

    assert set(indexed) == set(expected)
    assert Counter(indexed) == Counter(expected)
    assert len(indexed) == 4
    for relative in indexed:
        assert (ROOT / relative).is_file(), f"indexed identity is missing: {relative}"
    assert indexed[:2] == [SUBMISSION_RECORD, OPERATOR_RECORD]


def test_golden_acceptance_index_exposes_required_nonempty_fields() -> None:
    rows = _acceptance_rows()
    headers = list(rows[0])

    assert headers == list(REQUIRED_FIELDS)
    assert len(rows) == 4
    for row in rows:
        for field in REQUIRED_FIELDS:
            assert row[field].strip(), f"{field} is empty in {row!r}"
        assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
        identity = _identity_path(row["identity"])
        assert row["date"] == GOLDEN_ACCEPTANCE_DATES[identity]


def test_golden_acceptance_supersession_is_none() -> None:
    for row in _acceptance_rows():
        assert row.get("supersedes", "") == "None"
        assert row.get("superseded by", "") == "None"
        _assert_supersession_cell(row.get("supersedes", ""))
        _assert_supersession_cell(row.get("superseded by", ""))


def test_golden_acceptance_records_keep_published_digests() -> None:
    indexed = set(_acceptance_record_paths())

    assert indexed == set(GOLDEN_ACCEPTANCE_DIGESTS)
    for relative, expected in GOLDEN_ACCEPTANCE_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected


def test_golden_acceptance_claim_links_match_indexed_records() -> None:
    indexed = set(_acceptance_record_paths())
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))
    production = manifest["production"]
    status_links = _status_record_links()

    assert indexed == {
        SUBMISSION_RECORD,
        OPERATOR_RECORD,
        ICEBERG_RECORD,
        LAKE_TO_SERVING_RECORD,
    }
    assert production.get("verified_submission_smoke") == SUBMISSION_RECORD
    assert production.get("verified_operator_acceptance") == OPERATOR_RECORD
    assert production.get("verified_iceberg_materialization") == ICEBERG_RECORD
    assert production.get("verified_full_lake_to_serving_smoke") == LAKE_TO_SERVING_RECORD
    assert production.get("status") == "candidate"
    assert SUBMISSION_RECORD in manifest["required_evidence"]
    assert OPERATOR_RECORD in manifest["required_evidence"]
    assert ICEBERG_RECORD in manifest["required_evidence"]
    assert LAKE_TO_SERVING_RECORD in manifest["required_evidence"]
    assert SUBMISSION_RECORD in status_links
    assert OPERATOR_RECORD in status_links
    assert ICEBERG_RECORD in status_links
    assert LAKE_TO_SERVING_RECORD in status_links


def test_golden_acceptance_boundaries_remain_conservative() -> None:
    rows = {_identity_path(row["identity"]): row for row in _acceptance_rows()}
    submission = _row_text(rows[SUBMISSION_RECORD])
    operator = _row_text(rows[OPERATOR_RECORD])
    iceberg = _row_text(rows[ICEBERG_RECORD])
    lake_to_serving = _row_text(rows[LAKE_TO_SERVING_RECORD])

    assert "pass" in rows[SUBMISSION_RECORD]["result"].lower()
    assert "clean-checkout" in submission
    assert "oci" in submission
    assert "submission" in submission
    assert "running" in submission
    assert SUBMISSION_COMMIT in submission
    assert "pass" in rows[OPERATOR_RECORD]["result"].lower()
    assert "kind" in operator
    assert "operator" in operator
    assert "helm" in operator
    assert "hold" in operator
    assert OPERATOR_COMMIT in operator
    assert "pass" in rows[ICEBERG_RECORD]["result"].lower()
    assert "events.validated" in iceberg
    assert ICEBERG_RUNTIME in iceberg
    assert "lake materializer" in iceberg
    assert "iceberg" in iceberg
    assert "match_count=1" in iceberg
    assert OPERATOR_STAND in iceberg
    assert "pass" in rows[LAKE_TO_SERVING_RECORD]["result"].lower()
    assert "mixed-sha" in lake_to_serving
    assert "orders.raw" in lake_to_serving
    assert OPERATOR_STAND in lake_to_serving
    assert "pyflink" in lake_to_serving
    assert "events.validated" in lake_to_serving
    assert "iceberg" in lake_to_serving
    assert "bridge" in lake_to_serving
    assert "clickhouse" in lake_to_serving
    assert "task api" in lake_to_serving
    assert ICEBERG_RUNTIME in lake_to_serving
    for text in (submission, operator, iceberg, lake_to_serving):
        assert "does not claim" in text
        assert "candidate" in text
    for text in (submission, operator):
        for phrase in UNCLAIMED_BOUNDARIES:
            assert phrase in text
    for phrase in ICEBERG_UNCLAIMED_BOUNDARIES:
        assert phrase in iceberg
    for phrase in LAKE_TO_SERVING_UNCLAIMED_BOUNDARIES:
        assert phrase in lake_to_serving


def test_checkpoint_readiness_section_follows_golden_acceptance() -> None:
    text = INDEX.read_text(encoding="utf-8")
    golden_at = text.index(ACCEPTANCE_HEADING)
    checkpoint_at = text.index(CHECKPOINT_READINESS_HEADING)
    following_at = text.index("## F-10 rollback and soak-capacity records")

    assert golden_at < checkpoint_at < following_at


def test_checkpoint_readiness_index_lists_the_bounded_pair_once() -> None:
    indexed = _checkpoint_readiness_record_paths()
    expected = (CHECKPOINT_RECORD, READINESS_RECORD)

    assert set(indexed) == set(expected)
    assert Counter(indexed) == Counter(expected)
    assert len(indexed) == 2
    for relative in indexed:
        assert (ROOT / relative).is_file(), f"indexed identity is missing: {relative}"
    assert indexed == [CHECKPOINT_RECORD, READINESS_RECORD]
    for row in _checkpoint_readiness_rows():
        targets = LINK_RE.findall(row["identity"])
        assert targets[0].startswith("../perf/"), row["identity"]


def test_checkpoint_readiness_index_exposes_required_nonempty_fields() -> None:
    rows = _checkpoint_readiness_rows()
    headers = list(rows[0])

    assert headers == list(REQUIRED_FIELDS)
    assert len(rows) == 2
    for row in rows:
        for field in REQUIRED_FIELDS:
            assert row[field].strip(), f"{field} is empty in {row!r}"
        assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
        identity = _identity_path(row["identity"])
        assert row["date"] == CHECKPOINT_READINESS_DATES[identity]


def test_checkpoint_readiness_supersession_direction() -> None:
    rows = {_identity_path(row["identity"]): row for row in _checkpoint_readiness_rows()}
    checkpoint = rows[CHECKPOINT_RECORD]
    readiness = rows[READINESS_RECORD]
    supersedes_targets = LINK_RE.findall(checkpoint["supersedes"])

    assert [_resolve_index_link(target) for target in supersedes_targets] == [
        CHECKPOINT_BLOCKER_RECORD
    ]
    assert supersedes_targets[0].startswith("../perf/")
    assert checkpoint["superseded by"] == "None"
    assert readiness["supersedes"] == "None"
    assert readiness["superseded by"] == "None"
    _assert_supersession_cell(checkpoint["supersedes"])
    _assert_supersession_cell(checkpoint["superseded by"])
    _assert_supersession_cell(readiness["supersedes"])
    _assert_supersession_cell(readiness["superseded by"])
    for cell in (readiness["supersedes"], readiness["superseded by"]):
        resolved = [_resolve_index_link(target) for target in LINK_RE.findall(cell)]
        assert CHECKPOINT_RECORD not in resolved
        assert CHECKPOINT_BLOCKER_RECORD not in resolved
        assert CANARY_TRAFFIC_RECORD not in resolved


def test_checkpoint_readiness_records_keep_published_digests() -> None:
    indexed = set(_checkpoint_readiness_record_paths())

    assert indexed == set(CHECKPOINT_READINESS_DIGESTS)
    for relative, expected in CHECKPOINT_READINESS_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    blocker_digest = hashlib.sha256((ROOT / CHECKPOINT_BLOCKER_RECORD).read_bytes()).hexdigest()
    assert blocker_digest == CHECKPOINT_BLOCKER_DIGEST
    for relative, expected in PROTECTED_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    for relative, expected in GOLDEN_ACCEPTANCE_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected


def test_checkpoint_readiness_claim_links_match_indexed_records() -> None:
    indexed = set(_checkpoint_readiness_record_paths())
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))
    production = manifest["production"]
    status_links = _status_record_links()

    assert indexed == {CHECKPOINT_RECORD, READINESS_RECORD}
    assert production.get("verified_checkpoint_restore_replay") == CHECKPOINT_RECORD
    assert production.get("verified_ready_baselined_checkpoint_hold") == (READINESS_RECORD)
    assert production.get("latest_soak_recovery_evidence") == READINESS_RECORD
    assert production.get("status") == "candidate"
    assert CHECKPOINT_RECORD in manifest["required_evidence"]
    assert READINESS_RECORD in manifest["required_evidence"]
    assert CHECKPOINT_RECORD in status_links
    assert READINESS_RECORD in status_links


def test_checkpoint_readiness_boundaries_remain_conservative() -> None:
    rows = {_identity_path(row["identity"]): row for row in _checkpoint_readiness_rows()}
    checkpoint = _row_text(rows[CHECKPOINT_RECORD])
    readiness = _row_text(rows[READINESS_RECORD])

    assert "pass" in rows[CHECKPOINT_RECORD]["result"].lower()
    assert "isolated" in checkpoint
    assert "checkpoint" in checkpoint
    assert "savepoint" in checkpoint
    assert "restore" in checkpoint
    assert CHECKPOINT_RUNTIME in checkpoint
    assert "byte-identical" in checkpoint
    assert "e1" in checkpoint
    assert "e2" in checkpoint
    assert "kafka validated" in checkpoint
    assert "iceberg" in checkpoint
    assert "clickhouse" in checkpoint
    assert "api" in checkpoint
    assert "dlq" in checkpoint
    assert "lag" in checkpoint
    assert CHECKPOINT_TTL_SECONDS in checkpoint
    assert "runtime_hold_pass" in rows[READINESS_RECORD]["result"].lower()
    assert READINESS_HOLD_SECONDS in readiness
    assert "readiness-baselined" in readiness
    assert "read-only" in readiness
    assert "no-traffic" in readiness
    assert "already-running" in readiness
    assert READINESS_COMPLETED_FROM in readiness
    assert READINESS_COMPLETED_TO in readiness
    assert "failed checkpoints 1 to 1" in readiness
    assert STARTUP_FAILURE_CAUSE.lower() in readiness
    assert "does not claim" in checkpoint
    assert "does not prove" in readiness
    assert "candidate" in checkpoint
    assert "candidate" in readiness
    assert "canary" in readiness
    assert "latest traffic" in readiness
    for phrase in CHECKPOINT_UNCLAIMED_BOUNDARIES:
        assert phrase in checkpoint
    for phrase in READINESS_UNCLAIMED_BOUNDARIES:
        assert phrase in readiness


def test_f10_section_follows_checkpoint_readiness() -> None:
    text = INDEX.read_text(encoding="utf-8")
    checkpoint_at = text.index(CHECKPOINT_READINESS_HEADING)
    f10_at = text.index(F10_HEADING)

    assert checkpoint_at < f10_at


def test_f10_section_keeps_root_path_stability() -> None:
    section = _section(INDEX.read_text(encoding="utf-8"), F10_HEADING)

    assert "`docs/STATUS.md`" in section
    assert "`docs/PROJECT_CLOSURE.md`" in section
    assert "`config/project_claims.toml`" in section
    assert "root-path stability" in section
    assert "not new evidence under `docs/evidence/`" in section


def test_f10_index_lists_the_bounded_pair_once() -> None:
    indexed = _f10_record_paths()
    expected = (ROLLBACK_RECORD, SOAK_CAPACITY_RECORD)

    assert set(indexed) == set(expected)
    assert Counter(indexed) == Counter(expected)
    assert len(indexed) == 2
    for relative in indexed:
        assert (ROOT / relative).is_file(), f"indexed identity is missing: {relative}"
    assert indexed == [ROLLBACK_RECORD, SOAK_CAPACITY_RECORD]
    for row in _f10_rows():
        targets = LINK_RE.findall(row["identity"])
        assert targets[0].startswith("../../"), row["identity"]


def test_f10_index_exposes_required_nonempty_fields() -> None:
    rows = _f10_rows()
    headers = list(rows[0])

    assert headers == list(REQUIRED_FIELDS)
    assert len(rows) == 2
    for row in rows:
        for field in REQUIRED_FIELDS:
            assert row[field].strip(), f"{field} is empty in {row!r}"
        assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
        identity = _identity_path(row["identity"])
        assert row["date"] == F10_DATES[identity]


def test_f10_supersession_is_none() -> None:
    rows = {_identity_path(row["identity"]): row for row in _f10_rows()}
    rollback = rows[ROLLBACK_RECORD]
    soak = rows[SOAK_CAPACITY_RECORD]

    assert rollback["supersedes"] == "None"
    assert rollback["superseded by"] == "None"
    assert soak["supersedes"] == "None"
    assert soak["superseded by"] == "None"
    for row in (rollback, soak):
        _assert_supersession_cell(row["supersedes"])
        _assert_supersession_cell(row["superseded by"])
        resolved_supersedes = [
            _resolve_index_link(target) for target in LINK_RE.findall(row["supersedes"])
        ]
        resolved_superseded_by = [
            _resolve_index_link(target) for target in LINK_RE.findall(row["superseded by"])
        ]
        assert ROLLBACK_RECORD not in resolved_supersedes
        assert SOAK_CAPACITY_RECORD not in resolved_supersedes
        assert ROLLBACK_RECORD not in resolved_superseded_by
        assert SOAK_CAPACITY_RECORD not in resolved_superseded_by


def test_f10_records_keep_published_digests() -> None:
    indexed = set(_f10_record_paths())

    assert indexed == set(F10_DIGESTS)
    for relative, expected in F10_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    for relative, expected in PROTECTED_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    for relative, expected in GOLDEN_ACCEPTANCE_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    for relative, expected in CHECKPOINT_READINESS_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    blocker_digest = hashlib.sha256((ROOT / CHECKPOINT_BLOCKER_RECORD).read_bytes()).hexdigest()
    assert blocker_digest == CHECKPOINT_BLOCKER_DIGEST


def test_f10_claim_links_match_indexed_records() -> None:
    indexed = set(_f10_record_paths())
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))
    production = manifest["production"]
    status_links = _status_record_links()
    closure_links = _project_closure_record_links()

    assert indexed == {ROLLBACK_RECORD, SOAK_CAPACITY_RECORD}
    assert production.get("rollback_mechanics_evidence") == ROLLBACK_RECORD
    assert production.get("rollback_mechanics") == "PASS"
    assert production.get("full_soak_plus_rollback_after_traffic_evidence") == (
        SOAK_CAPACITY_RECORD
    )
    assert production.get("full_soak_plus_rollback_after_traffic") == ("BLOCKED_HOST_CAPACITY")
    assert production.get("status") == "candidate"
    assert ROLLBACK_RECORD in manifest["required_evidence"]
    assert SOAK_CAPACITY_RECORD in manifest["required_evidence"]
    assert ROLLBACK_RECORD in status_links
    assert SOAK_CAPACITY_RECORD in status_links
    assert ROLLBACK_RECORD in closure_links
    assert SOAK_CAPACITY_RECORD in closure_links


def test_f10_boundaries_remain_conservative() -> None:
    rows = {_identity_path(row["identity"]): row for row in _f10_rows()}
    rollback = _row_text(rows[ROLLBACK_RECORD])
    soak = _row_text(rows[SOAK_CAPACITY_RECORD])

    assert "pass" in rows[ROLLBACK_RECORD]["result"].lower()
    assert "rev5" in rollback
    assert "rev6" in rollback
    assert "byte-identical" in rollback
    assert "rev3" in rollback
    assert "no traffic" in rollback
    assert "blocked_host_capacity" in rows[SOAK_CAPACITY_RECORD]["result"].lower()
    assert "f-02" in soak
    assert "r17" in soak
    assert "pass" not in rows[SOAK_CAPACITY_RECORD]["result"].lower()
    assert "does not claim" in rollback
    assert "does not claim" in soak
    assert "candidate" in rollback
    assert "candidate" in soak
    for phrase in F10_SHARED_UNCLAIMED_BOUNDARIES:
        assert phrase in rollback
        assert phrase in soak


def test_kind_soak_section_follows_checkpoint_readiness() -> None:
    text = INDEX.read_text(encoding="utf-8")
    assert KIND_SOAK_HEADING in text
    checkpoint_at = text.index(CHECKPOINT_READINESS_HEADING)
    kind_soak_at = text.index(KIND_SOAK_HEADING)
    f10_at = text.index(F10_HEADING)

    assert checkpoint_at < kind_soak_at < f10_at


def test_kind_soak_index_lists_the_bounded_pair_once() -> None:
    indexed = _kind_soak_record_paths()
    expected = (KIND_RESIDUAL_RECORD, SOAK_05_RECORD)

    assert set(indexed) == set(expected)
    assert Counter(indexed) == Counter(expected)
    assert len(indexed) == 2
    for relative in indexed:
        assert (ROOT / relative).is_file(), f"indexed identity is missing: {relative}"
    assert indexed == [KIND_RESIDUAL_RECORD, SOAK_05_RECORD]
    for row in _kind_soak_rows():
        targets = LINK_RE.findall(row["identity"])
        assert targets[0].startswith("../perf/"), row["identity"]


def test_kind_soak_index_exposes_required_nonempty_fields() -> None:
    rows = _kind_soak_rows()
    headers = list(rows[0])

    assert headers == list(REQUIRED_FIELDS)
    assert len(rows) == 2
    for row in rows:
        for field in REQUIRED_FIELDS:
            assert row[field].strip(), f"{field} is empty in {row!r}"
        assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
        identity = _identity_path(row["identity"])
        assert row["date"] == KIND_SOAK_DATES[identity]


def test_kind_soak_supersession_direction() -> None:
    rows = {_identity_path(row["identity"]): row for row in _kind_soak_rows()}
    canary = rows[KIND_RESIDUAL_RECORD]
    soak = rows[SOAK_05_RECORD]
    soak_supersedes_targets = LINK_RE.findall(soak["supersedes"])

    assert canary["supersedes"] == "None"
    assert canary["superseded by"] == "None"
    assert [_resolve_index_link(target) for target in soak_supersedes_targets] == [
        SOAK_START_RECORD
    ]
    assert soak_supersedes_targets[0].startswith("../perf/")
    assert soak["superseded by"] == "None"
    _assert_supersession_cell(canary["supersedes"])
    _assert_supersession_cell(canary["superseded by"])
    _assert_supersession_cell(soak["supersedes"])
    _assert_supersession_cell(soak["superseded by"])
    for cell in (canary["supersedes"], canary["superseded by"]):
        resolved = [_resolve_index_link(target) for target in LINK_RE.findall(cell)]
        assert CANARY_TRAFFIC_RECORD not in resolved
        assert SOAK_05_RECORD not in resolved
        assert SOAK_START_RECORD not in resolved
    soak_supersedes = [
        _resolve_index_link(target) for target in LINK_RE.findall(soak["supersedes"])
    ]
    soak_superseded_by = [
        _resolve_index_link(target) for target in LINK_RE.findall(soak["superseded by"])
    ]
    assert KIND_RESIDUAL_RECORD not in soak_supersedes
    assert CANARY_TRAFFIC_RECORD not in soak_supersedes
    assert KIND_RESIDUAL_RECORD not in soak_superseded_by
    assert CANARY_TRAFFIC_RECORD not in soak_superseded_by
    assert SOAK_START_RECORD not in soak_superseded_by


def test_kind_soak_records_keep_published_digests() -> None:
    indexed = set(_kind_soak_record_paths())

    assert indexed == set(KIND_SOAK_DIGESTS)
    for relative, expected in KIND_SOAK_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    start_digest = hashlib.sha256((ROOT / SOAK_START_RECORD).read_bytes()).hexdigest()
    assert start_digest == SOAK_START_DIGEST
    canary_fail_digest = hashlib.sha256((ROOT / CANARY_TRAFFIC_RECORD).read_bytes()).hexdigest()
    assert canary_fail_digest == CANARY_TRAFFIC_DIGEST
    for relative, expected in PROTECTED_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    for relative, expected in GOLDEN_ACCEPTANCE_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    for relative, expected in CHECKPOINT_READINESS_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    blocker_digest = hashlib.sha256((ROOT / CHECKPOINT_BLOCKER_RECORD).read_bytes()).hexdigest()
    assert blocker_digest == CHECKPOINT_BLOCKER_DIGEST
    for relative, expected in F10_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected


def test_kind_soak_claim_links_match_indexed_records() -> None:
    indexed = set(_kind_soak_record_paths())
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))
    production = manifest["production"]
    status_links = _status_record_links()
    closure_links = _project_closure_record_links()

    assert indexed == {KIND_RESIDUAL_RECORD, SOAK_05_RECORD}
    assert production.get("latest_kind_residual_canary") == KIND_RESIDUAL_RECORD
    assert production.get("latest_kind_residual_canary_result") == (
        "pass-residual-7p51s-budget-20s"
    )
    assert production.get("latest_soak_attempt") == SOAK_05_RECORD
    assert production.get("latest_soak_attempt_result") == (
        "soak-fail-unresolved-flink-terminal-failure"
    )
    assert production.get("status") == "candidate"
    assert KIND_RESIDUAL_RECORD in manifest["required_evidence"]
    assert SOAK_05_RECORD in manifest["required_evidence"]
    assert SOAK_START_RECORD in manifest["required_evidence"]
    assert KIND_RESIDUAL_RECORD in status_links
    assert SOAK_05_RECORD in status_links
    assert SOAK_05_RECORD in closure_links


def test_kind_soak_boundaries_remain_conservative() -> None:
    rows = {_identity_path(row["identity"]): row for row in _kind_soak_rows()}
    canary = _row_text(rows[KIND_RESIDUAL_RECORD])
    soak = _row_text(rows[SOAK_05_RECORD])

    assert "pass_kind_residual_20" in rows[KIND_RESIDUAL_RECORD]["result"].lower()
    assert "d+c1-20" in canary
    assert "7.5127 s" in canary
    assert "20 s" in canary
    assert "2000/2000" in canary
    assert "dlq" in canary
    assert "lag" in canary
    assert "applied_mean_eps=77.9059" in canary
    assert "does not claim" in canary
    assert "candidate" in canary
    assert "soak_fail" in rows[SOAK_05_RECORD]["result"].lower()
    assert "-05" in rows[SOAK_05_RECORD]["result"].lower()
    assert "1,440,000/1,440,000" in soak
    assert "zero producer failures" in soak
    assert "99.99979" in soak
    assert "failed" in soak
    assert "flink" in soak
    assert "pass json" in soak
    assert "rollback" in soak
    assert "not started" in soak
    assert "unresolved_flink_terminal_failure" in soak
    assert "evidence-retention" in soak
    assert "topology abort" in soak
    assert "does not claim" in soak
    assert "candidate" in soak
    assert "combined gate" in soak
    assert "open" in soak
    for phrase in KIND_RESIDUAL_UNCLAIMED_BOUNDARIES:
        assert phrase in canary
    for phrase in SOAK_UNCLAIMED_BOUNDARIES:
        assert phrase in soak


def test_golden_soak_rca_index_lists_one_bounded_record() -> None:
    text = INDEX.read_text(encoding="utf-8")
    kind_soak_at = text.index(KIND_SOAK_HEADING)
    rca_at = text.index(SOAK_RCA_HEADING)
    f10_at = text.index(F10_HEADING)
    rows = _soak_rca_rows()
    indexed = _soak_rca_record_paths()

    assert kind_soak_at < rca_at < f10_at
    assert indexed == [SOAK_RCA_RECORD]
    assert Counter(indexed) == Counter((SOAK_RCA_RECORD,))
    assert len(rows) == 1
    row = rows[0]
    assert list(row) == list(REQUIRED_FIELDS)
    for field in REQUIRED_FIELDS:
        assert row[field].strip(), f"{field} is empty in {row!r}"
    assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
    assert row["date"] == SOAK_RCA_DATE
    assert (ROOT / SOAK_RCA_RECORD).is_file()
    targets = LINK_RE.findall(row["identity"])
    assert targets[0].startswith("../perf/"), row["identity"]


def test_golden_soak_rca_complements_soak_05_without_supersession() -> None:
    section = _section(INDEX.read_text(encoding="utf-8"), SOAK_RCA_HEADING)
    section_text = " ".join(section.lower().split())
    row = _soak_rca_rows()[0]
    resolved_links = {_resolve_index_link(target) for target in LINK_RE.findall(section)}

    assert "complementary" in section_text
    assert "does not supersede" in section_text
    assert resolved_links == {SOAK_RCA_RECORD, SOAK_05_RECORD}
    assert row["supersedes"] == "None"
    assert row["superseded by"] == "None"
    _assert_supersession_cell(row["supersedes"])
    _assert_supersession_cell(row["superseded by"])


def test_golden_soak_rca_record_keeps_published_digest() -> None:
    assert _soak_rca_record_paths() == [SOAK_RCA_RECORD]
    digest = hashlib.sha256((ROOT / SOAK_RCA_RECORD).read_bytes()).hexdigest()
    assert digest == SOAK_RCA_DIGEST


def test_golden_soak_rca_sources_and_plan_match_the_index() -> None:
    assert _soak_rca_record_paths() == [SOAK_RCA_RECORD]
    retention = (ROOT / "flink-failure-evidence-retention.md").read_text(encoding="utf-8")
    policy = (ROOT / "scripts" / "soak_observer_policy.py").read_text(encoding="utf-8")
    policy_tests = (ROOT / "tests" / "unit" / "test_soak_observer_policy.py").read_text(
        encoding="utf-8"
    )
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))
    plan = DOCUMENTATION_PLAN.read_text(encoding="utf-8").lower()

    assert SOAK_RCA_RECORD in retention
    assert SOAK_RCA_RECORD in policy
    assert SOAK_RCA_RECORD in policy_tests
    assert manifest["production"]["latest_soak_attempt"] == SOAK_05_RECORD
    assert SOAK_RCA_RECORD not in manifest["required_evidence"]
    assert "golden soak cross-run rca evidence sub-slice" in plan
    assert SOAK_RCA_DIGEST in plan
    assert "пункт 5 остаётся открыт" in plan


def test_golden_soak_rca_result_and_boundary_remain_conservative() -> None:
    row = _soak_rca_rows()[0]
    row_text = _row_text(row)
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))

    for phrase in SOAK_RCA_FACTS:
        assert phrase in row_text
    for phrase in SOAK_RCA_BOUNDARIES:
        assert phrase in row_text
    assert manifest["production"]["status"] == "candidate"


def test_historical_canary_soak_section_follows_checkpoint_readiness() -> None:
    text = INDEX.read_text(encoding="utf-8")
    assert HISTORICAL_CANARY_SOAK_HEADING in text
    checkpoint_at = text.index(CHECKPOINT_READINESS_HEADING)
    historical_at = text.index(HISTORICAL_CANARY_SOAK_HEADING)
    kind_soak_at = text.index(KIND_SOAK_HEADING)
    f10_at = text.index(F10_HEADING)

    assert checkpoint_at < historical_at < kind_soak_at < f10_at


def test_historical_canary_soak_index_lists_the_bounded_pair_once() -> None:
    indexed = _historical_canary_soak_record_paths()
    expected = (CANARY_TRAFFIC_RECORD, SOAK_START_RECORD)

    assert set(indexed) == set(expected)
    assert Counter(indexed) == Counter(expected)
    assert len(indexed) == 2
    for relative in indexed:
        assert (ROOT / relative).is_file(), f"indexed identity is missing: {relative}"
    assert indexed == [CANARY_TRAFFIC_RECORD, SOAK_START_RECORD]
    assert KIND_RESIDUAL_RECORD not in indexed
    assert SOAK_05_RECORD not in indexed
    assert RESOURCE_BLOCKER_RECORD not in indexed
    assert CANARY_TRAFFIC_RECORD not in _kind_soak_record_paths()
    assert SOAK_START_RECORD not in _kind_soak_record_paths()
    for row in _historical_canary_soak_rows():
        targets = LINK_RE.findall(row["identity"])
        assert targets[0].startswith("../perf/"), row["identity"]


def test_historical_canary_soak_index_exposes_required_nonempty_fields() -> None:
    rows = _historical_canary_soak_rows()
    headers = list(rows[0])

    assert headers == list(REQUIRED_FIELDS)
    assert len(rows) == 2
    for row in rows:
        for field in REQUIRED_FIELDS:
            assert row[field].strip(), f"{field} is empty in {row!r}"
        assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
        identity = _identity_path(row["identity"])
        assert row["date"] == HISTORICAL_CANARY_SOAK_DATES[identity]


def test_historical_canary_soak_supersession_direction() -> None:
    rows = {_identity_path(row["identity"]): row for row in _historical_canary_soak_rows()}
    canary = rows[CANARY_TRAFFIC_RECORD]
    start = rows[SOAK_START_RECORD]
    canary_supersedes_targets = LINK_RE.findall(canary["supersedes"])
    start_superseded_by_targets = LINK_RE.findall(start["superseded by"])
    kind_soak_rows = {_identity_path(row["identity"]): row for row in _kind_soak_rows()}
    soak05 = kind_soak_rows[SOAK_05_RECORD]
    soak05_supersedes_targets = LINK_RE.findall(soak05["supersedes"])

    assert [_resolve_index_link(target) for target in canary_supersedes_targets] == [
        RESOURCE_BLOCKER_RECORD
    ]
    assert canary_supersedes_targets[0].startswith("../perf/")
    assert canary["superseded by"] == "None"
    assert start["supersedes"] == "None"
    assert [_resolve_index_link(target) for target in start_superseded_by_targets] == [
        SOAK_05_RECORD
    ]
    assert start_superseded_by_targets[0].startswith("../perf/")
    assert [_resolve_index_link(target) for target in soak05_supersedes_targets] == [
        SOAK_START_RECORD
    ]
    _assert_supersession_cell(canary["supersedes"])
    _assert_supersession_cell(canary["superseded by"])
    _assert_supersession_cell(start["supersedes"])
    _assert_supersession_cell(start["superseded by"])
    canary_supersedes = [
        _resolve_index_link(target) for target in LINK_RE.findall(canary["supersedes"])
    ]
    canary_superseded_by = [
        _resolve_index_link(target) for target in LINK_RE.findall(canary["superseded by"])
    ]
    start_supersedes = [
        _resolve_index_link(target) for target in LINK_RE.findall(start["supersedes"])
    ]
    start_superseded_by = [
        _resolve_index_link(target) for target in LINK_RE.findall(start["superseded by"])
    ]
    assert KIND_RESIDUAL_RECORD not in canary_supersedes
    assert KIND_RESIDUAL_RECORD not in canary_superseded_by
    assert SOAK_05_RECORD not in canary_supersedes
    assert SOAK_05_RECORD not in canary_superseded_by
    assert SOAK_START_RECORD not in canary_supersedes
    assert SOAK_START_RECORD not in canary_superseded_by
    assert KIND_RESIDUAL_RECORD not in start_supersedes
    assert KIND_RESIDUAL_RECORD not in start_superseded_by
    assert CANARY_TRAFFIC_RECORD not in start_supersedes
    assert CANARY_TRAFFIC_RECORD not in start_superseded_by
    assert RESOURCE_BLOCKER_RECORD not in start_supersedes
    assert RESOURCE_BLOCKER_RECORD not in start_superseded_by
    assert SOAK_START_RECORD not in start_supersedes
    assert CANARY_TRAFFIC_RECORD not in [
        _resolve_index_link(target) for target in soak05_supersedes_targets
    ]


def test_historical_canary_soak_records_keep_published_digests() -> None:
    indexed = set(_historical_canary_soak_record_paths())

    assert indexed == set(HISTORICAL_CANARY_SOAK_DIGESTS)
    for relative, expected in HISTORICAL_CANARY_SOAK_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    blocker_digest = hashlib.sha256((ROOT / RESOURCE_BLOCKER_RECORD).read_bytes()).hexdigest()
    assert blocker_digest == RESOURCE_BLOCKER_DIGEST
    soak05_digest = hashlib.sha256((ROOT / SOAK_05_RECORD).read_bytes()).hexdigest()
    assert soak05_digest == KIND_SOAK_DIGESTS[SOAK_05_RECORD]
    kind_residual_digest = hashlib.sha256((ROOT / KIND_RESIDUAL_RECORD).read_bytes()).hexdigest()
    assert kind_residual_digest == KIND_SOAK_DIGESTS[KIND_RESIDUAL_RECORD]
    for relative, expected in PROTECTED_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    for relative, expected in GOLDEN_ACCEPTANCE_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    for relative, expected in CHECKPOINT_READINESS_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    checkpoint_blocker_digest = hashlib.sha256(
        (ROOT / CHECKPOINT_BLOCKER_RECORD).read_bytes()
    ).hexdigest()
    assert checkpoint_blocker_digest == CHECKPOINT_BLOCKER_DIGEST
    for relative, expected in F10_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected


def test_historical_canary_soak_claim_links_match_indexed_records() -> None:
    indexed = set(_historical_canary_soak_record_paths())
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))
    production = manifest["production"]
    status_links = _status_record_links()
    closure_links = _project_closure_record_links()

    assert indexed == {CANARY_TRAFFIC_RECORD, SOAK_START_RECORD}
    assert CANARY_TRAFFIC_RECORD in manifest["required_evidence"]
    assert SOAK_START_RECORD in manifest["required_evidence"]
    assert production.get("latest_kind_residual_canary") == KIND_RESIDUAL_RECORD
    assert production.get("latest_kind_residual_canary") != CANARY_TRAFFIC_RECORD
    assert production.get("latest_soak_attempt") == SOAK_05_RECORD
    assert production.get("latest_soak_attempt") != SOAK_START_RECORD
    assert production.get("status") == "candidate"
    assert CANARY_TRAFFIC_RECORD not in status_links
    assert SOAK_START_RECORD not in status_links
    assert CANARY_TRAFFIC_RECORD not in closure_links
    assert SOAK_START_RECORD not in closure_links
    assert KIND_RESIDUAL_RECORD in status_links
    assert SOAK_05_RECORD in status_links


def test_historical_canary_soak_boundaries_remain_conservative() -> None:
    rows = {_identity_path(row["identity"]): row for row in _historical_canary_soak_rows()}
    canary = _row_text(rows[CANARY_TRAFFIC_RECORD])
    start = _row_text(rows[SOAK_START_RECORD])
    section = _section(INDEX.read_text(encoding="utf-8"), HISTORICAL_CANARY_SOAK_HEADING).lower()

    assert "fail_canary_catchup_rate_floor" in rows[CANARY_TRAFFIC_RECORD]["result"].lower()
    assert "2,000/2,000" in canary
    assert "zero failures" in canary
    assert "88.715123" in canary
    assert "1092/2000" in canary
    assert "546/2000" in canary
    assert "no verifier pass" in canary
    assert "observer" in canary
    assert "not started" in canary
    assert "latest attempt state" in canary or "latest attempt state" in section
    assert "preflight" in canary or "preflight" in section
    assert "does not claim" in canary
    assert "candidate" in canary
    assert "soak_running" in rows[SOAK_START_RECORD]["result"].lower()
    assert "not pass" in rows[SOAK_START_RECORD]["result"].lower()
    assert "golden-4h-soak-rv-20260807-01" in rows[SOAK_START_RECORD]["result"].lower()
    assert "1,440,000" in start
    assert "100" in start
    assert "dual_mean_90" in start
    assert "72k" in start
    assert "observer" in start
    assert "producer" in start
    assert "verifier" in start
    assert "rollback" in start
    assert "not started" in start
    assert "does not claim" in start
    assert "candidate" in start
    assert "current" in start
    assert "outcome" in start
    assert "soak-05" in start or "-05" in start
    assert "not a pass chain" in section
    for phrase in CANARY_FAILURE_UNCLAIMED_BOUNDARIES:
        assert phrase in canary
    for phrase in SOAK_START_UNCLAIMED_BOUNDARIES:
        assert phrase in start


def test_historical_capacity_blockers_section_precedes_current_outcomes() -> None:
    text = INDEX.read_text(encoding="utf-8")
    golden_at = text.index(ACCEPTANCE_HEADING)
    blockers_at = text.index(HISTORICAL_CAPACITY_BLOCKERS_HEADING)
    checkpoint_at = text.index(CHECKPOINT_READINESS_HEADING)
    canary_at = text.index(HISTORICAL_CANARY_SOAK_HEADING)

    assert golden_at < blockers_at < checkpoint_at < canary_at


def test_historical_capacity_blockers_index_lists_the_bounded_pair_once() -> None:
    indexed = _historical_capacity_blocker_record_paths()
    expected = (CHECKPOINT_BLOCKER_RECORD, RESOURCE_BLOCKER_RECORD)

    assert set(indexed) == set(expected)
    assert Counter(indexed) == Counter(expected)
    assert len(indexed) == 2
    assert indexed == list(expected)
    for relative in indexed:
        assert (ROOT / relative).is_file(), f"indexed identity is missing: {relative}"
    for row in _historical_capacity_blocker_rows():
        targets = LINK_RE.findall(row["identity"])
        assert targets[0].startswith("../perf/"), row["identity"]


def test_historical_capacity_blockers_expose_required_nonempty_fields() -> None:
    rows = _historical_capacity_blocker_rows()
    headers = list(rows[0])

    assert headers == list(REQUIRED_FIELDS)
    assert len(rows) == 2
    for row in rows:
        for field in REQUIRED_FIELDS:
            assert row[field].strip(), f"{field} is empty in {row!r}"
        assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
        identity = _identity_path(row["identity"])
        assert row["date"] == HISTORICAL_CAPACITY_BLOCKER_DATES[identity]


def test_historical_capacity_blockers_supersession_is_reciprocal() -> None:
    blockers = {_identity_path(row["identity"]): row for row in _historical_capacity_blocker_rows()}
    checkpoint_blocker = blockers[CHECKPOINT_BLOCKER_RECORD]
    soak_resource_blocker = blockers[RESOURCE_BLOCKER_RECORD]
    checkpoint = {_identity_path(row["identity"]): row for row in _checkpoint_readiness_rows()}[
        CHECKPOINT_RECORD
    ]
    canary = {_identity_path(row["identity"]): row for row in _historical_canary_soak_rows()}[
        CANARY_TRAFFIC_RECORD
    ]

    assert checkpoint_blocker["supersedes"] == "None"
    assert soak_resource_blocker["supersedes"] == "None"
    assert [
        _resolve_index_link(target)
        for target in LINK_RE.findall(checkpoint_blocker["superseded by"])
    ] == [CHECKPOINT_RECORD]
    assert [
        _resolve_index_link(target)
        for target in LINK_RE.findall(soak_resource_blocker["superseded by"])
    ] == [CANARY_TRAFFIC_RECORD]
    assert [
        _resolve_index_link(target) for target in LINK_RE.findall(checkpoint["supersedes"])
    ] == [CHECKPOINT_BLOCKER_RECORD]
    assert [_resolve_index_link(target) for target in LINK_RE.findall(canary["supersedes"])] == [
        RESOURCE_BLOCKER_RECORD
    ]
    for row in (checkpoint_blocker, soak_resource_blocker):
        _assert_supersession_cell(row["supersedes"])
        _assert_supersession_cell(row["superseded by"])


def test_historical_capacity_blockers_keep_published_digests() -> None:
    indexed = set(_historical_capacity_blocker_record_paths())

    assert indexed == set(HISTORICAL_CAPACITY_BLOCKER_DIGESTS)
    for relative, expected in HISTORICAL_CAPACITY_BLOCKER_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected


def test_historical_capacity_blocker_boundaries_remain_conservative() -> None:
    rows = {_identity_path(row["identity"]): row for row in _historical_capacity_blocker_rows()}
    checkpoint = _row_text(rows[CHECKPOINT_BLOCKER_RECORD])
    soak = _row_text(rows[RESOURCE_BLOCKER_RECORD])

    assert "unsafe_capacity" in rows[CHECKPOINT_BLOCKER_RECORD]["result"].lower()
    assert "blocked_before_mutation" in checkpoint
    assert "insufficient_non_protected_reclaim" in checkpoint
    assert "not accepted" in checkpoint
    assert "historical" in checkpoint
    assert "health evidence" in checkpoint
    assert "only for the restore/replay gate" in checkpoint
    assert "candidate" in checkpoint
    assert "blocked_resource_capacity" in rows[RESOURCE_BLOCKER_RECORD]["result"].lower()
    assert "not started" in soak
    assert "historical" in soak
    assert "preflight remains valid" in soak
    assert "health evidence" in soak
    assert "only as the latest attempt state" in soak
    assert "candidate" in soak
    for phrase in CHECKPOINT_BLOCKER_UNCLAIMED_BOUNDARIES:
        assert phrase in checkpoint
    for phrase in SOAK_RESOURCE_BLOCKER_UNCLAIMED_BOUNDARIES:
        assert phrase in soak


def test_historical_streaming_hop_index_lists_one_bounded_record() -> None:
    text = INDEX.read_text(encoding="utf-8")
    nl_sql_at = text.index(NL_SQL_EVALUATION_HEADING)
    historical_at = text.index(HISTORICAL_STREAMING_HOP_HEADING)
    current_at = text.index(CURRENT_FRESHNESS_HEADING)
    indexed = _historical_streaming_hop_record_paths()
    rows = _historical_streaming_hop_rows()

    assert nl_sql_at < historical_at < current_at
    assert indexed == [HISTORICAL_STREAMING_HOP_RECORD]
    assert Counter(indexed) == Counter((HISTORICAL_STREAMING_HOP_RECORD,))
    assert list(rows[0]) == list(REQUIRED_FIELDS)
    assert len(rows) == 1
    row = rows[0]
    for field in REQUIRED_FIELDS:
        assert row[field].strip(), f"{field} is empty in {row!r}"
    assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
    assert row["date"] == HISTORICAL_STREAMING_HOP_DATE
    assert (ROOT / HISTORICAL_STREAMING_HOP_RECORD).is_file()
    targets = LINK_RE.findall(row["identity"])
    assert targets[0].startswith("../perf/"), row["identity"]


def test_historical_streaming_hop_is_a_distinct_segment_not_supersession() -> None:
    section = " ".join(
        _section(INDEX.read_text(encoding="utf-8"), HISTORICAL_STREAMING_HOP_HEADING)
        .lower()
        .split()
    )
    row = _historical_streaming_hop_rows()[0]
    current = {_identity_path(item["identity"]): item for item in _current_freshness_rows()}[
        REAL_PATH_FRESHNESS_RECORD
    ]

    assert "separate measurement segment" in section
    assert "not a supersession" in section
    assert "s8 extends the measured path" in section
    assert row["supersedes"] == "None"
    assert row["superseded by"] == "None"
    assert current["supersedes"] == "None"
    assert current["superseded by"] == "None"
    _assert_supersession_cell(row["supersedes"])
    _assert_supersession_cell(row["superseded by"])


def test_historical_streaming_hop_record_keeps_published_digest() -> None:
    assert _historical_streaming_hop_record_paths() == [HISTORICAL_STREAMING_HOP_RECORD]
    digest = hashlib.sha256((ROOT / HISTORICAL_STREAMING_HOP_RECORD).read_bytes()).hexdigest()
    assert digest == HISTORICAL_STREAMING_HOP_DIGEST


def test_historical_streaming_hop_sources_and_plan_match_the_index() -> None:
    historical = (ROOT / HISTORICAL_STREAMING_HOP_RECORD).read_text(encoding="utf-8")
    current = (ROOT / REAL_PATH_FRESHNESS_RECORD).read_text(encoding="utf-8")
    bridge = (ROOT / "docs" / "architecture" / "serving-bridge.md").read_text(encoding="utf-8")
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))
    plan = DOCUMENTATION_PLAN.read_text(encoding="utf-8").lower()

    assert Path(REAL_PATH_FRESHNESS_RECORD).name in historical
    assert HISTORICAL_STREAMING_HOP_RECORD in current
    assert Path(HISTORICAL_STREAMING_HOP_RECORD).name in bridge
    assert manifest["latency"]["real_path"]["evidence"] == REAL_PATH_FRESHNESS_RECORD
    assert HISTORICAL_STREAMING_HOP_RECORD not in manifest["required_evidence"]
    assert "historical streaming-hop freshness sub-slice" in plan
    assert HISTORICAL_STREAMING_HOP_DIGEST in plan
    assert "пункт 5 остаётся открыт" in plan


def test_historical_streaming_hop_result_and_boundary_remain_conservative() -> None:
    row = _historical_streaming_hop_rows()[0]
    historical = _row_text(row)
    current = {_identity_path(item["identity"]): item for item in _current_freshness_rows()}[
        REAL_PATH_FRESHNESS_RECORD
    ]
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))

    for phrase in HISTORICAL_STREAMING_HOP_FACTS:
        assert phrase in historical
    for phrase in HISTORICAL_STREAMING_HOP_BOUNDARIES:
        assert phrase in historical
    assert "3.02 s" in _row_text(current)
    assert "5.70 s" in _row_text(current)
    assert manifest["production"]["status"] == "candidate"


def test_current_freshness_index_lists_the_bounded_pair_with_required_fields() -> None:
    text = INDEX.read_text(encoding="utf-8")
    security_at = text.index(SECURITY_DEPENDENCY_HEADING)
    freshness_at = text.index(CURRENT_FRESHNESS_HEADING)
    golden_at = text.index(ACCEPTANCE_HEADING)
    indexed = _current_freshness_record_paths()
    expected = (REAL_PATH_FRESHNESS_RECORD, DEMO_FRESHNESS_RECORD)
    rows = _current_freshness_rows()

    assert security_at < freshness_at < golden_at
    assert set(indexed) == set(expected)
    assert Counter(indexed) == Counter(expected)
    assert indexed == list(expected)
    assert list(rows[0]) == list(REQUIRED_FIELDS)
    assert len(rows) == 2
    for row in rows:
        for field in REQUIRED_FIELDS:
            assert row[field].strip(), f"{field} is empty in {row!r}"
        assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
        identity = _identity_path(row["identity"])
        assert row["date"] == CURRENT_FRESHNESS_DATES[identity]
        assert (ROOT / identity).is_file(), f"indexed identity is missing: {identity}"
        targets = LINK_RE.findall(row["identity"])
        if identity == DEMO_FRESHNESS_RECORD:
            assert targets[0].startswith("../archive/performance/"), row["identity"]
        else:
            assert targets[0].startswith("../perf/"), row["identity"]


def test_current_freshness_records_are_complementary_not_supersession() -> None:
    section = _section(INDEX.read_text(encoding="utf-8"), CURRENT_FRESHNESS_HEADING).lower()
    rows = _current_freshness_rows()

    assert "complementary" in section
    assert "not a supersession chain" in section
    for row in rows:
        assert row["supersedes"] == "None"
        assert row["superseded by"] == "None"
        _assert_supersession_cell(row["supersedes"])
        _assert_supersession_cell(row["superseded by"])


def test_current_freshness_records_keep_published_digests() -> None:
    indexed = set(_current_freshness_record_paths())

    assert indexed == set(CURRENT_FRESHNESS_DIGESTS)
    for relative, expected in CURRENT_FRESHNESS_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected


def test_current_freshness_claim_links_match_indexed_records() -> None:
    indexed = set(_current_freshness_record_paths())
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))
    latency = manifest["latency"]["real_path"]
    status_links = _status_record_links()

    assert indexed == {REAL_PATH_FRESHNESS_RECORD, DEMO_FRESHNESS_RECORD}
    assert REAL_PATH_FRESHNESS_RECORD in manifest["required_evidence"]
    assert latency["evidence"] == REAL_PATH_FRESHNESS_RECORD
    assert latency["p50_seconds"] == 3.02
    assert latency["p95_seconds"] == 5.70
    assert REAL_PATH_FRESHNESS_RECORD in status_links
    assert DEMO_FRESHNESS_RECORD in status_links
    assert manifest["production"]["status"] == "candidate"


def test_current_freshness_boundaries_keep_scopes_distinct() -> None:
    rows = {_identity_path(row["identity"]): row for row in _current_freshness_rows()}
    real_path = _row_text(rows[REAL_PATH_FRESHNESS_RECORD])
    demo = _row_text(rows[DEMO_FRESHNESS_RECORD])

    assert "s8" in rows[REAL_PATH_FRESHNESS_RECORD]["result"].lower()
    assert "3.02 s" in real_path
    assert "5.70 s" in real_path
    assert "n=20" in real_path
    assert "event_driven" in rows[DEMO_FRESHNESS_RECORD]["result"].lower()
    assert "1.06 s" in demo
    assert "1.99 s" in demo
    assert "n=30" in demo
    for phrase in REAL_PATH_FRESHNESS_BOUNDARIES:
        assert phrase in real_path
    for phrase in DEMO_FRESHNESS_BOUNDARIES:
        assert phrase in demo


def test_e4_replica_index_lists_the_bounded_pair_with_required_fields() -> None:
    text = INDEX.read_text(encoding="utf-8")
    freshness_at = text.index(CURRENT_FRESHNESS_HEADING)
    e4_at = text.index(E4_REPLICA_HEADING)
    golden_at = text.index(ACCEPTANCE_HEADING)
    indexed = _e4_replica_record_paths()
    expected = (E4_TWO_POD_RECORD, E4_CHECK4_RECORD)
    rows = _e4_replica_rows()

    assert freshness_at < e4_at < golden_at
    assert set(indexed) == set(expected)
    assert Counter(indexed) == Counter(expected)
    assert indexed == list(expected)
    assert list(rows[0]) == list(REQUIRED_FIELDS)
    assert len(rows) == 2
    for row in rows:
        for field in REQUIRED_FIELDS:
            assert row[field].strip(), f"{field} is empty in {row!r}"
        assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
        identity = _identity_path(row["identity"])
        assert row["date"] == E4_REPLICA_DATES[identity]
        assert (ROOT / identity).is_file(), f"indexed identity is missing: {identity}"
        targets = LINK_RE.findall(row["identity"])
        assert targets[0].startswith("../perf/"), row["identity"]


def test_e4_replica_records_are_extension_not_supersession() -> None:
    section = _section(INDEX.read_text(encoding="utf-8"), E4_REPLICA_HEADING).lower()
    rows = _e4_replica_rows()

    assert "complementary extension" in section
    assert "not a supersession chain" in section
    assert "explicit a-to-b" in section
    assert "different kind snapshot" in section
    for row in rows:
        assert row["supersedes"] == "None"
        assert row["superseded by"] == "None"
        _assert_supersession_cell(row["supersedes"])
        _assert_supersession_cell(row["superseded by"])


def test_e4_replica_records_keep_published_digests() -> None:
    indexed = set(_e4_replica_record_paths())

    assert indexed == set(E4_REPLICA_DIGESTS)
    for relative, expected in E4_REPLICA_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected


def test_e4_replica_claim_links_match_indexed_records() -> None:
    indexed = set(_e4_replica_record_paths())
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))
    status_links = _status_record_links()

    assert indexed == {E4_TWO_POD_RECORD, E4_CHECK4_RECORD}
    assert E4_TWO_POD_RECORD in status_links
    assert E4_CHECK4_RECORD in status_links
    assert manifest["production"]["status"] == "candidate"


def test_e4_replica_boundaries_keep_topology_claims_distinct() -> None:
    rows = {_identity_path(row["identity"]): row for row in _e4_replica_rows()}
    two_pod = _row_text(rows[E4_TWO_POD_RECORD])
    check4 = _row_text(rows[E4_CHECK4_RECORD])

    assert "pass" in rows[E4_TWO_POD_RECORD]["result"].lower()
    assert "pass" in rows[E4_CHECK4_RECORD]["result"].lower()
    for phrase in E4_TWO_POD_BOUNDARIES:
        assert phrase in two_pod
    for phrase in E4_CHECK4_BOUNDARIES:
        assert phrase in check4


def test_historical_e4_index_lists_the_bounded_pair_with_required_fields() -> None:
    text = INDEX.read_text(encoding="utf-8")
    current_e4_at = text.index(E4_REPLICA_HEADING)
    historical_e4_at = text.index(HISTORICAL_E4_HEADING)
    golden_at = text.index(ACCEPTANCE_HEADING)
    indexed = _historical_e4_record_paths()
    expected = (E4_REPLICA_TOPOLOGY_RECORD, E4_CHECK3_RECORD)
    rows = _historical_e4_rows()

    assert current_e4_at < historical_e4_at < golden_at
    assert set(indexed) == set(expected)
    assert Counter(indexed) == Counter(expected)
    assert indexed == list(expected)
    assert list(rows[0]) == list(REQUIRED_FIELDS)
    assert len(rows) == 2
    assert E4_TWO_POD_RECORD not in indexed
    assert E4_CHECK4_RECORD not in indexed
    assert E4_REPLICA_TOPOLOGY_RECORD not in _e4_replica_record_paths()
    assert E4_CHECK3_RECORD not in _e4_replica_record_paths()
    for row in rows:
        for field in REQUIRED_FIELDS:
            assert row[field].strip(), f"{field} is empty in {row!r}"
        assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
        identity = _identity_path(row["identity"])
        assert row["date"] == HISTORICAL_E4_DATES[identity]
        assert (ROOT / identity).is_file(), f"indexed identity is missing: {identity}"
        targets = LINK_RE.findall(row["identity"])
        assert targets[0].startswith("../perf/"), row["identity"]


def test_historical_e4_records_are_extension_not_supersession() -> None:
    section = _section(INDEX.read_text(encoding="utf-8"), HISTORICAL_E4_HEADING).lower()
    rows = _historical_e4_rows()

    assert "historical" in section
    assert "intermediate" in section
    assert "extension" in section
    assert "not a supersession chain" in section
    assert "current status" in section
    assert "checks 1-2" in section
    assert "exactly-one delivery" in section or "exactly one delivery" in section
    assert "does not supersede" in section
    for row in rows:
        assert row["supersedes"] == "None"
        assert row["superseded by"] == "None"
        _assert_supersession_cell(row["supersedes"])
        _assert_supersession_cell(row["superseded by"])
        resolved_supersedes = [
            _resolve_index_link(target) for target in LINK_RE.findall(row["supersedes"])
        ]
        resolved_superseded_by = [
            _resolve_index_link(target) for target in LINK_RE.findall(row["superseded by"])
        ]
        assert E4_TWO_POD_RECORD not in resolved_supersedes
        assert E4_CHECK4_RECORD not in resolved_supersedes
        assert E4_REPLICA_TOPOLOGY_RECORD not in resolved_supersedes
        assert E4_CHECK3_RECORD not in resolved_supersedes
        assert E4_TWO_POD_RECORD not in resolved_superseded_by
        assert E4_CHECK4_RECORD not in resolved_superseded_by
        assert E4_REPLICA_TOPOLOGY_RECORD not in resolved_superseded_by
        assert E4_CHECK3_RECORD not in resolved_superseded_by


def test_historical_e4_records_keep_published_digests() -> None:
    indexed = set(_historical_e4_record_paths())

    assert indexed == set(HISTORICAL_E4_DIGESTS)
    for relative, expected in HISTORICAL_E4_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    for relative, expected in E4_REPLICA_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected


def test_historical_e4_claim_links_are_not_current_status_owners() -> None:
    indexed = set(_historical_e4_record_paths())
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))
    status_links = _status_record_links()
    closure_links = _project_closure_record_links()
    required = manifest["required_evidence"]

    assert indexed == {E4_REPLICA_TOPOLOGY_RECORD, E4_CHECK3_RECORD}
    assert E4_REPLICA_TOPOLOGY_RECORD not in status_links
    assert E4_CHECK3_RECORD not in status_links
    assert E4_TWO_POD_RECORD in status_links
    assert E4_CHECK4_RECORD in status_links
    assert E4_REPLICA_TOPOLOGY_RECORD not in required
    assert E4_CHECK3_RECORD not in required
    assert E4_REPLICA_TOPOLOGY_RECORD not in closure_links
    assert E4_CHECK3_RECORD not in closure_links
    assert manifest["production"]["status"] == "candidate"


def test_historical_e4_boundaries_keep_intermediate_proofs_distinct() -> None:
    rows = {_identity_path(row["identity"]): row for row in _historical_e4_rows()}
    topology = _row_text(rows[E4_REPLICA_TOPOLOGY_RECORD])
    check3 = _row_text(rows[E4_CHECK3_RECORD])

    assert "pass" in rows[E4_REPLICA_TOPOLOGY_RECORD]["result"].lower()
    assert "pass" in rows[E4_CHECK3_RECORD]["result"].lower()
    assert "4a4709a0-0bdc-42bc-803a-2d49c1fb8f04" in topology
    assert "8 round-robin" in topology
    for phrase in E4_REPLICA_TOPOLOGY_BOUNDARIES:
        assert phrase in topology
    for phrase in E4_CHECK3_BOUNDARIES:
        assert phrase in check3


def test_current_endurance_scale_index_lists_the_bounded_pair_with_required_fields() -> None:
    text = INDEX.read_text(encoding="utf-8")
    historical_e4_at = text.index(HISTORICAL_E4_HEADING)
    endurance_at = text.index(CURRENT_ENDURANCE_SCALE_HEADING)
    golden_at = text.index(ACCEPTANCE_HEADING)
    indexed = _current_endurance_scale_record_paths()
    expected = (S11_SOAK_RECORD, S13_SCALE_RECORD)
    rows = _current_endurance_scale_rows()

    assert historical_e4_at < endurance_at < golden_at
    assert set(indexed) == set(expected)
    assert Counter(indexed) == Counter(expected)
    assert indexed == list(expected)
    assert RSS_REVERIFY_RECORD not in indexed
    assert list(rows[0]) == list(REQUIRED_FIELDS)
    assert len(rows) == 2
    for row in rows:
        for field in REQUIRED_FIELDS:
            assert row[field].strip(), f"{field} is empty in {row!r}"
        assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
        identity = _identity_path(row["identity"])
        assert row["date"] == CURRENT_ENDURANCE_SCALE_DATES[identity]
        assert (ROOT / identity).is_file(), f"indexed identity is missing: {identity}"
        targets = LINK_RE.findall(row["identity"])
        assert targets[0].startswith("../perf/"), row["identity"]


def test_current_endurance_scale_records_are_complementary_with_scoped_api_rss() -> None:
    section = _section(INDEX.read_text(encoding="utf-8"), CURRENT_ENDURANCE_SCALE_HEADING).lower()
    indexed = _current_endurance_scale_record_paths()
    rows = {_identity_path(row["identity"]): row for row in _current_endurance_scale_rows()}
    s11 = rows[S11_SOAK_RECORD]
    s13 = rows[S13_SCALE_RECORD]
    s11_superseded_by_targets = LINK_RE.findall(s11["superseded by"])

    assert "complementary" in section
    assert "not a supersession chain" in section
    assert "scoped partial supersession" in section
    assert "api rss" in section
    assert "full-path endurance" in section
    assert "does not supersede" in section
    assert "rss-reverify-183-2026-07-11" in section
    assert RSS_REVERIFY_RECORD not in indexed
    assert s11["supersedes"] == "None"
    assert [_resolve_index_link(target) for target in s11_superseded_by_targets] == [
        RSS_REVERIFY_RECORD
    ]
    assert s11_superseded_by_targets[0].startswith("../perf/")
    assert s13["supersedes"] == "None"
    assert s13["superseded by"] == "None"
    _assert_supersession_cell(s11["supersedes"])
    _assert_supersession_cell(s11["superseded by"])
    _assert_supersession_cell(s13["supersedes"])
    _assert_supersession_cell(s13["superseded by"])
    s11_supersedes = [_resolve_index_link(target) for target in LINK_RE.findall(s11["supersedes"])]
    s11_superseded_by = [_resolve_index_link(target) for target in s11_superseded_by_targets]
    s13_supersedes = [_resolve_index_link(target) for target in LINK_RE.findall(s13["supersedes"])]
    s13_superseded_by = [
        _resolve_index_link(target) for target in LINK_RE.findall(s13["superseded by"])
    ]
    assert S11_SOAK_RECORD not in s11_supersedes
    assert S13_SCALE_RECORD not in s11_supersedes
    assert RSS_REVERIFY_RECORD not in s11_supersedes
    assert S11_SOAK_RECORD not in s11_superseded_by
    assert S13_SCALE_RECORD not in s11_superseded_by
    assert S11_SOAK_RECORD not in s13_supersedes
    assert S13_SCALE_RECORD not in s13_supersedes
    assert RSS_REVERIFY_RECORD not in s13_supersedes
    assert S11_SOAK_RECORD not in s13_superseded_by
    assert S13_SCALE_RECORD not in s13_superseded_by
    assert RSS_REVERIFY_RECORD not in s13_superseded_by


def test_current_endurance_scale_records_keep_published_digests() -> None:
    indexed = set(_current_endurance_scale_record_paths())

    assert indexed == set(CURRENT_ENDURANCE_SCALE_DIGESTS)
    for relative, expected in CURRENT_ENDURANCE_SCALE_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    assert (ROOT / RSS_REVERIFY_RECORD).is_file()


def test_current_endurance_scale_claim_links_match_status_rows() -> None:
    indexed = set(_current_endurance_scale_record_paths())
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))
    status_links = _status_record_links()
    proven_rows = _status_table_rows("## Proven")
    known_issues = _section(STATUS.read_text(encoding="utf-8"), "## Known issues").lower()
    proven_by_path: dict[str, dict[str, str]] = {}
    proven_paths: set[str] = set()
    for row in proven_rows:
        for path in _status_cell_record_paths(row.get("evidence", "")):
            proven_paths.add(path)
            proven_by_path[path] = row

    assert indexed == {S11_SOAK_RECORD, S13_SCALE_RECORD}
    assert S11_SOAK_RECORD in status_links
    assert S13_SCALE_RECORD in status_links
    assert S11_SOAK_RECORD in proven_paths
    assert S13_SCALE_RECORD in proven_paths
    assert RSS_REVERIFY_RECORD not in proven_paths
    assert RSS_REVERIFY_RECORD in status_links
    assert "rss-reverify-183-2026-07-11.md" in known_issues
    assert proven_by_path[S11_SOAK_RECORD]["claim"] == S11_STATUS_CLAIM
    assert proven_by_path[S11_SOAK_RECORD]["result"] == S11_STATUS_RESULT
    assert proven_by_path[S13_SCALE_RECORD]["claim"] == S13_STATUS_CLAIM
    assert proven_by_path[S13_SCALE_RECORD]["result"] == S13_STATUS_RESULT
    assert manifest["production"]["status"] == "candidate"


def test_current_endurance_scale_boundaries_keep_scopes_distinct() -> None:
    rows = {_identity_path(row["identity"]): row for row in _current_endurance_scale_rows()}
    s11 = _row_text(rows[S11_SOAK_RECORD])
    s13 = _row_text(rows[S13_SCALE_RECORD])

    assert "s11" in rows[S11_SOAK_RECORD]["result"].lower()
    assert "s13" in rows[S13_SCALE_RECORD]["result"].lower()
    assert "does not supersede" in s11
    assert "full-path endurance" in s11
    for phrase in S11_SOAK_BOUNDARIES:
        assert phrase in s11
    for phrase in S13_SCALE_BOUNDARIES:
        assert phrase in s13


def test_rss_reverify_section_follows_endurance_and_precedes_s10() -> None:
    text = INDEX.read_text(encoding="utf-8")
    endurance_at = text.index(CURRENT_ENDURANCE_SCALE_HEADING)
    rss_reverify_at = text.index(RSS_REVERIFY_HEADING)
    s10_at = text.index(CURRENT_S10_THROUGHPUT_HEADING)
    between_rss_reverify_and_s10 = text[rss_reverify_at + len(RSS_REVERIFY_HEADING) : s10_at]

    assert "API RSS fix" in RSS_REVERIFY_HEADING
    assert endurance_at < rss_reverify_at < s10_at
    assert "\n## " not in between_rss_reverify_and_s10


def test_rss_reverify_index_lists_one_bounded_record_with_required_fields() -> None:
    indexed = _rss_reverify_record_paths()
    rows = _rss_reverify_rows()

    assert indexed == [RSS_REVERIFY_RECORD]
    assert Counter(indexed) == Counter([RSS_REVERIFY_RECORD])
    assert list(rows[0]) == list(REQUIRED_FIELDS)
    assert len(rows) == 1
    row = rows[0]
    for field in REQUIRED_FIELDS:
        assert row[field].strip(), f"{field} is empty in {row!r}"
    assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
    assert row["date"] == RSS_REVERIFY_DATE
    assert (ROOT / RSS_REVERIFY_RECORD).is_file()
    targets = LINK_RE.findall(row["identity"])
    assert targets[0].startswith("../perf/"), row["identity"]


def test_rss_reverify_is_reciprocal_partial_supersession_of_s11_api_rss_finding() -> None:
    section = _section(INDEX.read_text(encoding="utf-8"), RSS_REVERIFY_HEADING).lower()
    rss_row = _rss_reverify_rows()[0]
    endurance_rows = {
        _identity_path(row["identity"]): row for row in _current_endurance_scale_rows()
    }
    s11 = endurance_rows[S11_SOAK_RECORD]
    s13 = endurance_rows[S13_SCALE_RECORD]

    assert "scoped partial supersession" in section
    assert "api rss" in section
    assert "full-path endurance" in section
    assert [_resolve_index_link(target) for target in LINK_RE.findall(rss_row["supersedes"])] == [
        S11_SOAK_RECORD
    ]
    assert rss_row["superseded by"] == "None"
    assert [_resolve_index_link(target) for target in LINK_RE.findall(s11["superseded by"])] == [
        RSS_REVERIFY_RECORD
    ]
    assert s13["supersedes"] == "None"
    assert s13["superseded by"] == "None"
    _assert_supersession_cell(rss_row["supersedes"])
    _assert_supersession_cell(rss_row["superseded by"])


def test_rss_reverify_record_keeps_published_digest_and_status_owner() -> None:
    status_links = _status_record_links()
    known_issues = _section(STATUS.read_text(encoding="utf-8"), "## Known issues").lower()

    assert _rss_reverify_record_paths() == [RSS_REVERIFY_RECORD]
    digest = hashlib.sha256((ROOT / RSS_REVERIFY_RECORD).read_bytes()).hexdigest()
    assert digest == RSS_REVERIFY_DIGEST
    assert RSS_REVERIFY_RECORD in status_links
    assert "api rss growth under steady load" in known_issues
    assert "97 min" in known_issues
    assert "+7.5 mb/h" in known_issues
    assert "plateaued" in known_issues


def test_rss_reverify_result_and_boundary_remain_conservative() -> None:
    row = _rss_reverify_rows()[0]
    record = _row_text(row)
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))

    assert "rss" in row["result"].lower()
    assert "re-verification" in row["result"].lower()
    for phrase in RSS_REVERIFY_RESULT_FACTS:
        assert phrase in record
    for phrase in RSS_REVERIFY_BOUNDARIES:
        assert phrase in record
    assert manifest["production"]["status"] == "candidate"
    assert manifest["production"]["full_soak_plus_rollback_after_traffic"] == (
        "BLOCKED_HOST_CAPACITY"
    )


def test_current_s10_throughput_index_lists_the_bounded_pair_with_required_fields() -> None:
    text = INDEX.read_text(encoding="utf-8")
    endurance_at = text.index(CURRENT_ENDURANCE_SCALE_HEADING)
    s10_at = text.index(CURRENT_S10_THROUGHPUT_HEADING)
    golden_at = text.index(ACCEPTANCE_HEADING)
    indexed = _current_s10_throughput_record_paths()
    expected = (S10_BURST_BASELINE_RECORD, S10_PACED_R4_RECORD)
    rows = _current_s10_throughput_rows()

    assert endurance_at < s10_at < golden_at
    assert set(indexed) == set(expected)
    assert Counter(indexed) == Counter(expected)
    assert indexed == list(expected)
    assert list(rows[0]) == list(REQUIRED_FIELDS)
    assert len(rows) == 2
    for relative in S10_INTERMEDIATE_RECORDS:
        assert relative not in indexed
    assert REAL_PATH_FRESHNESS_RECORD not in indexed
    assert SOAK_CAPACITY_RECORD not in indexed
    for row in rows:
        for field in REQUIRED_FIELDS:
            assert row[field].strip(), f"{field} is empty in {row!r}"
        assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
        identity = _identity_path(row["identity"])
        assert row["date"] == CURRENT_S10_THROUGHPUT_DATES[identity]
        assert (ROOT / identity).is_file(), f"indexed identity is missing: {identity}"
        targets = LINK_RE.findall(row["identity"])
        if identity == S10_BURST_BASELINE_RECORD:
            assert targets[0].startswith("../archive/performance/"), row["identity"]
        else:
            assert targets[0].startswith("../perf/"), row["identity"]


def test_current_s10_throughput_records_are_not_a_direct_supersession_chain() -> None:
    section = _section(INDEX.read_text(encoding="utf-8"), CURRENT_S10_THROUGHPUT_HEADING)
    section_lower = section.lower()
    rows = {_identity_path(row["identity"]): row for row in _current_s10_throughput_rows()}
    baseline = rows[S10_BURST_BASELINE_RECORD]
    r4 = rows[S10_PACED_R4_RECORD]
    r4_supersedes = [_resolve_index_link(target) for target in LINK_RE.findall(r4["supersedes"])]
    r4_superseded_by = [
        _resolve_index_link(target) for target in LINK_RE.findall(r4["superseded by"])
    ]

    assert any("not a direct supersession chain" in line for line in section.splitlines())
    assert "different modes" in section_lower
    assert "current four-hour paced-gate outcome" in section_lower
    assert "historical facts remain valid" in section_lower
    assert "already-closed serving-path gate" in section_lower
    assert "remains open" in section_lower
    assert baseline["supersedes"] == "None"
    assert baseline["superseded by"] == "None"
    assert r4_supersedes == [S10_PACED_R1_RECORD, S10_PACED_R3_RECORD]
    assert r4["supersedes"].count("[") == 2
    assert r4["superseded by"] == "None"
    assert S10_BURST_BASELINE_RECORD not in r4_supersedes
    assert S10_BURST_BASELINE_RECORD not in r4_superseded_by
    assert SOAK_CAPACITY_RECORD not in r4_supersedes
    assert SOAK_CAPACITY_RECORD not in r4_superseded_by
    _assert_supersession_cell(baseline["supersedes"])
    _assert_supersession_cell(baseline["superseded by"])
    _assert_supersession_cell(r4["supersedes"])
    _assert_supersession_cell(r4["superseded by"])


def test_current_s10_throughput_records_keep_published_digests() -> None:
    indexed = set(_current_s10_throughput_record_paths())

    assert indexed == set(CURRENT_S10_THROUGHPUT_DIGESTS)
    for relative, expected in CURRENT_S10_THROUGHPUT_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    assert (ROOT / S10_PACED_R1_RECORD).is_file()
    assert (ROOT / S10_PACED_R3_RECORD).is_file()
    f02_digest = hashlib.sha256((ROOT / SOAK_CAPACITY_RECORD).read_bytes()).hexdigest()
    assert f02_digest == F10_DIGESTS[SOAK_CAPACITY_RECORD]


def test_current_s10_throughput_claim_links_match_status_rows() -> None:
    indexed = set(_current_s10_throughput_record_paths())
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))
    status_links = _status_record_links()
    proven_rows = _status_table_rows(S10_BASELINE_STATUS_HEADING)
    bridge_rows = _status_table_rows(S10_R4_STATUS_HEADING)
    proven_by_path: dict[str, dict[str, str]] = {}
    for row in proven_rows:
        for path in _status_cell_record_paths(row.get("evidence", "")):
            proven_by_path[path] = row
    bridge_by_path: dict[str, dict[str, str]] = {}
    for row in bridge_rows:
        for path in _status_cell_record_paths(row.get("state", "")):
            bridge_by_path[path] = row

    assert indexed == {S10_BURST_BASELINE_RECORD, S10_PACED_R4_RECORD}
    assert S10_BURST_BASELINE_RECORD in status_links
    assert S10_PACED_R4_RECORD in status_links
    assert S10_PACED_R1_RECORD not in status_links
    assert S10_PACED_R3_RECORD not in status_links
    assert proven_by_path[S10_BURST_BASELINE_RECORD]["claim"] == S10_BASELINE_STATUS_CLAIM
    assert proven_by_path[S10_BURST_BASELINE_RECORD]["result"] == S10_BASELINE_STATUS_RESULT
    assert S10_PACED_R4_RECORD not in proven_by_path
    assert bridge_by_path[S10_PACED_R4_RECORD]["step"] == S10_R4_STATUS_CLAIM
    assert bridge_by_path[S10_PACED_R4_RECORD]["bridge apply"] == S10_R4_STATUS_RESULT
    assert bridge_by_path[S10_BURST_BASELINE_RECORD]["step"] == "Baseline (per-event apply)"
    assert bridge_by_path[S10_BURST_BASELINE_RECORD]["bridge apply"] == "~8 eps"
    assert SOAK_CAPACITY_RECORD in status_links
    assert SOAK_CAPACITY_RECORD in _f10_record_paths()
    assert manifest["production"]["status"] == "candidate"
    assert manifest["production"]["full_soak_plus_rollback_after_traffic"] == (
        "BLOCKED_HOST_CAPACITY"
    )


def test_current_s10_throughput_boundaries_keep_scopes_distinct() -> None:
    rows = {_identity_path(row["identity"]): row for row in _current_s10_throughput_rows()}
    baseline = _row_text(rows[S10_BURST_BASELINE_RECORD])
    r4 = _row_text(rows[S10_PACED_R4_RECORD])

    assert "s10" in rows[S10_BURST_BASELINE_RECORD]["result"].lower()
    assert "pass" in rows[S10_PACED_R4_RECORD]["result"].lower()
    assert "consumed = applied = 1 440 000" in r4
    assert "produced = delivered = 1 440 000" in r4
    for phrase in S10_BURST_BASELINE_BOUNDARIES:
        assert phrase in baseline
    for phrase in S10_PACED_R4_BOUNDARIES:
        assert phrase in r4


def test_q12_predecessor_section_follows_historical_paced_and_precedes_q13_q14() -> None:
    text = INDEX.read_text(encoding="utf-8")
    current_s10_at = text.index(CURRENT_S10_THROUGHPUT_HEADING)
    historical_paced_at = text.index(HISTORICAL_PACED_4H_HEADING)
    q12_at = text.index(Q12_PREDECESSOR_HEADING)
    q13_q14_at = text.index(Q13_Q14_INTERMEDIATE_S10_HEADING)
    paced_at = text.index(PACED_10M_1H_HEADING)
    golden_at = text.index(ACCEPTANCE_HEADING)
    between_current_and_historical = text[
        current_s10_at + len(CURRENT_S10_THROUGHPUT_HEADING) : historical_paced_at
    ]
    between_historical_and_q12 = text[
        historical_paced_at + len(HISTORICAL_PACED_4H_HEADING) : q12_at
    ]
    between_q12_and_q13 = text[q12_at + len(Q12_PREDECESSOR_HEADING) : q13_q14_at]
    between_new_and_paced = text[q13_q14_at + len(Q13_Q14_INTERMEDIATE_S10_HEADING) : paced_at]

    assert "Historical four-hour paced" in HISTORICAL_PACED_4H_HEADING
    assert "S10 predecessor records" in HISTORICAL_PACED_4H_HEADING
    assert "Q1.2 predecessor" in Q12_PREDECESSOR_HEADING
    assert "S10 throughput record" in Q12_PREDECESSOR_HEADING
    assert "Q1.3/Q1.4" in Q13_Q14_INTERMEDIATE_S10_HEADING
    assert "intermediate S10 throughput" in Q13_Q14_INTERMEDIATE_S10_HEADING
    assert current_s10_at < historical_paced_at < q12_at < q13_q14_at < paced_at < golden_at
    assert "\n## " not in between_current_and_historical
    assert "\n## " not in between_historical_and_q12
    assert "\n## " not in between_q12_and_q13
    assert "\n## " not in between_new_and_paced


def test_q12_predecessor_index_lists_one_bounded_record_with_required_fields() -> None:
    indexed = _q12_predecessor_record_paths()
    rows = _q12_predecessor_rows()

    assert indexed == [S10_Q12_RECORD]
    assert Counter(indexed) == Counter([S10_Q12_RECORD])
    assert list(rows[0]) == list(REQUIRED_FIELDS)
    assert len(rows) == 1
    row = rows[0]
    for field in REQUIRED_FIELDS:
        assert row[field].strip(), f"{field} is empty in {row!r}"
    assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
    assert row["date"] == Q12_PREDECESSOR_DATE
    assert (ROOT / S10_Q12_RECORD).is_file()
    targets = LINK_RE.findall(row["identity"])
    assert targets[0].startswith("../perf/"), row["identity"]
    assert S10_Q12_RECORD not in _q13_q14_intermediate_s10_record_paths()


def test_q12_predecessor_is_reciprocal_root_of_q13_q14_narrow_chain() -> None:
    section = _section(INDEX.read_text(encoding="utf-8"), Q12_PREDECESSOR_HEADING).lower()
    q12 = _q12_predecessor_rows()[0]
    q13_q14 = {_identity_path(row["identity"]): row for row in _q13_q14_intermediate_s10_rows()}
    q13 = q13_q14[S10_Q13_RECORD]
    q14 = q13_q14[S10_Q14_RECORD]
    current = {_identity_path(row["identity"]): row for row in _current_s10_throughput_rows()}
    baseline = current[S10_BURST_BASELINE_RECORD]

    assert "root of the narrow" in section
    assert "q1.2 -> q1.3 -> q1.4" in section
    assert q12["supersedes"] == "None"
    assert [_resolve_index_link(target) for target in LINK_RE.findall(q12["superseded by"])] == [
        S10_Q13_RECORD
    ]
    assert [_resolve_index_link(target) for target in LINK_RE.findall(q13["supersedes"])] == [
        S10_Q12_RECORD
    ]
    assert [_resolve_index_link(target) for target in LINK_RE.findall(q13["superseded by"])] == [
        S10_Q14_RECORD
    ]
    assert [_resolve_index_link(target) for target in LINK_RE.findall(q14["supersedes"])] == [
        S10_Q13_RECORD
    ]
    assert baseline["supersedes"] == "None"
    assert baseline["superseded by"] == "None"
    _assert_supersession_cell(q12["supersedes"])
    _assert_supersession_cell(q12["superseded by"])


def test_q12_predecessor_record_keeps_published_digest() -> None:
    assert _q12_predecessor_record_paths() == [S10_Q12_RECORD]
    digest = hashlib.sha256((ROOT / S10_Q12_RECORD).read_bytes()).hexdigest()
    assert digest == Q12_PREDECESSOR_DIGEST


def test_q12_predecessor_result_and_boundary_remain_conservative() -> None:
    row = _q12_predecessor_rows()[0]
    q12 = _row_text(row)
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))
    status_links = _status_record_links()

    assert "q1.2" in row["result"].lower()
    for phrase in Q12_PREDECESSOR_RESULT_FACTS:
        assert phrase in q12
    for phrase in Q12_PREDECESSOR_BOUNDARIES:
        assert phrase in q12
    assert S10_Q12_RECORD in status_links
    assert manifest["production"]["status"] == "candidate"
    assert manifest["production"]["full_soak_plus_rollback_after_traffic"] == (
        "BLOCKED_HOST_CAPACITY"
    )


def test_historical_paced_4h_index_lists_the_bounded_pair_with_required_fields() -> None:
    indexed = _historical_paced_4h_record_paths()
    expected = (S10_PACED_R1_RECORD, S10_PACED_R3_RECORD)
    rows = _historical_paced_4h_rows()

    assert set(indexed) == set(expected)
    assert Counter(indexed) == Counter(expected)
    assert indexed == list(expected)
    assert list(rows[0]) == list(REQUIRED_FIELDS)
    assert len(rows) == 2
    assert S10_PACED_R4_RECORD not in indexed
    assert S10_Q12_RECORD not in indexed
    for row in rows:
        for field in REQUIRED_FIELDS:
            assert row[field].strip(), f"{field} is empty in {row!r}"
        assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
        identity = _identity_path(row["identity"])
        assert row["date"] == HISTORICAL_PACED_4H_DATES[identity]
        assert (ROOT / identity).is_file(), f"indexed identity is missing: {identity}"
        targets = LINK_RE.findall(row["identity"])
        assert targets[0].startswith("../perf/"), row["identity"]


def test_historical_paced_4h_rows_reciprocate_r4_without_cross_supersession() -> None:
    section = _section(INDEX.read_text(encoding="utf-8"), HISTORICAL_PACED_4H_HEADING).lower()
    historical_rows = {_identity_path(row["identity"]): row for row in _historical_paced_4h_rows()}
    current_rows = {_identity_path(row["identity"]): row for row in _current_s10_throughput_rows()}
    r4 = current_rows[S10_PACED_R4_RECORD]
    r4_supersedes = [_resolve_index_link(target) for target in LINK_RE.findall(r4["supersedes"])]

    assert "distinct failure modes" in section
    assert "not a supersession chain" in section
    assert "current four-hour paced-gate outcome" in section
    assert r4_supersedes == [S10_PACED_R1_RECORD, S10_PACED_R3_RECORD]
    for relative in (S10_PACED_R1_RECORD, S10_PACED_R3_RECORD):
        row = historical_rows[relative]
        assert row["supersedes"] == "None"
        assert [
            _resolve_index_link(target) for target in LINK_RE.findall(row["superseded by"])
        ] == [S10_PACED_R4_RECORD]
        _assert_supersession_cell(row["supersedes"])
        _assert_supersession_cell(row["superseded by"])
    assert S10_PACED_R3_RECORD not in [
        _resolve_index_link(target)
        for target in LINK_RE.findall(historical_rows[S10_PACED_R1_RECORD]["superseded by"])
    ]
    assert S10_PACED_R1_RECORD not in [
        _resolve_index_link(target)
        for target in LINK_RE.findall(historical_rows[S10_PACED_R3_RECORD]["superseded by"])
    ]


def test_historical_paced_4h_records_keep_published_digests() -> None:
    assert set(_historical_paced_4h_record_paths()) == set(HISTORICAL_PACED_4H_DIGESTS)
    for relative, expected in HISTORICAL_PACED_4H_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected


def test_historical_paced_4h_results_and_boundaries_remain_conservative() -> None:
    rows = {_identity_path(row["identity"]): row for row in _historical_paced_4h_rows()}
    r1 = _row_text(rows[S10_PACED_R1_RECORD])
    r3 = _row_text(rows[S10_PACED_R3_RECORD])
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))

    for phrase in S10_PACED_R1_RESULT_FACTS:
        assert phrase in r1
    for phrase in S10_PACED_R3_RESULT_FACTS:
        assert phrase in r3
    for phrase in S10_PACED_R1_BOUNDARIES:
        assert phrase in r1
    for phrase in S10_PACED_R3_BOUNDARIES:
        assert phrase in r3
    assert manifest["production"]["status"] == "candidate"
    assert manifest["production"]["full_soak_plus_rollback_after_traffic"] == (
        "BLOCKED_HOST_CAPACITY"
    )


def test_q13_q14_index_lists_the_bounded_pair_with_required_fields() -> None:
    indexed = _q13_q14_intermediate_s10_record_paths()
    expected = (S10_Q13_RECORD, S10_Q14_RECORD)
    rows = _q13_q14_intermediate_s10_rows()

    assert set(indexed) == set(expected)
    assert Counter(indexed) == Counter(expected)
    assert indexed == list(expected)
    assert list(rows[0]) == list(REQUIRED_FIELDS)
    assert len(rows) == 2
    assert S10_Q12_RECORD not in indexed
    for relative in Q13_Q14_NON_SUPERSESSION_RECORDS:
        assert relative not in indexed
    for row in rows:
        for field in REQUIRED_FIELDS:
            assert row[field].strip(), f"{field} is empty in {row!r}"
        assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
        identity = _identity_path(row["identity"])
        assert row["date"] == Q13_Q14_INTERMEDIATE_S10_DATES[identity]
        assert (ROOT / identity).is_file(), f"indexed identity is missing: {identity}"
        targets = LINK_RE.findall(row["identity"])
        assert targets[0].startswith("../perf/"), row["identity"]


def test_q13_q14_narrow_reciprocal_supersession_chain() -> None:
    section = _section(INDEX.read_text(encoding="utf-8"), Q13_Q14_INTERMEDIATE_S10_HEADING)
    section_lower = section.lower()
    rows = {_identity_path(row["identity"]): row for row in _q13_q14_intermediate_s10_rows()}
    q13 = rows[S10_Q13_RECORD]
    q14 = rows[S10_Q14_RECORD]
    q13_supersedes = [_resolve_index_link(target) for target in LINK_RE.findall(q13["supersedes"])]
    q13_superseded_by = [
        _resolve_index_link(target) for target in LINK_RE.findall(q13["superseded by"])
    ]
    q14_supersedes = [_resolve_index_link(target) for target in LINK_RE.findall(q14["supersedes"])]
    q14_superseded_by = [
        _resolve_index_link(target) for target in LINK_RE.findall(q14["superseded by"])
    ]
    current_rows = {_identity_path(row["identity"]): row for row in _current_s10_throughput_rows()}

    assert "historical measurements remain valid" in section_lower
    assert "do not merge" in section_lower
    assert "four-hour paced" in section_lower
    assert "narrow" in section_lower
    assert q13_supersedes == [S10_Q12_RECORD]
    assert q13["supersedes"].count("[") == 1
    assert q13_superseded_by == [S10_Q14_RECORD]
    assert q13["superseded by"].count("[") == 1
    assert q14_supersedes == [S10_Q13_RECORD]
    assert q14["supersedes"].count("[") == 1
    assert q14["superseded by"] == "None"
    assert q14_superseded_by == []
    assert S10_Q12_RECORD not in q13_superseded_by
    assert S10_Q12_RECORD not in q14_supersedes
    assert S10_Q12_RECORD not in q14_superseded_by
    for relative in Q13_Q14_NON_SUPERSESSION_RECORDS:
        assert relative not in q13_supersedes
        assert relative not in q13_superseded_by
        assert relative not in q14_supersedes
        assert relative not in q14_superseded_by
    for row in current_rows.values():
        current_supersedes = [
            _resolve_index_link(target) for target in LINK_RE.findall(row["supersedes"])
        ]
        current_superseded_by = [
            _resolve_index_link(target) for target in LINK_RE.findall(row["superseded by"])
        ]
        assert S10_Q13_RECORD not in current_supersedes
        assert S10_Q14_RECORD not in current_supersedes
        assert S10_Q13_RECORD not in current_superseded_by
        assert S10_Q14_RECORD not in current_superseded_by
    _assert_supersession_cell(q13["supersedes"])
    _assert_supersession_cell(q13["superseded by"])
    _assert_supersession_cell(q14["supersedes"])
    _assert_supersession_cell(q14["superseded by"])


def test_q13_q14_records_keep_published_digests() -> None:
    indexed = set(_q13_q14_intermediate_s10_record_paths())

    assert indexed == set(Q13_Q14_INTERMEDIATE_S10_DIGESTS)
    for relative, expected in Q13_Q14_INTERMEDIATE_S10_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    assert (ROOT / S10_Q12_RECORD).is_file()
    for relative, expected in CURRENT_S10_THROUGHPUT_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected


def test_q13_q14_status_readme_ownership_and_current_endpoint_exclusion() -> None:
    indexed = _q13_q14_intermediate_s10_record_paths()
    rows = {_identity_path(row["identity"]): row for row in _q13_q14_intermediate_s10_rows()}
    current = _current_s10_throughput_record_paths()
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))
    status_links = _status_record_links()
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    bridge_rows = _status_table_rows(S10_R4_STATUS_HEADING)
    q14_status_rows = [
        row
        for row in bridge_rows
        if S10_Q14_RECORD in _status_cell_record_paths(row.get("state", ""))
    ]
    q14_claim = rows[S10_Q14_RECORD]["claim boundary"].lower()

    assert indexed == [S10_Q13_RECORD, S10_Q14_RECORD]
    assert S10_Q13_RECORD not in current
    assert S10_Q14_RECORD not in current
    assert current == [S10_BURST_BASELINE_RECORD, S10_PACED_R4_RECORD]
    assert S10_Q14_RECORD in status_links
    assert len(q14_status_rows) == 1
    assert "87.4" in q14_status_rows[0]["bridge apply"]
    assert "throughput-realpath-q14-2026-07-10.md" in readme
    assert "87.4 events/s" in readme
    assert "400-event burst" in readme
    assert "docs/status.md" in q14_claim
    assert "readme" in q14_claim
    assert "400-event" in q14_claim
    assert manifest["production"]["status"] == "candidate"
    assert manifest["production"]["full_soak_plus_rollback_after_traffic"] == (
        "BLOCKED_HOST_CAPACITY"
    )


def test_q13_q14_boundaries_remain_conservative() -> None:
    section = _section(INDEX.read_text(encoding="utf-8"), Q13_Q14_INTERMEDIATE_S10_HEADING).lower()
    rows = {_identity_path(row["identity"]): row for row in _q13_q14_intermediate_s10_rows()}
    q13 = _row_text(rows[S10_Q13_RECORD])
    q14 = _row_text(rows[S10_Q14_RECORD])

    assert "q1.3" in rows[S10_Q13_RECORD]["result"].lower()
    assert "q1.4" in rows[S10_Q14_RECORD]["result"].lower()
    for phrase in S10_Q13_RESULT_FACTS:
        assert phrase in q13
    for phrase in S10_Q14_RESULT_FACTS:
        assert phrase in q14
    for phrase in S10_Q13_BOUNDARIES:
        assert phrase in q13
    for phrase in S10_Q14_BOUNDARIES:
        assert phrase in q14
    assert "historical measurements remain valid" in section
    assert "do not merge" in section
    assert "four-hour paced" in section
    assert "candidate" in q13
    assert "candidate" in q14
    assert "golden full-soak" in q13
    assert "golden full-soak" in q14
    assert "remains open" in q13
    assert "remains open" in q14


def test_paced_10m_1h_section_follows_q13_q14_and_precedes_finite_drain() -> None:
    text = INDEX.read_text(encoding="utf-8")
    q13_q14_at = text.index(Q13_Q14_INTERMEDIATE_S10_HEADING)
    paced_at = text.index(PACED_10M_1H_HEADING)
    finite_drain_at = text.index(FINITE_100EPS_DRAIN_HEADING)
    between_q13_q14_and_paced = text[q13_q14_at + len(Q13_Q14_INTERMEDIATE_S10_HEADING) : paced_at]
    between_paced_and_finite_drain = text[paced_at + len(PACED_10M_1H_HEADING) : finite_drain_at]

    assert "Paced 10-minute and one-hour" in PACED_10M_1H_HEADING
    assert "S10 throughput" in PACED_10M_1H_HEADING
    assert q13_q14_at < paced_at < finite_drain_at
    assert "\n## " not in between_q13_q14_and_paced
    assert "\n## " not in between_paced_and_finite_drain


def test_paced_10m_1h_index_lists_the_bounded_pair_with_required_fields() -> None:
    indexed = _paced_10m_1h_record_paths()
    expected = (S10_PACED_10M_RECORD, S10_PACED_1H_RECORD)
    rows = _paced_10m_1h_rows()

    assert set(indexed) == set(expected)
    assert Counter(indexed) == Counter(expected)
    assert indexed == list(expected)
    assert list(rows[0]) == list(REQUIRED_FIELDS)
    assert len(rows) == 2
    for relative in PACED_10M_1H_OTHER_RECORDS:
        assert relative not in indexed
    for row in rows:
        for field in REQUIRED_FIELDS:
            assert row[field].strip(), f"{field} is empty in {row!r}"
        assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
        identity = _identity_path(row["identity"])
        assert row["date"] == PACED_10M_1H_DATES[identity]
        assert (ROOT / identity).is_file(), f"indexed identity is missing: {identity}"
        targets = LINK_RE.findall(row["identity"])
        assert targets[0].startswith("../perf/"), row["identity"]


def test_paced_10m_1h_are_duration_extensions_not_supersession() -> None:
    section = _section(INDEX.read_text(encoding="utf-8"), PACED_10M_1H_HEADING).lower()
    rows = {_identity_path(row["identity"]): row for row in _paced_10m_1h_rows()}
    current_rows = {_identity_path(row["identity"]): row for row in _current_s10_throughput_rows()}

    assert "duration-extension" in section
    assert "not a supersession chain" in section
    assert "historical facts remain valid" in section
    assert "four-hour r4" in section
    for row in rows.values():
        assert row["supersedes"] == "None"
        assert row["superseded by"] == "None"
        _assert_supersession_cell(row["supersedes"])
        _assert_supersession_cell(row["superseded by"])
    r4 = current_rows[S10_PACED_R4_RECORD]
    r4_supersedes = [_resolve_index_link(target) for target in LINK_RE.findall(r4["supersedes"])]
    r4_superseded_by = [
        _resolve_index_link(target) for target in LINK_RE.findall(r4["superseded by"])
    ]
    assert r4_supersedes == [S10_PACED_R1_RECORD, S10_PACED_R3_RECORD]
    assert r4_superseded_by == []
    assert S10_PACED_10M_RECORD not in r4_supersedes
    assert S10_PACED_1H_RECORD not in r4_supersedes


def test_paced_10m_1h_records_keep_published_digests() -> None:
    indexed = set(_paced_10m_1h_record_paths())

    assert indexed == set(PACED_10M_1H_DIGESTS)
    for relative, expected in PACED_10M_1H_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    for relative, expected in CURRENT_S10_THROUGHPUT_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected


def test_paced_10m_1h_status_rows_match_indexed_records() -> None:
    indexed = _paced_10m_1h_record_paths()
    current = _current_s10_throughput_record_paths()
    q13_q14 = _q13_q14_intermediate_s10_record_paths()
    status_links = _status_record_links()
    bridge_rows = _status_table_rows(S10_R4_STATUS_HEADING)
    by_path: dict[str, dict[str, str]] = {}
    for row in bridge_rows:
        for path in _status_cell_record_paths(row.get("state", "")):
            by_path[path] = row

    assert indexed == [S10_PACED_10M_RECORD, S10_PACED_1H_RECORD]
    assert S10_PACED_10M_RECORD in status_links
    assert S10_PACED_1H_RECORD in status_links
    assert by_path[S10_PACED_10M_RECORD]["step"] == PACED_10M_STATUS_STEP
    assert by_path[S10_PACED_10M_RECORD]["bridge apply"] == PACED_10M_STATUS_RESULT
    assert by_path[S10_PACED_1H_RECORD]["step"] == PACED_1H_STATUS_STEP
    assert by_path[S10_PACED_1H_RECORD]["bridge apply"] == PACED_1H_STATUS_RESULT
    assert S10_PACED_10M_RECORD not in current
    assert S10_PACED_1H_RECORD not in current
    assert S10_PACED_10M_RECORD not in q13_q14
    assert S10_PACED_1H_RECORD not in q13_q14
    assert current == [S10_BURST_BASELINE_RECORD, S10_PACED_R4_RECORD]
    assert q13_q14 == [S10_Q13_RECORD, S10_Q14_RECORD]


def test_paced_10m_1h_results_and_boundaries_remain_conservative() -> None:
    rows = {_identity_path(row["identity"]): row for row in _paced_10m_1h_rows()}
    ten_minutes = _row_text(rows[S10_PACED_10M_RECORD])
    one_hour = _row_text(rows[S10_PACED_1H_RECORD])
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))

    assert "10-minute" in rows[S10_PACED_10M_RECORD]["result"].lower()
    assert "one-hour" in rows[S10_PACED_1H_RECORD]["result"].lower()
    for phrase in S10_PACED_10M_RESULT_FACTS:
        assert phrase in ten_minutes
    for phrase in S10_PACED_1H_RESULT_FACTS:
        assert phrase in one_hour
    for phrase in S10_PACED_10M_BOUNDARIES:
        assert phrase in ten_minutes
    for phrase in S10_PACED_1H_BOUNDARIES:
        assert phrase in one_hour
    assert S10_100EPS_TRY_RECORD not in _paced_10m_1h_record_paths()
    assert manifest["production"]["status"] == "candidate"
    assert manifest["production"]["full_soak_plus_rollback_after_traffic"] == (
        "BLOCKED_HOST_CAPACITY"
    )


def test_finite_100eps_drain_section_follows_paced_and_precedes_golden() -> None:
    text = INDEX.read_text(encoding="utf-8")
    paced_at = text.index(PACED_10M_1H_HEADING)
    finite_drain_at = text.index(FINITE_100EPS_DRAIN_HEADING)
    golden_at = text.index(ACCEPTANCE_HEADING)
    between_finite_drain_and_golden = text[
        finite_drain_at + len(FINITE_100EPS_DRAIN_HEADING) : golden_at
    ]

    assert "Finite 2000-event" in FINITE_100EPS_DRAIN_HEADING
    assert "S10 drain record" in FINITE_100EPS_DRAIN_HEADING
    assert paced_at < finite_drain_at < golden_at
    assert "\n## " not in between_finite_drain_and_golden


def test_finite_100eps_drain_index_lists_one_bounded_record_with_required_fields() -> None:
    indexed = _finite_100eps_drain_record_paths()
    rows = _finite_100eps_drain_rows()

    assert indexed == [S10_100EPS_TRY_RECORD]
    assert Counter(indexed) == Counter([S10_100EPS_TRY_RECORD])
    assert list(rows[0]) == list(REQUIRED_FIELDS)
    assert len(rows) == 1
    for relative in FINITE_100EPS_DRAIN_OTHER_RECORDS:
        assert relative not in indexed
    row = rows[0]
    for field in REQUIRED_FIELDS:
        assert row[field].strip(), f"{field} is empty in {row!r}"
    assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
    assert row["date"] == FINITE_100EPS_DRAIN_DATE
    assert (ROOT / S10_100EPS_TRY_RECORD).is_file()
    targets = LINK_RE.findall(row["identity"])
    assert targets[0].startswith("../perf/"), row["identity"]


def test_finite_100eps_drain_is_not_a_supersession() -> None:
    section = _section(INDEX.read_text(encoding="utf-8"), FINITE_100EPS_DRAIN_HEADING).lower()
    row = _finite_100eps_drain_rows()[0]

    assert "different windows" in section
    assert "not a supersession chain" in section
    assert "historical facts remain valid" in section
    assert row["supersedes"] == "None"
    assert row["superseded by"] == "None"
    _assert_supersession_cell(row["supersedes"])
    _assert_supersession_cell(row["superseded by"])
    for rows in (
        _current_s10_throughput_rows(),
        _q13_q14_intermediate_s10_rows(),
        _paced_10m_1h_rows(),
    ):
        for other_row in rows:
            supersession_text = f"{other_row['supersedes']} {other_row['superseded by']}"
            assert S10_100EPS_TRY_RECORD not in [
                _resolve_index_link(target) for target in LINK_RE.findall(supersession_text)
            ]


def test_finite_100eps_drain_record_keeps_published_digest() -> None:
    assert _finite_100eps_drain_record_paths() == [S10_100EPS_TRY_RECORD]
    digest = hashlib.sha256((ROOT / S10_100EPS_TRY_RECORD).read_bytes()).hexdigest()
    assert digest == FINITE_100EPS_DRAIN_DIGEST


def test_finite_100eps_drain_status_row_matches_indexed_record() -> None:
    indexed = _finite_100eps_drain_record_paths()
    status_links = _status_record_links()
    bridge_rows = _status_table_rows(S10_R4_STATUS_HEADING)
    by_path: dict[str, dict[str, str]] = {}
    for row in bridge_rows:
        for path in _status_cell_record_paths(row.get("state", "")):
            by_path[path] = row

    assert indexed == [S10_100EPS_TRY_RECORD]
    assert S10_100EPS_TRY_RECORD in status_links
    assert by_path[S10_100EPS_TRY_RECORD]["step"] == FINITE_100EPS_STATUS_STEP
    assert by_path[S10_100EPS_TRY_RECORD]["bridge apply"] == FINITE_100EPS_STATUS_RESULT
    assert S10_100EPS_TRY_RECORD not in _current_s10_throughput_record_paths()
    assert S10_100EPS_TRY_RECORD not in _q13_q14_intermediate_s10_record_paths()
    assert S10_100EPS_TRY_RECORD not in _paced_10m_1h_record_paths()


def test_finite_100eps_drain_result_and_boundary_remain_conservative() -> None:
    row = _finite_100eps_drain_rows()[0]
    drain = _row_text(row)
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))

    assert "finite" in row["result"].lower()
    assert "drain" in row["result"].lower()
    for phrase in FINITE_100EPS_DRAIN_RESULT_FACTS:
        assert phrase in drain
    for phrase in FINITE_100EPS_DRAIN_BOUNDARIES:
        assert phrase in drain
    assert manifest["production"]["status"] == "candidate"
    assert manifest["production"]["full_soak_plus_rollback_after_traffic"] == (
        "BLOCKED_HOST_CAPACITY"
    )
