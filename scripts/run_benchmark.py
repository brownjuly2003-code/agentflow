"""Run the AgentFlow load benchmark and generate docs/benchmark.md."""

from __future__ import annotations

import argparse
import csv
import ctypes
import http.client
import importlib.util
import json
import os
import platform
import re
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[1]
README_PATH = PROJECT_ROOT / "README.md"
REPORT_PATH = PROJECT_ROOT / "docs" / "benchmark.md"
RESULTS_PATH = PROJECT_ROOT / ".artifacts" / "benchmark" / "current.json"
CANONICAL_USERS = 50
CANONICAL_SPAWN_RATE = 10
CANONICAL_RUN_TIME_SECONDS = 60
WARMUP_SECONDS = 10
BenchmarkRow = dict[str, float | int | str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the AgentFlow Locust benchmark and write docs/benchmark.md.",
    )
    parser.add_argument("--host")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--users", type=int, default=50)
    parser.add_argument("--spawn-rate", type=int, default=10)
    parser.add_argument("--run-time", default="60s")
    parser.add_argument("--burst", type=int, default=500)
    parser.add_argument("--results-json", "--output", dest="results_json", default=str(RESULTS_PATH))
    parser.add_argument("--report-path", default=str(REPORT_PATH))
    return parser.parse_args()


def parse_float(value: str | None) -> float:
    if not value:
        return 0.0
    return float(value)


def parse_int(value: str | None) -> int:
    if not value:
        return 0
    return int(float(value))


def format_ms(value: float) -> str:
    return f"{value:.1f} ms"


def format_rps(value: float) -> str:
    return f"{value:.2f}"


def format_percent(value: float) -> str:
    return f"{value:.2f}%"


def format_ram_gb(value: float | None) -> str:
    if value is None:
        return "unknown"
    return f"{value:.1f} GB"


def read_readme_claims() -> dict[str, float] | None:
    text = README_PATH.read_text(encoding="utf-8")
    patterns = {
        "p50": r"\| Agent API response \(p50\) \| [^|]+ \| ~?([0-9]+(?:\.[0-9]+)?)ms \|",
        "p99": r"\| Agent API response \(p99\) \| [^|]+ \| ~?([0-9]+(?:\.[0-9]+)?)ms \|",
    }
    claims: dict[str, float] = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        if not match:
            return None
        claims[key] = float(match.group(1))
    return claims


def detect_total_memory_gb() -> float | None:
    if sys.platform == "win32":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return status.ullTotalPhys / (1024**3)
        return None

    if hasattr(os, "sysconf"):
        page_size = os.sysconf("SC_PAGE_SIZE")
        page_count = os.sysconf("SC_PHYS_PAGES")
        return (page_size * page_count) / (1024**3)

    return None


def collect_system_info() -> dict[str, str]:
    cpu_name = platform.processor() or platform.machine() or "unknown"
    return {
        "os": platform.platform(),
        "cpu": cpu_name,
        "cpu_count": str(os.cpu_count() or 0),
        "ram": format_ram_gb(detect_total_memory_gb()),
        "python": platform.python_version(),
    }


def is_port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def resolve_port(requested_port: int) -> int:
    if is_port_available(requested_port):
        return requested_port

    if requested_port != 8001:
        raise RuntimeError(f"Port {requested_port} is already in use.")

    for candidate in range(8002, 8021):
        if is_port_available(candidate):
            return candidate

    raise RuntimeError("Could not find a free port in the 8001-8020 range.")


def resolve_host_seed_db_path(host: str) -> Path | None:
    hostname = urlsplit(host).hostname
    if hostname not in {"127.0.0.1", "localhost"}:
        return None
    db_path = Path(os.getenv("DUCKDB_PATH", "agentflow_demo.duckdb"))
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path
    return db_path


def maybe_seed_host_fixtures(host: str) -> None:
    db_path = resolve_host_seed_db_path(host)
    if db_path is None:
        return
    try:
        seed_benchmark_fixtures(db_path)
    except duckdb.IOException as exc:
        print(
            "Skipping benchmark fixture seed for host run: "
            f"{db_path} is unavailable ({exc})."
        )


def ensure_locust_available() -> None:
    if importlib.util.find_spec("locust") is None:
        raise RuntimeError("Locust is not installed. Run `pip install -e \".[load]\"` first.")


def seed_benchmark_fixtures(db_path: Path) -> None:
    conn = duckdb.connect(str(db_path))
    try:
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


def run_command(command: list[str], env: dict[str, str], label: str) -> None:
    result = subprocess.run(  # noqa: S603
        command,
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return

    output = "\n".join(
        chunk for chunk in (result.stdout.strip(), result.stderr.strip()) if chunk
    )
    raise RuntimeError(f"{label} failed with exit code {result.returncode}.\n{output}")


def start_api(env: dict[str, str], port: int) -> subprocess.Popen[str]:
    return subprocess.Popen(  # noqa: S603
        [
            sys.executable,
            "-m",
            "uvicorn",
            "src.serving.api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )


def wait_for_api(
    host: str,
    port: int,
    process: subprocess.Popen[str],
    timeout_seconds: float = 30.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            logs = process.stdout.read() if process.stdout else ""
            raise RuntimeError(f"API exited before becoming healthy.\n{logs}")
        try:
            connection = http.client.HTTPConnection(host, port, timeout=2)
            connection.request("GET", "/v1/catalog")
            response = connection.getresponse()
            response.read()
            connection.close()
            if response.status == 200:
                return
        except OSError:
            time.sleep(0.5)

    raise RuntimeError(f"Timed out waiting for API at http://{host}:{port}.")


def stop_api(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return

    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def load_locust_stats(stats_path: Path) -> tuple[BenchmarkRow, list[BenchmarkRow]]:
    aggregate: BenchmarkRow | None = None
    rows: list[BenchmarkRow] = []

    with stats_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            name = (row.get("Name") or "").strip()
            request_count = parse_int(row.get("Request Count"))
            if not name or request_count == 0:
                continue

            parsed_row: BenchmarkRow = {
                "method": (row.get("Type") or "").strip(),
                "name": name,
                "request_count": request_count,
                "failure_count": parse_int(row.get("Failure Count")),
                "rps": parse_float(row.get("Requests/s")),
                "p50": parse_float(row.get("50%")),
                "p95": parse_float(row.get("95%")),
                "p99": parse_float(row.get("99%")),
            }
            failure_count = int(parsed_row["failure_count"])
            parsed_row["failure_rate"] = (
                (failure_count / request_count) * 100 if request_count else 0.0
            )

            if name == "Aggregated":
                aggregate = parsed_row
            else:
                rows.append(parsed_row)

    if aggregate is None:
        raise RuntimeError(f"Locust stats file did not contain an Aggregated row: {stats_path}")

    return aggregate, rows


def build_comparison_section(
    aggregate: BenchmarkRow,
    claims: dict[str, float] | None,
    endpoint_rows: list[BenchmarkRow],
    users: int,
) -> list[str]:
    measured_p50 = float(aggregate["p50"])
    measured_p99 = float(aggregate["p99"])
    if claims is None:
        lines = [
            "- README no longer carries a benchmark claim table, so this run is compared against the release gate instead of documentation copy.",
            f"- Measured aggregate: p50 {format_ms(measured_p50)}, p99 {format_ms(measured_p99)}.",
            "- Release gate for `/v1/entity/*`: p50 < 100 ms and p99 < 500 ms.",
        ]
        entity_rows = [
            row for row in endpoint_rows if str(row["name"]).startswith("/v1/entity/")
        ]
        if entity_rows:
            slowest_entity = max(entity_rows, key=lambda row: float(row["p99"]))
            endpoint_name = f"{slowest_entity['method']} {slowest_entity['name']}".strip()
            lines.append(
                f"- Slowest entity endpoint in this run: `{endpoint_name}` "
                f"at p50 {format_ms(float(slowest_entity['p50']))}, "
                f"p99 {format_ms(float(slowest_entity['p99']))}."
            )
        lines.append(
            f"- Aggregate throughput was {format_rps(float(aggregate['rps']))} RPS "
            f"with `{users}` concurrent users."
        )
        return lines

    claim_p50 = claims["p50"]
    claim_p99 = claims["p99"]

    lines = [
        f"- README claim: overall Agent API p50 ~{claim_p50:.0f} ms, p99 ~{claim_p99:.0f} ms.",
        f"- Measured aggregate: p50 {format_ms(measured_p50)}, p99 {format_ms(measured_p99)}.",
    ]

    slower_reasons: list[str] = []
    if measured_p50 > claim_p50:
        slower_reasons.append(f"p50 is {(measured_p50 / claim_p50 - 1) * 100:.1f}% slower")
    if measured_p99 > claim_p99:
        slower_reasons.append(f"p99 is {(measured_p99 / claim_p99 - 1) * 100:.1f}% slower")

    if slower_reasons:
        reason_text = " and ".join(slower_reasons)
        lines.append(
            "- Result: deviation detected; "
            f"{reason_text}. This run was measured on the local single-process environment above."
        )
        if endpoint_rows:
            slowest = max(endpoint_rows, key=lambda row: float(row["p99"]))
            slowest_endpoint = f"{slowest['method']} {slowest['name']}".strip()
            lines.append(
                f"- Slowest endpoint in this run: `{slowest_endpoint}` "
                f"at p99 {format_ms(float(slowest['p99']))}."
            )
        lines.append(
            f"- Aggregate throughput was {format_rps(float(aggregate['rps']))} RPS "
            f"with `{users}` concurrent users, which indicates queueing under local saturation."
        )
    else:
        lines.append("- Result: measured latency matches or beats the current README claim.")

    return lines


def build_report(
    *,
    generated_at: str,
    base_url: str,
    burst: int,
    users: int,
    spawn_rate: int,
    run_time: str,
    system_info: dict[str, str],
    claims: dict[str, float] | None,
    aggregate: BenchmarkRow,
    endpoint_rows: list[BenchmarkRow],
) -> str:
    run_time_match = re.fullmatch(r"\s*(\d+)\s*([smh])\s*", run_time)
    run_time_seconds = CANONICAL_RUN_TIME_SECONDS
    if run_time_match:
        value = int(run_time_match.group(1))
        unit = run_time_match.group(2).lower()
        multiplier = {"s": 1, "m": 60, "h": 3600}[unit]
        run_time_seconds = value * multiplier
    is_below_canonical_baseline = (
        users < CANONICAL_USERS
        or spawn_rate < CANONICAL_SPAWN_RATE
        or run_time_seconds < CANONICAL_RUN_TIME_SECONDS
    )
    lines = [
        "# AgentFlow Benchmark Report",
        "",
        f"Generated: `{generated_at}`",
        "",
        "## System Under Test",
        "",
        f"- OS: `{system_info['os']}`",
        f"- CPU: `{system_info['cpu']}` ({system_info['cpu_count']} logical cores)",
        f"- RAM: `{system_info['ram']}`",
        f"- Python: `{system_info['python']}`",
        "",
        "## Test Parameters",
        "",
        f"- Host: `{base_url}`",
        f"- Seed step: `python -m src.processing.local_pipeline --burst {burst}`",
        f"- Load profile: `{users}` users, spawn rate `{spawn_rate}/s`, duration `{run_time}`",
        (
            f"- Warmup: `{WARMUP_SECONDS}s` discarded pre-run with the same Locust traffic mix "
            "to reduce cold-start noise."
        ),
        "- Locust file: `tests/load/locustfile.py`",
        "",
        "## Results",
        "",
        "| Endpoint | Requests | Failures | Failure Rate | RPS | p50 | p95 | p99 |",
        "|----------|----------|----------|--------------|-----|-----|-----|-----|",
        (
            "| ALL | "
            f"{int(aggregate['request_count'])} | "
            f"{int(aggregate['failure_count'])} | "
            f"{format_percent(float(aggregate['failure_rate']))} | "
            f"{format_rps(float(aggregate['rps']))} | "
            f"{format_ms(float(aggregate['p50']))} | "
            f"{format_ms(float(aggregate['p95']))} | "
            f"{format_ms(float(aggregate['p99']))} |"
        ),
    ]

    for row in endpoint_rows:
        endpoint = f"{row['method']} {row['name']}".strip()
        lines.append(
            f"| {endpoint} | "
            f"{int(row['request_count'])} | "
            f"{int(row['failure_count'])} | "
            f"{format_percent(float(row['failure_rate']))} | "
            f"{format_rps(float(row['rps']))} | "
            f"{format_ms(float(row['p50']))} | "
            f"{format_ms(float(row['p95']))} | "
            f"{format_ms(float(row['p99']))} |"
        )

    lines.extend(
        [
            "",
            "## Release Gate Context",
            "",
            *build_comparison_section(aggregate, claims, endpoint_rows, users),
            "",
            "## Notes",
            "",
            (
                "- Benchmark comparability: this run is below canonical baseline "
                f"({CANONICAL_USERS} users, spawn rate {CANONICAL_SPAWN_RATE}/s, "
                f"duration {CANONICAL_RUN_TIME_SECONDS}s); compare against committed baselines cautiously."
            )
            if is_below_canonical_baseline
            else (
                "- Benchmark comparability: this run matches or exceeds the canonical baseline "
                f"({CANONICAL_USERS} users, spawn rate {CANONICAL_SPAWN_RATE}/s, "
                f"duration {CANONICAL_RUN_TIME_SECONDS}s)."
            ),
            "- This report is generated from a fresh DuckDB dataset on every run.",
            (
                "- Re-running `python scripts/run_benchmark.py` overwrites this file "
                "with new measurements."
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    ensure_locust_available()
    claims = read_readme_claims()
    system_info = collect_system_info()
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    results_path = Path(args.results_json)
    if not results_path.is_absolute():
        results_path = PROJECT_ROOT / results_path
    report_path = Path(args.report_path)
    if not report_path.is_absolute():
        report_path = PROJECT_ROOT / report_path

    with tempfile.TemporaryDirectory(prefix="agentflow-benchmark-") as temp_dir:
        temp_path = Path(temp_dir)
        db_path = temp_path / "benchmark.duckdb"
        csv_prefix = temp_path / "agentflow_benchmark"

        env = os.environ.copy()
        if args.host:
            base_url = args.host.rstrip("/")
            maybe_seed_host_fixtures(base_url)
        else:
            resolved_port = resolve_port(args.port)
            base_url = f"http://127.0.0.1:{resolved_port}"
            if resolved_port != args.port:
                print(f"Port {args.port} is busy; using {resolved_port} instead.")
            env["DUCKDB_PATH"] = str(db_path)
            env["AGENTFLOW_API_KEYS"] = ""
            env["AGENTFLOW_API_KEYS_FILE"] = ""
            env["AGENTFLOW_ADMIN_KEY"] = ""
            env["AGENTFLOW_USAGE_DB_PATH"] = str(temp_path / "benchmark_api_usage.duckdb")
            run_command(
                [
                    sys.executable,
                    "-m",
                    "src.processing.local_pipeline",
                    "--burst",
                    str(args.burst),
                ],
                env,
                "Demo data seed",
            )
            seed_benchmark_fixtures(db_path)
            api_process = start_api(env, resolved_port)
            try:
                wait_for_api("127.0.0.1", resolved_port, api_process)
                run_command(
                    [
                        sys.executable,
                        "-m",
                        "locust",
                        "-f",
                        "tests/load/locustfile.py",
                        "--headless",
                        "-u",
                        str(args.users),
                        "-r",
                        str(args.spawn_rate),
                        "--run-time",
                        f"{WARMUP_SECONDS}s",
                        "--host",
                        base_url,
                        "--csv",
                        str(temp_path / "agentflow_benchmark_warmup"),
                    ],
                    env,
                    "Locust warmup",
                )
                run_command(
                    [
                        sys.executable,
                        "-m",
                        "locust",
                        "-f",
                        "tests/load/locustfile.py",
                        "--headless",
                        "-u",
                        str(args.users),
                        "-r",
                        str(args.spawn_rate),
                        "--run-time",
                        args.run_time,
                        "--host",
                        base_url,
                        "--csv",
                        str(csv_prefix),
                    ],
                    env,
                    "Locust benchmark",
                )
            finally:
                stop_api(api_process)
        if args.host:
            run_command(
                [
                    sys.executable,
                    "-m",
                    "locust",
                    "-f",
                    "tests/load/locustfile.py",
                    "--headless",
                    "-u",
                    str(args.users),
                    "-r",
                    str(args.spawn_rate),
                    "--run-time",
                    f"{WARMUP_SECONDS}s",
                    "--host",
                    base_url,
                    "--csv",
                    str(temp_path / "agentflow_benchmark_warmup"),
                ],
                env,
                "Locust warmup",
            )
            run_command(
                [
                    sys.executable,
                    "-m",
                    "locust",
                    "-f",
                    "tests/load/locustfile.py",
                    "--headless",
                    "-u",
                    str(args.users),
                    "-r",
                    str(args.spawn_rate),
                    "--run-time",
                    args.run_time,
                    "--host",
                    base_url,
                    "--csv",
                    str(csv_prefix),
                ],
                env,
                "Locust benchmark",
            )

        aggregate, endpoint_rows = load_locust_stats(Path(f"{csv_prefix}_stats.csv"))
        report = build_report(
            generated_at=generated_at,
            base_url=base_url,
            burst=args.burst,
            users=args.users,
            spawn_rate=args.spawn_rate,
            run_time=args.run_time,
            system_info=system_info,
            claims=claims,
            aggregate=aggregate,
            endpoint_rows=endpoint_rows,
        )

    endpoints = {}
    for row in endpoint_rows:
        endpoint = f"{row['method']} {row['name']}".strip()
        endpoints[endpoint] = {
            "request_count": int(row["request_count"]),
            "failure_count": int(row["failure_count"]),
            "failure_rate_percent": float(row["failure_rate"]),
            "requests_per_second": float(row["rps"]),
            "p50_ms": float(row["p50"]),
            "p95_ms": float(row["p95"]),
            "p99_ms": float(row["p99"]),
        }
    results_payload = {
        "generated_at": generated_at,
        "source": "scripts/run_benchmark.py",
        "host": base_url,
        "load_profile": {
            "users": args.users,
            "spawn_rate": args.spawn_rate,
            "run_time": args.run_time,
        },
        "aggregate": {
            "request_count": int(aggregate["request_count"]),
            "failure_count": int(aggregate["failure_count"]),
            "failure_rate_percent": float(aggregate["failure_rate"]),
            "requests_per_second": float(aggregate["rps"]),
            "p50_ms": float(aggregate["p50"]),
            "p95_ms": float(aggregate["p95"]),
            "p99_ms": float(aggregate["p99"]),
        },
        "endpoints": endpoints,
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(report)
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(
        json.dumps(results_payload, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print(f"Wrote benchmark report to {report_path}")
    print(f"Wrote benchmark results to {results_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130) from None
