from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Queue

import httpx
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = PROJECT_ROOT / "docker-compose.prod.yml"
DEFAULT_STARTUP_TIMEOUT = int(os.getenv("AGENTFLOW_E2E_TIMEOUT", "120"))
SUPPORT_API_KEY = os.getenv("AGENTFLOW_E2E_SUPPORT_KEY", "af-prod-agent-support-abc123")
OPS_API_KEY = os.getenv("AGENTFLOW_E2E_OPS_KEY", "af-prod-agent-ops-def456")
RATE_LIMIT_API_KEY = os.getenv("AGENTFLOW_E2E_RATE_LIMIT_KEY", "af-prod-agent-rate-e2e000")


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_ready(base_url: str, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    health_url = f"{base_url.rstrip('/')}/v1/health"
    last_error = "service did not answer"

    while time.monotonic() < deadline:
        try:
            response = httpx.get(health_url, timeout=15.0)
            if response.status_code == 200:
                return
            last_error = f"unexpected status {response.status_code}"
        except httpx.HTTPError as exc:
            last_error = str(exc)
        time.sleep(1.0)

    raise RuntimeError(f"Timed out waiting for {health_url}: {last_error}")


def _tail(path: Path, lines: int = 40) -> str:
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(content[-lines:])


def _write_compose_override(path: Path, host_port: int) -> None:
    path.write_text(
        "\n".join([
            "services:",
            "  agentflow-api:",
            "    environment:",
            f"      AGENTFLOW_API_KEYS: \"{SUPPORT_API_KEY}:Support Agent,{OPS_API_KEY}:Ops Agent,{RATE_LIMIT_API_KEY}:Rate Limit Agent\"",
            "      AGENTFLOW_RATE_LIMIT_RPM: \"120\"",
            "      AGENTFLOW_USAGE_DB_PATH: /app/data/agentflow_api_usage.duckdb",
            "      AGENTFLOW_WEBHOOKS_FILE: /app/data/e2e-webhooks.yaml",
            "      OTEL_SDK_DISABLED: \"true\"",
            "    ports:",
            f"      - \"127.0.0.1:{host_port}:8000\"",
            "    extra_hosts:",
            "      - \"host.docker.internal:host-gateway\"",
        ]) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _compose_logs(compose_cmd: list[str]) -> str:
    result = subprocess.run(
        [*compose_cmd, "logs", "--tail", "80"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    output = (result.stdout or "") + (result.stderr or "")
    return output.strip()


def _start_compose_api(tmp_path: Path) -> dict[str, object]:
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    override_path = tmp_path / "docker-compose.e2e.override.yml"
    project_name = f"agentflow-e2e-{os.getpid()}-{int(time.time())}"
    compose_cmd = [
        "docker",
        "compose",
        "-p",
        project_name,
        "-f",
        str(COMPOSE_FILE),
        "-f",
        str(override_path),
    ]
    _write_compose_override(override_path, port)

    up_result = subprocess.run(
        [*compose_cmd, "up", "-d", "redis", "agentflow-api"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if up_result.returncode != 0:
        output = ((up_result.stdout or "") + (up_result.stderr or "")).strip()
        raise RuntimeError(f"Failed to start docker compose E2E stack.\n{output}")

    try:
        _wait_for_ready(base_url, DEFAULT_STARTUP_TIMEOUT)
    except Exception:
        logs = _compose_logs(compose_cmd)
        subprocess.run(
            [*compose_cmd, "down", "-v"],
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        raise RuntimeError(
            "AgentFlow docker-compose E2E stack failed to become ready.\n"
            f"Last compose log lines:\n{logs}"
        ) from None

    return {
        "base_url": base_url,
        "callback_host": "host.docker.internal",
        "compose_cmd": compose_cmd,
    }


def _start_local_api(tmp_path: Path) -> dict[str, object]:
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    log_path = tmp_path / "agentflow-api.log"
    env = {
        **os.environ,
        "AGENTFLOW_API_KEYS": (
            f"{SUPPORT_API_KEY}:Support Agent,"
            f"{OPS_API_KEY}:Ops Agent,"
            f"{RATE_LIMIT_API_KEY}:Rate Limit Agent"
        ),
        "AGENTFLOW_RATE_LIMIT_RPM": "120",
        "AGENTFLOW_USAGE_DB_PATH": str(tmp_path / "agentflow_usage.duckdb"),
        "AGENTFLOW_WEBHOOKS_FILE": str(tmp_path / "webhooks.yaml"),
        "DUCKDB_PATH": str(tmp_path / "agentflow.duckdb"),
        "PYTHONUNBUFFERED": "1",
    }

    log_file = log_path.open("w", encoding="utf-8", newline="\n")
    process = subprocess.Popen(
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
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        _wait_for_ready(base_url, DEFAULT_STARTUP_TIMEOUT)
    except Exception:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        log_file.close()
        raise RuntimeError(
            "AgentFlow API failed to start.\n"
            f"Last log lines:\n{_tail(log_path)}"
        ) from None

    return {
        "base_url": base_url,
        "process": process,
        "log_file": log_file,
        "log_path": log_path,
    }


@pytest.fixture(scope="session")
def e2e_env(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    external_base_url = os.getenv("AGENTFLOW_E2E_BASE_URL")
    if external_base_url:
        _wait_for_ready(external_base_url, DEFAULT_STARTUP_TIMEOUT)
        yield {
            "base_url": external_base_url.rstrip("/"),
            "support_api_key": SUPPORT_API_KEY,
            "ops_api_key": OPS_API_KEY,
            "rate_limit_api_key": RATE_LIMIT_API_KEY,
            "callback_host": os.getenv("AGENTFLOW_E2E_CALLBACK_HOST", "127.0.0.1"),
        }
        return

    runtime_dir = tmp_path_factory.mktemp("e2e-runtime")
    mode = os.getenv("AGENTFLOW_E2E_MODE", "local")
    if mode == "compose":
        started = _start_compose_api(runtime_dir)
    else:
        started = _start_local_api(runtime_dir)
    try:
        yield {
            "base_url": started["base_url"],
            "support_api_key": SUPPORT_API_KEY,
            "ops_api_key": OPS_API_KEY,
            "rate_limit_api_key": RATE_LIMIT_API_KEY,
            "callback_host": started.get("callback_host", "127.0.0.1"),
            "api_log_path": started.get("log_path"),
        }
    finally:
        compose_cmd = started.get("compose_cmd")
        if isinstance(compose_cmd, list):
            subprocess.run(
                [*compose_cmd, "down", "-v"],
                cwd=PROJECT_ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
        else:
            process = started["process"]
            log_file = started["log_file"]
            assert isinstance(process, subprocess.Popen)
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
            assert hasattr(log_file, "close")
            log_file.close()


@pytest.fixture(scope="session")
def base_url(e2e_env: dict[str, object]) -> str:
    return str(e2e_env["base_url"])


@pytest.fixture(scope="session")
def support_api_key(e2e_env: dict[str, object]) -> str:
    return str(e2e_env["support_api_key"])


@pytest.fixture(scope="session")
def ops_api_key(e2e_env: dict[str, object]) -> str:
    return str(e2e_env["ops_api_key"])


@pytest.fixture(scope="session")
def rate_limit_api_key(e2e_env: dict[str, object]) -> str:
    return str(e2e_env["rate_limit_api_key"])


@pytest.fixture(scope="session")
def callback_host(e2e_env: dict[str, object]) -> str:
    return str(e2e_env.get("callback_host", "127.0.0.1"))


@pytest.fixture
def api_client(base_url: str):
    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        yield client


@pytest.fixture
def support_headers(support_api_key: str) -> dict[str, str]:
    return {"X-API-Key": support_api_key}


@pytest.fixture
def ops_headers(ops_api_key: str) -> dict[str, str]:
    return {"X-API-Key": ops_api_key}


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self.server.events.put({
            "path": self.path,
            "headers": dict(self.headers.items()),
            "body": body,
        })
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{\"ok\": true}")

    def log_message(self, format: str, *args: object) -> None:
        return


@pytest.fixture
def webhook_receiver(callback_host: str):
    server = ThreadingHTTPServer(("0.0.0.0", 0), _CallbackHandler)
    server.events = Queue()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield {
            "url": f"http://{callback_host}:{server.server_port}/callback",
            "events": server.events,
        }
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
