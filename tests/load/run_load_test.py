from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from tests.load.thresholds import LOAD_PROFILE, THRESHOLDS


def test_load_locust_rows_parses_endpoint_metrics(tmp_path: Path):
    csv_path = tmp_path / "stats.csv"
    csv_path.write_text(
        "\n".join(
            [
                "Type,Name,Request Count,Failure Count,Requests/s,50%,95%,99%",
                "GET,/v1/entity/order/{id},10,0,5.0,12,20,30",
                "POST,/v1/query,4,1,1.5,100,500,900",
                "GET,Aggregated,14,1,6.5,15,30,45",
            ]
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    rows = load_locust_rows(csv_path)

    assert rows["GET /v1/entity/order/{id}"]["request_count"] == 10
    assert rows["GET /v1/entity/order/{id}"]["fail_ratio"] == 0
    assert rows["POST /v1/query"]["p95_ms"] == 500.0
    assert "ALL" in rows


def test_check_thresholds_reports_latency_and_error_violations():
    violations = check_thresholds(
        {
            "GET /v1/entity/order/{id}": {
                "request_count": 12,
                "failure_count": 1,
                "fail_ratio": 1 / 12,
                "p95_ms": 65.0,
                "p99_ms": 90.0,
                "rps": 4.0,
            },
            "GET /v1/health": {
                "request_count": 20,
                "failure_count": 0,
                "fail_ratio": 0.0,
                "p95_ms": 5.0,
                "p99_ms": 6.0,
                "rps": 10.0,
            },
        }
    )

    assert violations == [
        "GET /v1/entity/order/{id}: p95 65.0 ms exceeds threshold 50.0 ms",
        "GET /v1/entity/order/{id}: error rate 8.33% exceeds threshold 1.00%",
    ]


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATS_PREFIX = PROJECT_ROOT / "tests" / "load" / "results"
DEFAULT_RESULTS_PATH = PROJECT_ROOT / "tests" / "load" / "results.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="http://127.0.0.1:8000")
    parser.add_argument("--stats-prefix", default=str(DEFAULT_STATS_PREFIX))
    parser.add_argument("--results-json", default=str(DEFAULT_RESULTS_PATH))
    parser.add_argument("--duckdb-path")
    parser.add_argument("--seed-data", action="store_true")
    parser.add_argument("--seed-only", action="store_true")
    return parser.parse_args()


def _parse_int(value: str | None) -> int:
    if not value:
        return 0
    return int(float(value))


def _parse_float(value: str | None) -> float:
    if not value:
        return 0.0
    return float(value)


def load_locust_rows(stats_csv: Path) -> dict[str, dict[str, float | int]]:
    rows: dict[str, dict[str, float | int]] = {}
    with stats_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            request_count = _parse_int(row.get("Request Count"))
            name = (row.get("Name") or "").strip()
            if not name or request_count == 0:
                continue

            method = (row.get("Type") or "").strip().upper()
            endpoint = "ALL" if name == "Aggregated" else f"{method} {name}"
            failure_count = _parse_int(row.get("Failure Count"))
            rows[endpoint] = {
                "request_count": request_count,
                "failure_count": failure_count,
                "fail_ratio": failure_count / request_count if request_count else 0.0,
                "rps": _parse_float(row.get("Requests/s")),
                "p50_ms": _parse_float(row.get("50%")),
                "p95_ms": _parse_float(row.get("95%")),
                "p99_ms": _parse_float(row.get("99%")),
            }
    return rows


def check_thresholds(rows: dict[str, dict[str, float | int]]) -> list[str]:
    violations: list[str] = []
    for endpoint, limits in THRESHOLDS.items():
        metrics = rows.get(endpoint)
        if metrics is None:
            continue

        p95_ms = float(metrics["p95_ms"])
        fail_ratio = float(metrics["fail_ratio"])
        if p95_ms > limits["p95_ms"]:
            violations.append(
                f"{endpoint}: p95 {p95_ms:.1f} ms exceeds threshold {limits['p95_ms']:.1f} ms"
            )
        if fail_ratio > limits["error_rate_max"]:
            violations.append(
                f"{endpoint}: error rate {fail_ratio:.2%} exceeds threshold "
                f"{limits['error_rate_max']:.2%}"
            )
    return violations


def find_missing_thresholds(rows: dict[str, dict[str, float | int]]) -> list[str]:
    return [endpoint for endpoint in THRESHOLDS if endpoint not in rows]


def seed_benchmark_data(duckdb_path: Path) -> None:
    import duckdb

    duckdb_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(duckdb_path))
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS orders_v2 (
                order_id VARCHAR PRIMARY KEY,
                user_id VARCHAR,
                status VARCHAR,
                total_amount DECIMAL(10,2),
                currency VARCHAR DEFAULT 'USD',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS products_current (
                product_id VARCHAR PRIMARY KEY,
                name VARCHAR,
                category VARCHAR,
                price DECIMAL(10,2),
                in_stock BOOLEAN DEFAULT TRUE,
                stock_quantity INTEGER DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions_aggregated (
                session_id VARCHAR PRIMARY KEY,
                user_id VARCHAR,
                started_at TIMESTAMP,
                ended_at TIMESTAMP,
                duration_seconds FLOAT,
                event_count INTEGER,
                unique_pages INTEGER,
                funnel_stage VARCHAR,
                is_conversion BOOLEAN DEFAULT FALSE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users_enriched (
                user_id VARCHAR PRIMARY KEY,
                total_orders INTEGER DEFAULT 0,
                total_spent DECIMAL(10,2) DEFAULT 0,
                first_order_at TIMESTAMP,
                last_order_at TIMESTAMP,
                preferred_category VARCHAR
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pipeline_events (
                event_id VARCHAR,
                topic VARCHAR,
                event_type VARCHAR,
                latency_ms INTEGER,
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO products_current VALUES
            ('PROD-001', 'Wireless Headphones', 'electronics', 79.99, TRUE, 142),
            ('PROD-002', 'Running Shoes', 'footwear', 129.99, TRUE, 58),
            ('PROD-003', 'Coffee Maker', 'kitchen', 49.99, TRUE, 203),
            ('PROD-004', 'Mechanical Keyboard', 'electronics', 149.99, TRUE, 37),
            ('PROD-005', 'Yoga Mat', 'fitness', 34.99, TRUE, 315),
            ('PROD-006', 'Backpack', 'accessories', 89.99, TRUE, 94),
            ('PROD-007', 'Water Bottle', 'fitness', 24.99, TRUE, 421),
            ('PROD-008', 'Desk Lamp', 'home', 44.99, FALSE, 0),
            ('PROD-009', 'Bluetooth Speaker', 'electronics', 59.99, TRUE, 167),
            ('PROD-010', 'Sunglasses', 'accessories', 119.99, TRUE, 72)
            """
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO orders_v2 VALUES
            ('ORD-20260404-1001', 'USR-10001', 'delivered',
             159.98, 'USD', NOW() - INTERVAL '2 hours'),
            ('ORD-20260404-1002', 'USR-10002', 'shipped',
             129.99, 'USD', NOW() - INTERVAL '90 minutes'),
            ('ORD-20260404-1003', 'USR-10001', 'confirmed',
             249.97, 'USD', NOW() - INTERVAL '1 hour'),
            ('ORD-20260404-1004', 'USR-10003', 'pending',
             79.99, 'USD', NOW() - INTERVAL '45 minutes'),
            ('ORD-20260404-1005', 'USR-10004', 'delivered',
             89.99, 'USD', NOW() - INTERVAL '30 minutes'),
            ('ORD-20260404-1006', 'USR-10002', 'cancelled',
             34.99, 'USD', NOW() - INTERVAL '20 minutes'),
            ('ORD-20260404-1007', 'USR-10005', 'confirmed',
             179.98, 'USD', NOW() - INTERVAL '15 minutes'),
            ('ORD-20260404-1008', 'USR-10003', 'pending',
             59.99, 'USD', NOW() - INTERVAL '5 minutes')
            """
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO users_enriched VALUES
            ('USR-10001', 15, 2340.50, NOW() - INTERVAL '180 days',
             NOW() - INTERVAL '1 hour', 'electronics'),
            ('USR-10002', 8, 890.20, NOW() - INTERVAL '90 days',
             NOW() - INTERVAL '20 minutes', 'footwear'),
            ('USR-10003', 3, 210.00, NOW() - INTERVAL '30 days',
             NOW() - INTERVAL '5 minutes', 'electronics'),
            ('USR-10004', 22, 4100.75, NOW() - INTERVAL '365 days',
             NOW() - INTERVAL '30 minutes', 'accessories'),
            ('USR-10005', 1, 179.98, NOW() - INTERVAL '1 day',
             NOW() - INTERVAL '15 minutes', 'electronics')
            """
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO sessions_aggregated VALUES
            ('SES-a1b2c3', 'USR-10001',
             NOW() - INTERVAL '2 hours',
             NOW() - INTERVAL '100 minutes',
             1200, 14, 6, 'checkout', TRUE),
            ('SES-d4e5f6', 'USR-10002',
             NOW() - INTERVAL '90 minutes',
             NOW() - INTERVAL '70 minutes',
             1200, 8, 4, 'add_to_cart', FALSE),
            ('SES-g7h8i9', NULL,
             NOW() - INTERVAL '60 minutes',
             NOW() - INTERVAL '58 minutes',
             120, 2, 2, 'bounce', FALSE),
            ('SES-j1k2l3', 'USR-10003',
             NOW() - INTERVAL '45 minutes',
             NOW() - INTERVAL '20 minutes',
             1500, 11, 5, 'checkout', TRUE),
            ('SES-m4n5o6', 'USR-10004',
             NOW() - INTERVAL '30 minutes',
             NOW() - INTERVAL '15 minutes',
             900, 6, 3, 'product_view', FALSE),
            ('SES-p7q8r9', 'USR-10005',
             NOW() - INTERVAL '20 minutes',
             NULL, NULL, 3, 2, 'browse', FALSE)
            """
        )
        conn.execute("DELETE FROM pipeline_events")
        conn.execute(
            """
            INSERT INTO pipeline_events
            (event_id, topic, event_type, latency_ms, processed_at)
            VALUES
            ('evt-001', 'events.validated', 'order.created', 220, NOW() - INTERVAL '10 minutes'),
            ('evt-002', 'events.validated', 'payment.initiated', 180, NOW() - INTERVAL '9 minutes'),
            ('evt-003', 'events.validated', 'page_view', 160, NOW() - INTERVAL '8 minutes'),
            ('evt-004', 'events.deadletter', 'order.created', 0, NOW() - INTERVAL '7 minutes'),
            ('evt-005', 'events.validated', 'product.updated', 110, NOW() - INTERVAL '6 minutes'),
            ('evt-006', 'events.validated', 'order.confirmed', 210, NOW() - INTERVAL '5 minutes'),
            ('evt-007', 'events.validated', 'payment.captured', 190, NOW() - INTERVAL '4 minutes'),
            ('evt-008', 'events.validated', 'add_to_cart', 150, NOW() - INTERVAL '3 minutes'),
            ('evt-009', 'events.deadletter', 'payment.failed', 0, NOW() - INTERVAL '2 minutes'),
            ('evt-010', 'events.validated', 'order.shipped', 205, NOW() - INTERVAL '1 minute')
            """
        )
    finally:
        conn.close()


def run_locust(host: str, stats_prefix: Path) -> Path:
    stats_prefix.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "locust",
        "-f",
        "tests/load/locustfile.py",
        "--host",
        host,
        "--users",
        str(LOAD_PROFILE["users"]),
        "--spawn-rate",
        str(LOAD_PROFILE["spawn_rate"]),
        "--run-time",
        str(LOAD_PROFILE["run_time"]),
        "--headless",
        "--csv",
        str(stats_prefix),
        "--exit-code-on-error",
        "0",
    ]
    result = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
    if result.returncode != 0:
        raise SystemExit(result.returncode)
    return Path(f"{stats_prefix}_stats.csv")


def write_results(
    rows: dict[str, dict[str, float | int]],
    output_path: Path,
    host: str,
    violations: list[str],
) -> None:
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "host": host,
        "load_profile": LOAD_PROFILE,
        "thresholds": THRESHOLDS,
        "aggregate": rows.get("ALL"),
        "endpoints": {key: value for key, value in rows.items() if key != "ALL"},
        "violations": violations,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    args = parse_args()

    if args.duckdb_path and (args.seed_data or args.seed_only):
        seed_benchmark_data(Path(args.duckdb_path))
        print(f"Seeded benchmark data into {args.duckdb_path}")
        if args.seed_only:
            return 0

    if args.seed_only:
        raise SystemExit("--seed-only requires --duckdb-path")

    stats_prefix = Path(args.stats_prefix)
    if not stats_prefix.is_absolute():
        stats_prefix = PROJECT_ROOT / stats_prefix
    results_path = Path(args.results_json)
    if not results_path.is_absolute():
        results_path = PROJECT_ROOT / results_path

    stats_csv = run_locust(args.host, stats_prefix)
    rows = load_locust_rows(stats_csv)
    violations = check_thresholds(rows)
    missing = find_missing_thresholds(rows)
    violations.extend(
        f"{endpoint}: no load-test stats collected for thresholded endpoint"
        for endpoint in missing
    )
    write_results(rows, results_path, args.host, violations)

    if violations:
        print("\nLoad-test threshold violations:")
        for violation in violations:
            print(f"- {violation}")
        return 1

    print("\nAll load-test thresholds met.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
