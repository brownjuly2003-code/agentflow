#!/usr/bin/env python3
"""Fail-closed local Docker Compose controller for the tracked golden-soak pack."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

FULL_SOAK_COUNT = 1_440_000
REQUIRED_RATE_EPS = 100.0
MAX_COMMAND_OUTPUT_BYTES = 1024 * 1024
MAX_JSON_BYTES = 1024 * 1024
MAX_STATE_BYTES = 1024 * 1024

EXPECTED_PACK_NAMES = {
    "baseline-job.yaml",
    "baseline.py",
    "observer.py",
    "producer.py",
    "soak-observer-job.yaml",
    "soak-producer-job.yaml",
    "soak-verify-job.yaml",
    "verify.py",
}
COMPOSE_FILES = (
    "docker-compose.yml",
    "docker-compose.flink.yml",
    "docker-compose.soak.yml",
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CONTAINER_ID_RE = re.compile(r"^[0-9a-f]{64}$")
_EXIT_CODE_RE = re.compile(r"^(?:0|[1-9][0-9]{0,2})$")
_FLINK_JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
_EVENT_PREFIX_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-$")
_ORDER_PREFIX_RE = re.compile(r"^ORD-[0-9]{8}-[0-9]{4,}$")
_REASON_RE = re.compile(r"[^a-z0-9_]+")


class PackIntegrityError(RuntimeError):
    """The immutable source pack differs from its manifest."""


class RuntimeFailure(RuntimeError):  # noqa: N818 - domain term used in result tokens
    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = _sanitize_reason(reason)
        self.detail = _bounded_text(detail, 512).replace("\r", " ").replace("\n", " ")
        super().__init__(self.reason)


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str = ""


@dataclass(frozen=True)
class RuntimeOutcome:
    passed: bool
    reason: str
    terminal: str


@dataclass(frozen=True)
class RuntimeConfig:
    project_root: Path
    source_root: Path
    output_dir: Path
    project_name: str
    count: int = FULL_SOAK_COUNT
    rate_eps: float = REQUIRED_RATE_EPS
    flink_rest_base: str = "http://127.0.0.1:8081"
    readiness_timeout_s: float = 300.0


@dataclass(frozen=True)
class PackIdentity:
    manifest_source_identity: str
    manifest_sha256: str
    run_label: str
    source: str
    event_prefix: str
    order_prefix: str
    file_hashes: dict[str, str]


@dataclass(frozen=True)
class FlinkGate:
    job_id: str
    tasks_total: int
    checkpoints_completed: int
    checkpoints_failed: int


class Runner(Protocol):
    def which(self, executable: str) -> str | None: ...

    def run(
        self,
        step: str,
        argv: list[str],
        *,
        cwd: Path,
        env: dict[str, str] | None = None,
        timeout_s: float | None = None,
    ) -> CommandResult: ...


def _sanitize_reason(reason: str) -> str:
    sanitized = _REASON_RE.sub("_", reason.lower()).strip("_")
    return sanitized[:80] or "runtime_failure"


def _bounded_text(value: str, limit: int = MAX_COMMAND_OUTPUT_BYTES) -> str:
    encoded = value.encode("utf-8", errors="replace")
    if len(encoded) <= limit:
        return value
    marker = b"\n... output truncated by ci-soak runtime ...\n"
    head_size = min(32 * 1024, max(limit // 4, 0))
    tail_size = max(limit - head_size - len(marker), 0)
    bounded = encoded[:head_size] + marker + encoded[-tail_size:]
    return bounded.decode("utf-8", errors="replace")


def _command_log(result: CommandResult) -> str:
    stdout = _bounded_text(result.stdout)
    stderr = _bounded_text(result.stderr)
    if not stderr:
        return stdout
    separator = "" if not stdout or stdout.endswith("\n") else "\n"
    return _bounded_text(f"{stdout}{separator}--- stderr ---\n{stderr}")


def _extract_single_full_line(
    output: str,
    pattern: re.Pattern[str],
    *,
    reason: str,
    detail: str = "",
) -> str:
    matches = [line.strip() for line in output.splitlines() if pattern.fullmatch(line.strip())]
    if len(matches) != 1:
        raise RuntimeFailure(reason, detail)
    return matches[0]


def _extract_single_container_id(
    output: str,
    *,
    reason: str,
    detail: str = "",
) -> str:
    return _extract_single_full_line(
        output,
        _CONTAINER_ID_RE,
        reason=reason,
        detail=detail,
    )


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    if len(encoded.encode("utf-8")) > MAX_STATE_BYTES:
        raise RuntimeFailure("runtime_state_too_large")
    _atomic_write_text(path, encoded)


def _load_bounded_json(path: Path, label: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise RuntimeFailure(f"{label}_missing") from exc
    if not raw or len(raw) > MAX_JSON_BYTES:
        raise RuntimeFailure(f"{label}_size_invalid")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeFailure(f"{label}_invalid") from exc
    if not isinstance(payload, dict):
        raise RuntimeFailure(f"{label}_invalid")
    return payload


class SubprocessRunner:
    def which(self, executable: str) -> str | None:
        return shutil.which(executable)

    def run(
        self,
        step: str,
        argv: list[str],
        *,
        cwd: Path,
        env: dict[str, str] | None = None,
        timeout_s: float | None = None,
    ) -> CommandResult:
        process_env = os.environ.copy()
        if env:
            process_env.update(env)
        try:
            result = subprocess.run(
                argv,
                cwd=cwd,
                env=process_env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
                check=False,
            )
            return CommandResult(
                result.returncode,
                _bounded_text(result.stdout or ""),
                _bounded_text(result.stderr or ""),
            )
        except subprocess.TimeoutExpired as exc:
            captured_stdout = exc.stdout or ""
            captured_stderr = exc.stderr or ""
            if isinstance(captured_stdout, bytes):
                captured_stdout = captured_stdout.decode("utf-8", errors="replace")
            if isinstance(captured_stderr, bytes):
                captured_stderr = captured_stderr.decode("utf-8", errors="replace")
            return CommandResult(
                124,
                _bounded_text(captured_stdout),
                _bounded_text(f"{captured_stderr}\ntimeout step={step}\n"),
            )
        except OSError as exc:
            return CommandResult(
                127,
                "",
                f"runner_error step={step} type={type(exc).__name__}\n",
            )


def _literal_assignments(path: Path, names: set[str]) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        raise PackIntegrityError("baseline_parse_failed") from exc
    found: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in names:
            continue
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, TypeError) as exc:
            raise PackIntegrityError(f"baseline_literal_invalid:{target.id}") from exc
        if not isinstance(value, str) or not value:
            raise PackIntegrityError(f"baseline_literal_invalid:{target.id}")
        if target.id in found:
            raise PackIntegrityError(f"baseline_literal_duplicate:{target.id}")
        found[target.id] = value
    if set(found) != names:
        raise PackIntegrityError("baseline_literals_missing")
    return found


def validate_source_pack(source_root: Path) -> PackIdentity:
    source_root = source_root.resolve()
    manifest_path = source_root / "MANIFEST.json"
    pack_root = source_root / "pack"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise PackIntegrityError("manifest_missing")
    if pack_root.is_symlink() or not pack_root.is_dir():
        raise PackIntegrityError("pack_missing")
    try:
        raw_manifest = manifest_path.read_bytes()
    except OSError as exc:
        raise PackIntegrityError("manifest_unreadable") from exc
    if not raw_manifest or len(raw_manifest) > 64 * 1024:
        raise PackIntegrityError("manifest_size_invalid")
    try:
        manifest = json.loads(raw_manifest.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackIntegrityError("manifest_invalid") from exc
    if not isinstance(manifest, dict):
        raise PackIntegrityError("manifest_invalid")
    if manifest.get("contract_status") != "source-reference-only":
        raise PackIntegrityError("manifest_contract_status_invalid")
    source_identity = manifest.get("source_identity")
    entries = manifest.get("files")
    if not isinstance(source_identity, str) or not source_identity:
        raise PackIntegrityError("manifest_source_identity_invalid")
    if not isinstance(entries, dict):
        raise PackIntegrityError("manifest_files_invalid")

    try:
        children = list(pack_root.iterdir())
    except OSError as exc:
        raise PackIntegrityError("pack_unreadable") from exc
    if any(child.is_symlink() or not child.is_file() for child in children):
        raise PackIntegrityError("pack_contains_non_regular_file")
    actual_names = {child.name for child in children}
    if actual_names != EXPECTED_PACK_NAMES:
        raise PackIntegrityError("pack_file_set_mismatch")
    expected_keys = {f"pack/{name}" for name in EXPECTED_PACK_NAMES}
    if set(entries) != expected_keys:
        raise PackIntegrityError("manifest_file_set_mismatch")

    file_hashes: dict[str, str] = {}
    for key in sorted(expected_keys):
        pure_path = PurePosixPath(key)
        if pure_path.parts != ("pack", pure_path.name) or pure_path.name not in EXPECTED_PACK_NAMES:
            raise PackIntegrityError("manifest_path_unsafe")
        entry = entries[key]
        if not isinstance(entry, dict) or set(entry) != {"bytes", "sha256"}:
            raise PackIntegrityError("manifest_entry_invalid")
        expected_bytes = entry.get("bytes")
        expected_sha = entry.get("sha256")
        if (
            isinstance(expected_bytes, bool)
            or not isinstance(expected_bytes, int)
            or expected_bytes < 0
            or not isinstance(expected_sha, str)
            or not _SHA256_RE.fullmatch(expected_sha)
        ):
            raise PackIntegrityError("manifest_entry_invalid")
        path = pack_root / pure_path.name
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise PackIntegrityError(f"pack_file_unreadable:{pure_path.name}") from exc
        actual_sha = hashlib.sha256(data).hexdigest()
        if len(data) != expected_bytes or actual_sha != expected_sha:
            raise PackIntegrityError(f"pack_hash_mismatch:{pure_path.name}")
        file_hashes[key] = actual_sha

    constants = _literal_assignments(
        pack_root / "baseline.py",
        {"SOAK_SOURCE", "SOAK_EVENT_PREFIX", "SOAK_ORDER_PREFIX"},
    )
    source = constants["SOAK_SOURCE"]
    event_prefix = constants["SOAK_EVENT_PREFIX"]
    order_prefix = constants["SOAK_ORDER_PREFIX"]
    if not source.endswith(source_identity):
        raise PackIntegrityError("baseline_source_identity_mismatch")
    if not _EVENT_PREFIX_RE.fullmatch(event_prefix):
        raise PackIntegrityError("baseline_event_prefix_invalid")
    if not _ORDER_PREFIX_RE.fullmatch(order_prefix):
        raise PackIntegrityError("baseline_order_prefix_invalid")
    return PackIdentity(
        manifest_source_identity=source_identity,
        manifest_sha256=hashlib.sha256(raw_manifest).hexdigest(),
        run_label=source,
        source=source,
        event_prefix=event_prefix,
        order_prefix=order_prefix,
        file_hashes=file_hashes,
    )


def _default_http_json(url: str) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeFailure("flink_url_invalid")
    request = urllib.request.Request(  # noqa: S310 - validated loopback HTTP URL
        url,
        headers={"Accept": "application/json"},
    )
    with urllib.request.urlopen(  # noqa: S310 - validated loopback HTTP URL
        request,
        timeout=10,
    ) as response:
        raw = response.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise RuntimeFailure("flink_response_too_large")
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeFailure("flink_response_invalid")
    return payload


class RuntimeHarness:
    def __init__(
        self,
        config: RuntimeConfig,
        *,
        runner: Runner,
        http_json: Callable[[str], dict[str, Any]] = _default_http_json,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.runner = runner
        self.http_json = http_json
        self.sleep = sleep
        self.monotonic = monotonic
        self.identity: PackIdentity | None = None
        self.docker_executable = "docker"
        self.openssl_executable = "openssl"
        self.runtime_dir: Path | None = None
        self.evidence_dir = config.output_dir / "evidence"
        self.logs_dir = config.output_dir / "logs"
        self.observer_id: str | None = None
        self.shim_id: str | None = None
        self.compose_touched = False
        self.output_owned = False
        self.state: dict[str, Any] = {
            "schema_version": 1,
            "status": "INITIALIZING",
            "steps": [],
        }

    def execute(self) -> RuntimeOutcome:
        primary_reason = ""
        primary_detail = ""
        candidate_pass = False
        try:
            self.identity = validate_source_pack(self.config.source_root)
            self._validate_config()
            self._check_tools()
            self._prepare_output()
            self._initialize_state()
            self._prepare_tls()
            self._execute_lifecycle()
            candidate_pass = True
        except PackIntegrityError as exc:
            primary_reason = "pack_integrity"
            primary_detail = str(exc)
        except RuntimeFailure as exc:
            primary_reason = exc.reason
            primary_detail = exc.detail
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            primary_reason = "runtime_exception"
            primary_detail = type(exc).__name__

        cleanup_errors = self._cleanup()
        if cleanup_errors:
            self.state["cleanup_errors"] = cleanup_errors
            if candidate_pass:
                primary_reason = "cleanup_failed"
                primary_detail = cleanup_errors[0]
            candidate_pass = False
        self._remove_runtime_dir(cleanup_errors)
        if cleanup_errors and not primary_reason:
            primary_reason = "cleanup_failed"
            primary_detail = cleanup_errors[0]
        if primary_reason:
            candidate_pass = False

        passed = candidate_pass
        if not self.output_owned:
            self._prepare_failure_output()
        terminal = self._terminal_line(passed, primary_reason)
        if self.output_owned:
            self.state["status"] = "PASS" if passed else "FAIL"
            self.state["reason"] = "" if passed else (primary_reason or "runtime_failure")
            if primary_detail:
                self.state["detail"] = _bounded_text(primary_detail, 512)
            try:
                _atomic_write_json(self.config.output_dir / "runtime-state.json", self.state)
                _atomic_write_text(self.config.output_dir / "result-final.txt", terminal + "\n")
            except (OSError, RuntimeFailure):
                passed = False
                terminal = "RESULT=FAIL reason=evidence_write_failed"
        return RuntimeOutcome(
            passed=passed,
            reason="" if passed else (primary_reason or "runtime_failure"),
            terminal=terminal,
        )

    def _validate_config(self) -> None:
        if not self.config.project_root.is_dir():
            raise RuntimeFailure("project_root_invalid")
        if not _PROJECT_RE.fullmatch(self.config.project_name):
            raise RuntimeFailure("compose_project_invalid")
        if (
            isinstance(self.config.count, bool)
            or not isinstance(self.config.count, int)
            or not 1 <= self.config.count <= FULL_SOAK_COUNT
        ):
            raise RuntimeFailure("count_invalid")
        if self.config.rate_eps != REQUIRED_RATE_EPS:
            raise RuntimeFailure("rate_contract_invalid")
        for name in COMPOSE_FILES:
            path = self.config.project_root / name
            if path.is_symlink() or not path.is_file():
                raise RuntimeFailure("compose_file_missing", name)

    def _prepare_output(self) -> None:
        output = self.config.output_dir
        if output.exists():
            if not output.is_dir() or any(output.iterdir()):
                raise RuntimeFailure("output_not_empty")
        else:
            output.mkdir(parents=True)
        self.output_owned = True
        self.evidence_dir.mkdir()
        self.logs_dir.mkdir()

    def _prepare_failure_output(self) -> None:
        output = self.config.output_dir
        try:
            if output.exists():
                if not output.is_dir() or any(output.iterdir()):
                    return
            else:
                output.mkdir(parents=True)
            self.output_owned = True
            self.evidence_dir.mkdir(exist_ok=True)
            self.logs_dir.mkdir(exist_ok=True)
        except OSError:
            self.output_owned = False

    def _initialize_state(self) -> None:
        if self.identity is None:
            raise RuntimeFailure("pack_identity_missing")
        claim_boundary = (
            "capacity-independent-compose-soak"
            if self.config.count == FULL_SOAK_COUNT
            else "capacity-independent-compose-rehearsal"
        )
        self.state.update(
            {
                "claim_boundary": claim_boundary,
                "does_not_close": "mac-kind-operator-ha-helm-rollback-gate",
                "project_name": self.config.project_name,
                "count": self.config.count,
                "rate_eps": self.config.rate_eps,
                "source_identity": self.identity.manifest_source_identity,
                "source": self.identity.source,
                "event_prefix": self.identity.event_prefix,
                "order_prefix": self.identity.order_prefix,
                "manifest_sha256": self.identity.manifest_sha256,
                "pack_sha256": self.identity.file_hashes,
            }
        )

    def _check_tools(self) -> None:
        docker = self.runner.which("docker")
        openssl = self.runner.which("openssl")
        if not docker:
            raise RuntimeFailure("docker_unavailable")
        if not openssl:
            raise RuntimeFailure("openssl_unavailable")
        self.docker_executable = docker
        self.openssl_executable = openssl

    def _prepare_tls(self) -> None:
        shim_name = self._shim_name()
        self.runtime_dir = Path(tempfile.mkdtemp(prefix=f"{self.config.project_name}-shim-"))
        token_path = self.runtime_dir / "token"
        cert_path = self.runtime_dir / "ca.crt"
        key_path = self.runtime_dir / "server.key"
        token_path.write_text(secrets.token_urlsafe(32) + "\n", encoding="utf-8", newline="\n")
        token_path.chmod(0o600)
        argv = [
            self.openssl_executable,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-sha256",
            "-nodes",
            "-days",
            "1",
            "-keyout",
            str(key_path),
            "-out",
            str(cert_path),
            "-subj",
            f"/CN={shim_name}",
            "-addext",
            f"subjectAltName=DNS:{shim_name}",
        ]
        self._run_required("generate-tls", argv, timeout_s=30)
        if not cert_path.is_file() or not key_path.is_file():
            raise RuntimeFailure("tls_material_missing")
        if cert_path.stat().st_size <= 0 or key_path.stat().st_size <= 0:
            raise RuntimeFailure("tls_material_invalid")
        key_path.chmod(0o600)

    def _compose_prefix(self) -> list[str]:
        argv = [self.docker_executable, "compose", "--project-name", self.config.project_name]
        for name in COMPOSE_FILES:
            argv.extend(["-f", str((self.config.project_root / name).resolve())])
        return argv

    def _compose(self, *args: str) -> list[str]:
        return [*self._compose_prefix(), *args]

    def _execute_lifecycle(self) -> None:
        self._preflight_project_empty()
        self.compose_touched = True
        self._run_required("build-flink", self._compose("build", "flink-job-runner"), 1200)
        self._run_required("build-api", self._compose("build", "agentflow-api"), 1200)
        self._run_required(
            "up-core",
            self._compose(
                "up",
                "-d",
                "--wait",
                "--wait-timeout",
                "240",
                "kafka",
                "minio",
                "clickhouse",
                "flink-jobmanager",
            ),
            300,
        )
        self._run_required(
            "up-init",
            self._compose(
                "up",
                "-d",
                "kafka-init",
                "minio-init",
                "soak-topics-init",
                "iceberg-rest",
                "flink-taskmanager",
            ),
            300,
        )
        self._wait_one_shot("kafka-init")
        self._wait_one_shot("minio-init")
        self._wait_one_shot("soak-topics-init")
        self._run_required(
            "up-data-init",
            self._compose("up", "-d", "iceberg-init", "serving-init"),
            300,
        )
        self._wait_one_shot("iceberg-init")
        self._wait_one_shot("serving-init")
        self._run_required(
            "up-app",
            self._compose(
                "up",
                "-d",
                "--wait",
                "--wait-timeout",
                "240",
                "agentflow-api",
                "lake-materializer",
                "serving-bridge",
            ),
            300,
        )
        self._run_required(
            "up-flink-runner",
            self._compose("up", "-d", "flink-job-runner"),
            180,
        )

        jobmanager_id = self._single_container_id("flink-jobmanager", "ps-jm")
        taskmanager_id = self._single_container_id("flink-taskmanager", "ps-tm")
        self._inspect_container(
            jobmanager_id,
            service="flink-jobmanager",
            step="inspect-jm-initial",
            require_health=True,
        )
        self._inspect_container(
            taskmanager_id,
            service="flink-taskmanager",
            step="inspect-tm-initial",
            require_health=False,
        )
        gate = self._wait_flink_gate()
        self.state["container_ids"] = {
            "jobmanager": jobmanager_id,
            "taskmanager": taskmanager_id,
        }
        self.state["flink"] = {
            "job_id": gate.job_id,
            "tasks_total": gate.tasks_total,
            "checkpoint_baseline_completed": gate.checkpoints_completed,
            "checkpoint_baseline_failed": gate.checkpoints_failed,
        }

        self.shim_id = self._start_shim(jobmanager_id, taskmanager_id)
        self._probe_shim()
        self._run_baseline()
        self.observer_id = self._start_observer(gate)
        self._wait_observer_ready(self.observer_id)
        self._run_producer()
        self._assert_no_abort()
        self._validate_producer_final()
        self._run_verifier(gate)
        self._assert_no_abort()
        self._validate_verify_final(gate)

        final_jm = self._single_container_id("flink-jobmanager", "ps-jm-final")
        final_tm = self._single_container_id("flink-taskmanager", "ps-tm-final")
        if final_jm != jobmanager_id or final_tm != taskmanager_id:
            raise RuntimeFailure("container_identity_changed")
        self._inspect_container(
            jobmanager_id,
            service="flink-jobmanager",
            step="inspect-jm-final",
            require_health=True,
        )
        self._inspect_container(
            taskmanager_id,
            service="flink-taskmanager",
            step="inspect-tm-final",
            require_health=False,
        )
        final_gate = self._wait_flink_gate(
            expected_job_id=gate.job_id,
            expected_failed=gate.checkpoints_failed,
        )
        self.state["flink"]["final_checkpoints_completed"] = final_gate.checkpoints_completed
        self.state["flink"]["final_checkpoints_failed"] = final_gate.checkpoints_failed

    def _preflight_project_empty(self) -> None:
        checks = [
            (
                "preflight-containers",
                self._compose("ps", "--all", "--quiet"),
                "containers",
            ),
            (
                "preflight-volumes",
                [
                    self.docker_executable,
                    "volume",
                    "ls",
                    "--quiet",
                    "--filter",
                    f"label=com.docker.compose.project={self.config.project_name}",
                ],
                "volumes",
            ),
            (
                "preflight-networks",
                [
                    self.docker_executable,
                    "network",
                    "ls",
                    "--quiet",
                    "--filter",
                    f"label=com.docker.compose.project={self.config.project_name}",
                ],
                "networks",
            ),
        ]
        for step, argv, resource_kind in checks:
            output = self._run_required(step, argv, 30)
            if output.strip():
                raise RuntimeFailure("compose_project_not_clean", resource_kind)

    def _run_required(
        self,
        step: str,
        argv: list[str],
        timeout_s: float | None = None,
    ) -> str:
        result = self.runner.run(
            step,
            argv,
            cwd=self.config.project_root,
            timeout_s=timeout_s,
        )
        self._record_step(step, result)
        if result.returncode != 0:
            raise RuntimeFailure(f"{step}_failed", f"returncode={result.returncode}")
        return _bounded_text(result.stdout)

    def _record_step(self, step: str, result: CommandResult) -> None:
        output = _command_log(result)
        if self.output_owned:
            _atomic_write_text(self.logs_dir / f"{step}.log", output)
        steps = self.state.setdefault("steps", [])
        if isinstance(steps, list):
            steps.append(
                {
                    "name": step,
                    "returncode": result.returncode,
                    "output_bytes": len(output.encode("utf-8", errors="replace")),
                }
            )

    def _single_container_id(
        self,
        service: str,
        step: str,
        *,
        include_stopped: bool = False,
    ) -> str:
        compose_args = (
            ("ps", "--all", "--quiet", "--no-trunc", service)
            if include_stopped
            else ("ps", "-q", service)
        )
        output = self._run_required(step, self._compose(*compose_args), 30)
        return _extract_single_container_id(
            output,
            reason="container_identity_invalid",
            detail=service,
        )

    def _wait_one_shot(self, service: str) -> None:
        container_id = self._single_container_id(
            service,
            f"ps-{service}",
            include_stopped=True,
        )
        output = self._run_required(
            f"wait-{service}",
            [self.docker_executable, "wait", container_id],
            180,
        )
        value = _extract_single_full_line(
            output,
            _EXIT_CODE_RE,
            reason="one_shot_wait_output_invalid",
            detail=service,
        )
        exit_code = int(value)
        if exit_code > 255:
            raise RuntimeFailure("one_shot_wait_output_invalid", service)
        self._inspect_one_shot(container_id, service=service, expected_exit_code=exit_code)
        if exit_code != 0:
            raise RuntimeFailure("one_shot_exit_nonzero", service)

    def _inspect_one_shot(
        self,
        container_id: str,
        *,
        service: str,
        expected_exit_code: int,
    ) -> None:
        output = self._run_required(
            f"inspect-{service}",
            [self.docker_executable, "inspect", container_id],
            30,
        )
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError as exc:
            raise RuntimeFailure("container_inspect_invalid", service) from exc
        if isinstance(parsed, list) and len(parsed) == 1:
            payload = parsed[0]
        else:
            payload = parsed
        if not isinstance(payload, dict):
            raise RuntimeFailure("container_inspect_invalid", service)
        labels = (payload.get("Config") or {}).get("Labels")
        state = payload.get("State")
        restart_count = payload.get("RestartCount")
        if (
            payload.get("Id") != container_id
            or not isinstance(labels, dict)
            or not isinstance(state, dict)
            or isinstance(restart_count, bool)
            or not isinstance(restart_count, int)
        ):
            raise RuntimeFailure("container_inspect_invalid", service)
        if labels.get("com.docker.compose.project") != self.config.project_name:
            raise RuntimeFailure("container_project_mismatch", service)
        if labels.get("com.docker.compose.service") != service:
            raise RuntimeFailure("container_service_mismatch", service)
        if restart_count != 0:
            raise RuntimeFailure("container_restarted", service)
        if state.get("Running") is not False or state.get("Status") != "exited":
            raise RuntimeFailure("one_shot_not_exited", service)
        state_exit_code = state.get("ExitCode")
        if (
            isinstance(state_exit_code, bool)
            or not isinstance(state_exit_code, int)
            or state_exit_code != expected_exit_code
        ):
            raise RuntimeFailure("one_shot_exit_code_mismatch", service)

    def _inspect_container(
        self,
        container_id: str,
        *,
        service: str,
        step: str,
        require_health: bool,
    ) -> None:
        output = self._run_required(
            step,
            [self.docker_executable, "inspect", container_id],
            30,
        )
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError as exc:
            raise RuntimeFailure("container_inspect_invalid", service) from exc
        if isinstance(parsed, list) and len(parsed) == 1:
            payload = parsed[0]
        else:
            payload = parsed
        if not isinstance(payload, dict):
            raise RuntimeFailure("container_inspect_invalid", service)
        labels = (payload.get("Config") or {}).get("Labels")
        state = payload.get("State")
        restart_count = payload.get("RestartCount")
        if (
            payload.get("Id") != container_id
            or not isinstance(labels, dict)
            or not isinstance(state, dict)
            or isinstance(restart_count, bool)
            or not isinstance(restart_count, int)
        ):
            raise RuntimeFailure("container_inspect_invalid", service)
        if labels.get("com.docker.compose.project") != self.config.project_name:
            raise RuntimeFailure("container_project_mismatch", service)
        if labels.get("com.docker.compose.service") != service:
            raise RuntimeFailure("container_service_mismatch", service)
        if restart_count != 0:
            raise RuntimeFailure("container_restarted", service)
        if state.get("Running") is not True or state.get("Status") != "running":
            raise RuntimeFailure("container_not_running", service)
        health = state.get("Health")
        if require_health and (not isinstance(health, dict) or health.get("Status") != "healthy"):
            raise RuntimeFailure("container_unhealthy", service)
        if health is not None and (
            not isinstance(health, dict) or health.get("Status") != "healthy"
        ):
            raise RuntimeFailure("container_unhealthy", service)

    def _wait_flink_gate(
        self,
        *,
        expected_job_id: str | None = None,
        expected_failed: int | None = None,
    ) -> FlinkGate:
        base = self.config.flink_rest_base.rstrip("/")
        deadline = self.monotonic() + self.config.readiness_timeout_s
        last_reason = "flink_not_ready"
        while self.monotonic() <= deadline:
            try:
                overview = self.http_json(f"{base}/jobs/overview")
                jobs = overview.get("jobs")
                if not isinstance(jobs, list) or not jobs:
                    last_reason = "flink_no_jobs"
                elif len(jobs) != 1 or not isinstance(jobs[0], dict):
                    raise RuntimeFailure("flink_job_count_invalid")
                else:
                    job = jobs[0]
                    job_id = str(job.get("jid") or job.get("id") or "")
                    if not _FLINK_JOB_ID_RE.fullmatch(job_id):
                        raise RuntimeFailure("flink_job_id_invalid")
                    if expected_job_id is not None and job_id != expected_job_id:
                        raise RuntimeFailure("flink_job_identity_changed")
                    tasks = job.get("tasks")
                    if not isinstance(tasks, dict):
                        raise RuntimeFailure("flink_tasks_invalid")
                    total = int(tasks.get("total", 0) or 0)
                    running = int(tasks.get("running", 0) or 0)
                    checkpoints = self.http_json(f"{base}/jobs/{job_id}/checkpoints")
                    counts = checkpoints.get("counts")
                    if not isinstance(counts, dict) or "failed" not in counts:
                        raise RuntimeFailure("flink_checkpoints_invalid")
                    completed = int(counts.get("completed", 0) or 0)
                    failed = int(counts["failed"])
                    if failed < 0:
                        raise RuntimeFailure("flink_checkpoints_invalid")
                    if expected_failed is not None and failed != expected_failed:
                        raise RuntimeFailure("flink_failed_checkpoints_changed")
                    if (
                        job.get("state") == "RUNNING"
                        and total > 0
                        and running == total
                        and completed > 0
                    ):
                        return FlinkGate(job_id, total, completed, failed)
                    last_reason = "flink_not_running"
            except RuntimeFailure:
                raise
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                last_reason = "flink_api_unavailable"
            self.sleep(5.0)
        raise RuntimeFailure(last_reason)

    def _shim_name(self) -> str:
        return f"{self.config.project_name}-pods-shim"

    def _observer_name(self) -> str:
        return f"{self.config.project_name}-observer"

    def _host_mount(self, source: Path, target: str, *, read_only: bool = False) -> str:
        suffix = ":ro" if read_only else ""
        return f"{source.resolve()}:{target}{suffix}"

    def _env_flags(self, values: dict[str, str]) -> list[str]:
        flags: list[str] = []
        for key in sorted(values):
            flags.extend(["-e", f"{key}={values[key]}"])
        return flags

    def _pack_command(
        self,
        script_name: str,
        values: dict[str, str],
        *,
        detached: bool = False,
        name: str | None = None,
    ) -> list[str]:
        if self.runtime_dir is None:
            raise RuntimeFailure("runtime_directory_missing")
        run_flags = ["run"]
        run_flags.append("--no-TTY")
        if detached:
            run_flags.append("--detach")
        else:
            run_flags.append("--rm")
        if name:
            run_flags.extend(["--name", name])
        run_flags.extend(
            [
                "--no-deps",
                "--user",
                "0:0",
                "-v",
                self._host_mount(self.config.source_root, "/golden-pack", read_only=True),
                "-v",
                self._host_mount(self.evidence_dir, "/evidence"),
                "-v",
                self._host_mount(self.runtime_dir, "/shim", read_only=True),
                *self._env_flags(values),
                "agentflow-api",
                "python",
                f"/golden-pack/pack/{script_name}",
            ]
        )
        return [*self._compose_prefix(), *run_flags]

    def _common_data_env(self) -> dict[str, str]:
        return {
            "KAFKA_BOOTSTRAP_SERVERS": "kafka:9092",
            "CLICKHOUSE_HOST": "clickhouse",
            "CLICKHOUSE_PORT": "8123",
            "CLICKHOUSE_DATABASE": "agentflow",
            "DEMO_API_KEY": "demo-key",
            "TASK_API_BASE": "http://agentflow-api:8000",
            "AGENTFLOW_ICEBERG_CONFIG": "/app/config/iceberg.yaml",
            "AGENTFLOW_ICEBERG_URI": "http://iceberg-rest:8181",
            "AGENTFLOW_ICEBERG_WAREHOUSE": "s3://agentflow-lake/warehouse",
            "AGENTFLOW_S3_ENDPOINT": "http://minio:9000",
            "AGENTFLOW_S3_REGION": "us-east-1",
        }

    def _shim_env(self) -> dict[str, str]:
        return {
            "KUBERNETES_API": f"https://{self._shim_name()}:8443",
            "POD_NAMESPACE": "agentflow",
            "FLINK_POD_SELECTOR": "app=agentflow-ci-soak-flink",
            "SA_TOKEN_PATH": "/shim/token",
            "SA_CA_PATH": "/shim/ca.crt",
        }

    def _start_shim(self, jobmanager_id: str, taskmanager_id: str) -> str:
        if self.runtime_dir is None:
            raise RuntimeFailure("runtime_directory_missing")
        argv = [
            *self._compose_prefix(),
            "run",
            "--no-TTY",
            "--detach",
            "--name",
            self._shim_name(),
            "--no-deps",
            "--user",
            "0:0",
            "-v",
            self._host_mount(self.config.source_root, "/golden-soak", read_only=True),
            "-v",
            "/var/run/docker.sock:/var/run/docker.sock:ro",
            "-v",
            self._host_mount(self.runtime_dir, "/shim", read_only=True),
            "agentflow-api",
            "python",
            "/golden-soak/pods_shim.py",
            "--cert",
            "/shim/ca.crt",
            "--key",
            "/shim/server.key",
            "--token-file",
            "/shim/token",
            "--project-name",
            self.config.project_name,
            "--jobmanager-id",
            jobmanager_id,
            "--taskmanager-id",
            taskmanager_id,
            "--namespace",
            "agentflow",
            "--label-selector",
            "app=agentflow-ci-soak-flink",
        ]
        output = self._run_required("shim-start", argv, 60)
        return _extract_single_container_id(
            output,
            reason="shim_container_id_invalid",
        )

    def _probe_shim(self) -> None:
        if self.runtime_dir is None:
            raise RuntimeFailure("runtime_directory_missing")
        probe = (
            "import json,pathlib,ssl,urllib.request;"
            "token=pathlib.Path('/shim/token').read_text().strip();"
            "ctx=ssl.create_default_context(cafile='/shim/ca.crt');"
            f"req=urllib.request.Request('https://{self._shim_name()}:8443/healthz',"
            "headers={'Authorization':'Bearer '+token});"
            "print(urllib.request.urlopen(req,timeout=10,context=ctx).read().decode())"
        )
        argv = [
            *self._compose_prefix(),
            "run",
            "--no-TTY",
            "--rm",
            "--no-deps",
            "-v",
            self._host_mount(self.runtime_dir, "/shim", read_only=True),
            "agentflow-api",
            "python",
            "-c",
            probe,
        ]
        deadline = self.monotonic() + 60
        for _attempt in range(30):
            result = self.runner.run(
                "shim-probe",
                argv,
                cwd=self.config.project_root,
                timeout_s=30,
            )
            self._record_step("shim-probe", result)
            if result.returncode == 0:
                for line in reversed(result.stdout.splitlines()):
                    if not line.strip():
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if payload == {"ok": True, "containers": 2}:
                        return
                    break
            if self.monotonic() >= deadline:
                break
            self.sleep(2)
        raise RuntimeFailure("shim_probe_failed")

    def _run_baseline(self) -> None:
        values = {
            **self._common_data_env(),
            "EVIDENCE_DIR": "/evidence",
            "KAFKA_BASELINE_GROUP": f"{self.config.project_name}-baseline",
        }
        output = self._run_required(
            "baseline",
            self._pack_command("baseline.py", values),
            300,
        )
        if "result=PASS baseline_all_zero=1" not in output:
            raise RuntimeFailure("baseline_result_invalid")

    def _start_observer(self, gate: FlinkGate) -> str:
        if self.identity is None:
            raise RuntimeFailure("pack_identity_missing")
        deadline = max(1800, int(self.config.count / self.config.rate_eps) + 3600)
        values = {
            **self._shim_env(),
            "RUN_LABEL": self.identity.run_label,
            "EVIDENCE_DIR": "/evidence",
            "FLINK_REST_BASE": "http://flink-jobmanager:8081",
            "HOST_MEMINFO_PATH": "/proc/meminfo",
            "HOST_DISK_PATH": "/evidence",
            "OBSERVER_DEADLINE_S": str(deadline),
            "FLINK_FAILED_CHECKPOINT_BASELINE": str(gate.checkpoints_failed),
        }
        output = self._run_required(
            "observer-start",
            self._pack_command(
                "observer.py",
                values,
                detached=True,
                name=self._observer_name(),
            ),
            60,
        )
        return _extract_single_container_id(
            output,
            reason="observer_container_id_invalid",
        )

    def _wait_observer_ready(self, observer_id: str) -> None:
        deadline = self.monotonic() + 90
        while self.monotonic() <= deadline:
            output = self._run_required(
                "observer-ready",
                [self.docker_executable, "logs", "--tail", "100", observer_id],
                30,
            )
            if "observer_start" in output:
                return
            self.sleep(2)
        raise RuntimeFailure("observer_start_timeout")

    def _run_producer(self) -> None:
        if self.identity is None:
            raise RuntimeFailure("pack_identity_missing")
        values = {
            "RUN_LABEL": self.identity.run_label,
            "SOURCE": self.identity.source,
            "EVENT_PREFIX": self.identity.event_prefix,
            "ORDER_PREFIX": self.identity.order_prefix,
            "COUNT": str(self.config.count),
            "RATE_EPS": str(int(self.config.rate_eps)),
            "KAFKA_BOOTSTRAP_SERVERS": "kafka:9092",
            "EVIDENCE_DIR": "/evidence",
        }
        timeout_s = max(600.0, (self.config.count / self.config.rate_eps) + 600.0)
        output = self._run_required(
            "producer",
            self._pack_command("producer.py", values),
            timeout_s,
        )
        if "result=PASS" not in output:
            raise RuntimeFailure("producer_result_invalid")

    def _validate_producer_final(self) -> None:
        if self.identity is None:
            raise RuntimeFailure("pack_identity_missing")
        path = self.evidence_dir / f"{self.identity.run_label}-final.json"
        producer = _load_bounded_json(path, "producer_final")
        if (
            producer.get("result") != "PASS"
            or producer.get("run_label") != self.identity.run_label
            or producer.get("attempted") != self.config.count
            or producer.get("delivered") != self.config.count
            or producer.get("failures") != 0
            or float(producer.get("rate_eps") or 0) != self.config.rate_eps
            or float(producer.get("elapsed_s") or 0) < self.config.count / self.config.rate_eps
        ):
            raise RuntimeFailure("producer_final_contract_failed")

    def _run_verifier(self, gate: FlinkGate) -> None:
        if self.identity is None:
            raise RuntimeFailure("pack_identity_missing")
        values = {
            **self._common_data_env(),
            **self._shim_env(),
            "RUN_LABEL": self.identity.run_label,
            "SOURCE": self.identity.source,
            "EVENT_PREFIX": self.identity.event_prefix,
            "ORDER_PREFIX": self.identity.order_prefix,
            "EXPECTED": str(self.config.count),
            "VERIFY_PHASE": "soak",
            "AGENTFLOW_RATE_CONTRACT": "dual_mean_90",
            "KAFKA_VERIFY_GROUP": f"{self.config.project_name}-verify",
            "EVIDENCE_DIR": "/evidence",
            "STOP_OBSERVER": "false",
            "FLINK_FAILED_CHECKPOINT_BASELINE": str(gate.checkpoints_failed),
            "FLINK_REST_BASE": "http://flink-jobmanager:8081",
            "FLINK_SOURCE_GROUP": "agentflow-ci-soak-stream",
            "LAKE_GROUP": "agentflow-ci-soak-lake",
            "SERVING_GROUP": "agentflow-ci-soak-serving",
        }
        catchup_budget = (self.config.count / 90.0) - (self.config.count / 100.0)
        timeout_s = max(1800.0, catchup_budget + 900.0)
        output = self._run_required(
            "verify",
            self._pack_command("verify.py", values),
            timeout_s,
        )
        if "result=PASS phase=soak" not in output:
            raise RuntimeFailure("verify_result_invalid")

    def _validate_verify_final(self, gate: FlinkGate) -> None:
        if self.identity is None:
            raise RuntimeFailure("pack_identity_missing")
        path = self.evidence_dir / f"{self.identity.run_label}-soak-verify.json"
        result = _load_bounded_json(path, "soak_verify")
        flink = result.get("flink")
        if (
            result.get("result") != "PASS"
            or result.get("run_label") != self.identity.run_label
            or result.get("verify_phase") != "soak"
            or result.get("expected") != self.config.count
            or result.get("rate_contract") != "dual_mean_90"
            or not isinstance(flink, dict)
            or flink.get("job_id") != gate.job_id
        ):
            raise RuntimeFailure("soak_verify_contract_failed")

    def _assert_no_abort(self) -> None:
        path = self.evidence_dir / "ABORT"
        if path.exists():
            try:
                detail = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                detail = "unreadable"
            raise RuntimeFailure("observer_abort", detail)

    def _cleanup(self) -> list[str]:
        errors: list[str] = []
        if not self.compose_touched:
            return errors
        if self.output_owned:
            try:
                _atomic_write_text(self.evidence_dir / "STOP_OBSERVER", "runtime_cleanup\n")
            except OSError:
                errors.append("stop_observer_write_failed")
        self._cleanup_step(
            "collect-ps",
            self._compose("ps", "--all"),
            errors,
            60,
        )
        self._cleanup_step(
            "collect-logs",
            self._compose("logs", "--no-color", "--tail", "2000"),
            errors,
            180,
        )
        if self.observer_id:
            self._cleanup_step(
                "observer-remove",
                [self.docker_executable, "rm", "-f", self.observer_id],
                errors,
                60,
            )
        if self.shim_id:
            self._cleanup_step(
                "shim-remove",
                [self.docker_executable, "rm", "-f", self.shim_id],
                errors,
                60,
            )
        self._cleanup_step(
            "compose-down",
            self._compose("down", "-v", "--remove-orphans"),
            errors,
            300,
        )
        return errors

    def _cleanup_step(
        self,
        step: str,
        argv: list[str],
        errors: list[str],
        timeout_s: float,
    ) -> None:
        try:
            result = self.runner.run(
                step,
                argv,
                cwd=self.config.project_root,
                timeout_s=timeout_s,
            )
            self._record_step(step, result)
            if result.returncode != 0:
                errors.append(f"{step}_failed")
        except Exception as exc:  # noqa: BLE001 - cleanup must continue through all steps
            errors.append(f"{step}_{type(exc).__name__}")

    def _remove_runtime_dir(self, errors: list[str]) -> None:
        if self.runtime_dir is None:
            return
        path = self.runtime_dir.resolve()
        temp_root = Path(tempfile.gettempdir()).resolve()
        try:
            path.relative_to(temp_root)
            if not path.name.startswith(f"{self.config.project_name}-shim-"):
                raise ValueError("unexpected runtime directory name")
            shutil.rmtree(path)
        except (OSError, ValueError):
            errors.append("runtime_directory_cleanup_failed")

    def _terminal_line(self, passed: bool, reason: str) -> str:
        if not passed:
            return f"RESULT=FAIL reason={reason or 'runtime_failure'}"
        if self.identity is None:
            return "RESULT=FAIL reason=pack_identity_missing"
        if self.config.count == FULL_SOAK_COUNT:
            return (
                "RESULT=SOAK_PASS_DUAL_MEAN_90 "
                f"run={self.identity.run_label} count={self.config.count} "
                "gate=capacity-independent-only does_not_close=mac-rollback"
            )
        return (
            "RESULT=REHEARSAL_PASS "
            f"run={self.identity.run_label} count={self.config.count} "
            "gate=capacity-independent-rehearsal-only"
        )


def _parser() -> argparse.ArgumentParser:
    project_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=project_root)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--project-name", default="agentflow-ci-soak")
    parser.add_argument("--count", type=int, default=FULL_SOAK_COUNT)
    parser.add_argument("--rate-eps", type=float, default=REQUIRED_RATE_EPS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    project_root = args.project_root.resolve()
    source_root = (args.source_root or project_root / "scripts" / "golden_soak").resolve()
    output_dir = (args.output_dir or project_root / ".artifacts" / "soak").resolve()
    config = RuntimeConfig(
        project_root=project_root,
        source_root=source_root,
        output_dir=output_dir,
        project_name=args.project_name,
        count=args.count,
        rate_eps=args.rate_eps,
    )
    outcome = RuntimeHarness(config, runner=SubprocessRunner()).execute()
    print(outcome.terminal, flush=True)
    return 0 if outcome.passed else 1


if __name__ == "__main__":
    sys.exit(main())
