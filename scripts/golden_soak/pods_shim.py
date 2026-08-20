#!/usr/bin/env python3
"""Expose two identity-bound Compose containers as a narrow Kubernetes PodList."""

from __future__ import annotations

import argparse
import hmac
import http.client
import json
import re
import socket
import ssl
import sys
import urllib.parse
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Protocol

MAX_REQUEST_TARGET_BYTES = 2048
MAX_HEADER_BYTES = 8192
MAX_DOCKER_RESPONSE_BYTES = 1024 * 1024
MAX_RESPONSE_BYTES = 64 * 1024
MAX_TOKEN_BYTES = 512

_CONTAINER_ID_RE = re.compile(r"^[0-9a-f]{64}$")
_PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
_NAMESPACE_RE = re.compile(r"^[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?$")
_DOCKER_API_VERSION_RE = re.compile(r"^1\.(?:0|[1-9][0-9]{0,2})$")

_MIN_DOCKER_API_VERSION = (1, 41)
_MAX_DOCKER_API_VERSION = (1, 53)


class ShimError(RuntimeError):
    """A sanitized, fail-closed shim error."""


class Inspector(Protocol):
    def inspect(self, container_id: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ShimConfig:
    project_name: str
    jobmanager_id: str
    taskmanager_id: str
    namespace: str
    label_selector: str


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: Path, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self._socket_path = socket_path

    def connect(self) -> None:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(self.timeout)
        connection.connect(str(self._socket_path))
        self.sock = connection


class DockerSocketInspector:
    """Read one exact container document from the Docker Engine API."""

    def __init__(
        self,
        socket_path: Path,
        *,
        timeout_s: float = 5.0,
    ) -> None:
        self.socket_path = socket_path
        self.timeout_s = timeout_s
        self._api_version: str | None = None

    def _request_json(
        self,
        path: str,
        *,
        unavailable_reason: str,
        malformed_reason: str,
        payload_reason: str,
        failed_reason: str,
    ) -> dict[str, Any]:
        connection = _UnixHTTPConnection(self.socket_path, self.timeout_s)
        try:
            connection.request(
                "GET",
                path,
                headers={"Accept": "application/json", "Connection": "close"},
            )
            response = connection.getresponse()
            body = response.read(MAX_DOCKER_RESPONSE_BYTES + 1)
            if len(body) > MAX_DOCKER_RESPONSE_BYTES:
                raise ShimError("docker_response_too_large")
            if response.status != 200:
                raise ShimError(unavailable_reason)
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ShimError(malformed_reason) from exc
            if not isinstance(payload, dict):
                raise ShimError(payload_reason)
            return payload
        except ShimError:
            raise
        except (OSError, ValueError, http.client.HTTPException) as exc:
            raise ShimError(failed_reason) from exc
        finally:
            connection.close()

    def _discover_api_version(self) -> str:
        payload = self._request_json(
            "/version",
            unavailable_reason="docker_version_unavailable",
            malformed_reason="docker_version_invalid",
            payload_reason="docker_version_invalid",
            failed_reason="docker_version_failed",
        )
        api_version_raw = payload.get("ApiVersion")
        minimum_version_raw = payload.get("MinAPIVersion")
        if (
            not isinstance(api_version_raw, str)
            or not _DOCKER_API_VERSION_RE.fullmatch(api_version_raw)
            or not isinstance(minimum_version_raw, str)
            or not _DOCKER_API_VERSION_RE.fullmatch(minimum_version_raw)
        ):
            raise ShimError("docker_version_invalid")

        api_version = tuple(int(part) for part in api_version_raw.split("."))
        minimum_version = tuple(int(part) for part in minimum_version_raw.split("."))
        if minimum_version > api_version:
            raise ShimError("docker_version_invalid")

        selected_version = min(api_version, _MAX_DOCKER_API_VERSION)
        required_minimum = max(minimum_version, _MIN_DOCKER_API_VERSION)
        if selected_version < required_minimum:
            raise ShimError("docker_api_incompatible")
        return f"v{selected_version[0]}.{selected_version[1]}"

    def inspect(self, container_id: str) -> dict[str, Any]:
        if not _CONTAINER_ID_RE.fullmatch(container_id):
            raise ShimError("container_id_invalid")
        if self._api_version is None:
            self._api_version = self._discover_api_version()
        return self._request_json(
            f"/{self._api_version}/containers/{container_id}/json",
            unavailable_reason="docker_inspect_unavailable",
            malformed_reason="docker_inspect_failed",
            payload_reason="docker_payload_invalid",
            failed_reason="docker_inspect_failed",
        )


def _validate_config(config: ShimConfig) -> None:
    if not _PROJECT_RE.fullmatch(config.project_name):
        raise ShimError("compose_project_invalid")
    if not _CONTAINER_ID_RE.fullmatch(config.jobmanager_id):
        raise ShimError("jobmanager_id_invalid")
    if not _CONTAINER_ID_RE.fullmatch(config.taskmanager_id):
        raise ShimError("taskmanager_id_invalid")
    if config.jobmanager_id == config.taskmanager_id:
        raise ShimError("container_ids_not_distinct")
    if not _NAMESPACE_RE.fullmatch(config.namespace):
        raise ShimError("namespace_invalid")
    if not config.label_selector or len(config.label_selector.encode("utf-8")) > 512:
        raise ShimError("label_selector_invalid")


def _pod_item(
    payload: dict[str, Any],
    *,
    expected_id: str,
    expected_project: str,
    expected_service: str,
    require_health: bool,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ShimError("docker_payload_invalid")
    actual_id = payload.get("Id")
    config = payload.get("Config")
    state = payload.get("State")
    restart_count = payload.get("RestartCount")
    if (
        not isinstance(actual_id, str)
        or not isinstance(config, dict)
        or not isinstance(state, dict)
        or isinstance(restart_count, bool)
        or not isinstance(restart_count, int)
    ):
        raise ShimError("docker_payload_invalid")
    if actual_id != expected_id:
        raise ShimError("container_identity_mismatch")

    labels = config.get("Labels")
    if not isinstance(labels, dict):
        raise ShimError("docker_payload_invalid")
    if labels.get("com.docker.compose.project") != expected_project:
        raise ShimError("compose_project_mismatch")
    if labels.get("com.docker.compose.service") != expected_service:
        raise ShimError("compose_service_mismatch")
    if restart_count != 0:
        raise ShimError("container_restarted")
    if state.get("Running") is not True or state.get("Status") != "running":
        raise ShimError("container_not_running")

    health = state.get("Health")
    if require_health:
        if not isinstance(health, dict) or health.get("Status") != "healthy":
            raise ShimError("container_unhealthy")
    elif health is not None and (not isinstance(health, dict) or health.get("Status") != "healthy"):
        raise ShimError("container_unhealthy")

    stable_name = f"{expected_service}-{expected_id[:12]}"
    return {
        "metadata": {
            "name": stable_name,
            "uid": expected_id,
            "labels": {
                "app": "agentflow-ci-soak-flink",
                "component": expected_service,
            },
        },
        "status": {
            "phase": "Running",
            "containerStatuses": [
                {
                    "name": expected_service,
                    "ready": True,
                    "restartCount": 0,
                    "containerID": f"docker://{expected_id}",
                }
            ],
        },
    }


def build_pod_list(inspector: Inspector, config: ShimConfig) -> dict[str, Any]:
    """Build exactly two Ready items or raise a sanitized error."""

    _validate_config(config)
    jobmanager = inspector.inspect(config.jobmanager_id)
    taskmanager = inspector.inspect(config.taskmanager_id)
    items = [
        _pod_item(
            jobmanager,
            expected_id=config.jobmanager_id,
            expected_project=config.project_name,
            expected_service="flink-jobmanager",
            require_health=True,
        ),
        _pod_item(
            taskmanager,
            expected_id=config.taskmanager_id,
            expected_project=config.project_name,
            expected_service="flink-taskmanager",
            require_health=False,
        ),
    ]
    return {
        "apiVersion": "v1",
        "kind": "PodList",
        "metadata": {
            "resourceVersion": f"{config.jobmanager_id[:12]}-{config.taskmanager_id[:12]}"
        },
        "items": items,
    }


def encode_json_response(payload: dict[str, Any]) -> bytes:
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    if len(encoded) > MAX_RESPONSE_BYTES:
        raise ShimError("response_too_large")
    return encoded


def is_authorized(header_value: str | None, expected_token: str) -> bool:
    if not isinstance(header_value, str) or not expected_token:
        return False
    prefix = "Bearer "
    if not header_value.startswith(prefix):
        return False
    presented = header_value[len(prefix) :]
    if not presented or len(presented.encode("utf-8")) > MAX_TOKEN_BYTES:
        return False
    return hmac.compare_digest(presented, expected_token)


def validate_pod_list_target(
    target: str,
    *,
    namespace: str,
    label_selector: str,
) -> bool:
    if len(target.encode("utf-8", errors="replace")) > MAX_REQUEST_TARGET_BYTES:
        raise ShimError("request_target_too_large")
    parsed = urllib.parse.urlsplit(target)
    expected_path = f"/api/v1/namespaces/{urllib.parse.quote(namespace, safe='')}/pods"
    if parsed.scheme or parsed.netloc or parsed.fragment or parsed.path != expected_path:
        raise ShimError("request_target_invalid")
    try:
        query = urllib.parse.parse_qs(
            parsed.query,
            keep_blank_values=True,
            strict_parsing=True,
            max_num_fields=2,
        )
    except ValueError as exc:
        raise ShimError("request_target_invalid") from exc
    if query != {"labelSelector": [label_selector]}:
        raise ShimError("request_target_invalid")
    return True


@dataclass(frozen=True)
class _ServerContext:
    config: ShimConfig
    inspector: Inspector
    token: str


class _ShimServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], context: _ServerContext) -> None:
        self.context = context
        super().__init__(address, _RequestHandler)


class _RequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: _ShimServer

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        try:
            body = encode_json_response(payload)
        except ShimError:
            status = 500
            body = b'{"ok":false,"reason":"response_too_large"}'
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def _headers_are_bounded(self) -> bool:
        total = sum(len(key) + len(value) + 4 for key, value in self.headers.items())
        return total <= MAX_HEADER_BYTES

    def do_GET(self) -> None:  # noqa: N802
        if not self._headers_are_bounded():
            self._send(431, {"ok": False, "reason": "headers_too_large"})
            return
        if not is_authorized(
            self.headers.get("Authorization"),
            self.server.context.token,
        ):
            self._send(401, {"ok": False, "reason": "unauthorized"})
            return
        try:
            pod_list = build_pod_list(
                self.server.context.inspector,
                self.server.context.config,
            )
            if self.path == "/healthz":
                self._send(200, {"ok": True, "containers": len(pod_list["items"])})
                return
            validate_pod_list_target(
                self.path,
                namespace=self.server.context.config.namespace,
                label_selector=self.server.context.config.label_selector,
            )
            self._send(200, pod_list)
        except ShimError as exc:
            reason = str(exc)
            status = 400 if reason.startswith("request_target_") else 503
            self._send(status, {"ok": False, "reason": reason})

    def _method_not_allowed(self) -> None:
        self._send(405, {"ok": False, "reason": "method_not_allowed"})

    do_DELETE = _method_not_allowed  # type: ignore[assignment]  # noqa: N815
    do_HEAD = _method_not_allowed  # type: ignore[assignment]  # noqa: N815
    do_OPTIONS = _method_not_allowed  # type: ignore[assignment]  # noqa: N815
    do_PATCH = _method_not_allowed  # type: ignore[assignment]  # noqa: N815
    do_POST = _method_not_allowed  # type: ignore[assignment]  # noqa: N815
    do_PUT = _method_not_allowed  # type: ignore[assignment]  # noqa: N815

    def log_message(self, _format: str, *_args: Any) -> None:
        return


def _read_token(path: Path) -> str:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ShimError("token_unreadable") from exc
    if not raw or len(raw) > MAX_TOKEN_BYTES:
        raise ShimError("token_invalid")
    try:
        token = raw.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise ShimError("token_invalid") from exc
    if not token or "\n" in token or "\r" in token:
        raise ShimError("token_invalid")
    return token


def serve(
    *,
    host: str,
    port: int,
    cert_path: Path,
    key_path: Path,
    context: _ServerContext,
) -> None:
    server = _ShimServer((host, port), context)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    try:
        tls.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    except (OSError, ssl.SSLError) as exc:
        server.server_close()
        raise ShimError("tls_material_invalid") from exc
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    print(f"shim_ready port={port} containers=2", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")  # noqa: S104
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--socket", type=Path, default=Path("/var/run/docker.sock"))
    parser.add_argument("--cert", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--jobmanager-id", required=True)
    parser.add_argument("--taskmanager-id", required=True)
    parser.add_argument("--namespace", default="agentflow")
    parser.add_argument("--label-selector", default="app=agentflow-ci-soak-flink")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if not 1 <= args.port <= 65535:
            raise ShimError("port_invalid")
        if not args.socket.is_absolute() or not args.socket.exists():
            raise ShimError("docker_socket_unavailable")
        if not args.cert.is_file() or not args.key.is_file():
            raise ShimError("tls_material_missing")
        config = ShimConfig(
            project_name=args.project_name,
            jobmanager_id=args.jobmanager_id,
            taskmanager_id=args.taskmanager_id,
            namespace=args.namespace,
            label_selector=args.label_selector,
        )
        _validate_config(config)
        context = _ServerContext(
            config=config,
            inspector=DockerSocketInspector(args.socket),
            token=_read_token(args.token_file),
        )
        serve(
            host=args.host,
            port=args.port,
            cert_path=args.cert,
            key_path=args.key,
            context=context,
        )
        return 0
    except ShimError as exc:
        print(f"result=FAIL reason={exc}", flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
