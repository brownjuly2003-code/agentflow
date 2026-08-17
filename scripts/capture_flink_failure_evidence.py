#!/usr/bin/env python3
"""Capture the first Flink failure window to private host-side storage.

The watcher is deliberately read-only: its Kubernetes command surface is
limited to ``get``, ``logs``, and ``exec ... cat``.  It must be armed by a
healthy RUNNING pod topology before a future soak starts traffic.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import quote

TERMINAL_JOB_STATES = frozenset(
    {
        "CANCELED",
        "CANCELLING",
        "FAILED",
        "FAILING",
        "RECONCILING",
        "RESTARTING",
        "SUSPENDED",
    }
)
FAILED_LIFECYCLE_STATES = frozenset({"ERROR", "FAILED"})
FAILED_JM_STATES = frozenset({"ERROR", "MISSING"})
OBSERVER_EVIDENCE_FILES = (
    "soak-observer.jsonl",
    "soak-observer-latest.json",
    "ABORT",
)


class CommandResult(NamedTuple):
    returncode: int
    stdout: str
    stderr: str


class CaptureConfig(NamedTuple):
    context: str
    namespace: str
    flink_deployment: str
    pod_selector: str
    flink_rest_service: str
    flink_rest_port: int
    observer_job: str
    observer_container: str
    observer_evidence_dir: str
    output_dir: Path
    log_since: str
    observer_local_dir: Path | None = None
    expected_pods: int = 2


class CaptureResult(NamedTuple):
    bundle_dir: Path
    errors: tuple[str, ...]


class KubectlClient:
    """Bounded kubectl runner with no shell interpolation."""

    def __init__(
        self,
        *,
        executable: str,
        context: str,
        namespace: str,
        request_timeout_seconds: int,
    ) -> None:
        self._prefix = [executable]
        if context:
            self._prefix.extend(("--context", context))
        self._prefix.extend(
            ("--namespace", namespace, f"--request-timeout={request_timeout_seconds}s")
        )
        self._subprocess_timeout = request_timeout_seconds + 5

    def run(self, *args: str) -> CommandResult:
        try:
            completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
                [*self._prefix, *args],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._subprocess_timeout,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            detail = stderr.strip() or "kubectl subprocess timeout"
            return CommandResult(124, stdout, detail)
        except OSError as exc:
            return CommandResult(127, "", f"{type(exc).__name__}: {exc}")
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        path.chmod(0o700)


def _write_private_text(path: Path, text: str) -> None:
    _ensure_private_dir(path.parent)
    tmp = path.with_name(f".{path.name}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    descriptor = os.open(tmp, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise
    os.replace(tmp, path)
    if os.name != "nt":
        path.chmod(0o600)


def _write_private_json(path: Path, payload: Any) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    _write_private_text(path, text)


def _append_private_jsonl(path: Path, payload: dict[str, Any]) -> None:
    _ensure_private_dir(path.parent)
    line = json.dumps(payload, separators=(",", ":"), ensure_ascii=True) + "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())
    if os.name != "nt":
        path.chmod(0o600)


def _copy_private(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise OSError(f"observer source is not a regular file: {source}")
    _ensure_private_dir(destination.parent)
    tmp = destination.with_name(f".{destination.name}.tmp")
    with source.open("rb") as source_handle, tmp.open("wb") as destination_handle:
        shutil.copyfileobj(source_handle, destination_handle, length=1024 * 1024)
        destination_handle.flush()
        os.fsync(destination_handle.fileno())
    os.replace(tmp, destination)
    if os.name != "nt":
        destination.chmod(0o600)


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return safe or "unknown"


def _status_value(resource: dict[str, Any], *path: str) -> Any:
    value: Any = resource
    for part in path:
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _container_state(state: Any) -> dict[str, Any]:
    if not isinstance(state, dict):
        return {}
    sanitized: dict[str, Any] = {}
    for kind in ("running", "waiting", "terminated"):
        body = state.get(kind)
        if not isinstance(body, dict):
            continue
        allowed = (
            "containerID",
            "exitCode",
            "finishedAt",
            "message",
            "reason",
            "signal",
            "startedAt",
        )
        sanitized[kind] = {key: body[key] for key in allowed if key in body}
    return sanitized


def _container_statuses(status: dict[str, Any], key: str) -> list[dict[str, Any]]:
    sanitized = []
    for item in status.get(key) or []:
        if not isinstance(item, dict):
            continue
        sanitized.append(
            {
                "name": item.get("name"),
                "ready": item.get("ready"),
                "started": item.get("started"),
                "restartCount": item.get("restartCount", 0),
                "state": _container_state(item.get("state")),
                "lastState": _container_state(item.get("lastState")),
            }
        )
    return sanitized


def _sanitize_cr(resource: dict[str, Any]) -> dict[str, Any]:
    metadata = resource.get("metadata") or {}
    return {
        "apiVersion": resource.get("apiVersion"),
        "kind": resource.get("kind"),
        "metadata": {
            key: metadata.get(key)
            for key in (
                "creationTimestamp",
                "deletionTimestamp",
                "generation",
                "name",
                "namespace",
                "resourceVersion",
                "uid",
            )
            if key in metadata
        },
        "status": resource.get("status") or {},
    }


def _sanitize_pods(resource: dict[str, Any]) -> dict[str, Any]:
    pods = []
    for item in resource.get("items") or []:
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata") or {}
        spec = item.get("spec") or {}
        status = item.get("status") or {}
        conditions = []
        for condition in status.get("conditions") or []:
            if not isinstance(condition, dict):
                continue
            allowed = (
                "lastProbeTime",
                "lastTransitionTime",
                "message",
                "reason",
                "status",
                "type",
            )
            conditions.append({key: condition[key] for key in allowed if key in condition})
        pods.append(
            {
                "metadata": {
                    key: metadata.get(key)
                    for key in (
                        "creationTimestamp",
                        "deletionTimestamp",
                        "name",
                        "namespace",
                        "uid",
                    )
                    if key in metadata
                },
                "nodeName": spec.get("nodeName"),
                "status": {
                    key: status.get(key)
                    for key in (
                        "message",
                        "phase",
                        "qosClass",
                        "reason",
                        "startTime",
                    )
                    if key in status
                }
                | {
                    "conditions": conditions,
                    "initContainerStatuses": _container_statuses(status, "initContainerStatuses"),
                    "containerStatuses": _container_statuses(status, "containerStatuses"),
                    "ephemeralContainerStatuses": _container_statuses(
                        status, "ephemeralContainerStatuses"
                    ),
                },
            }
        )
    return {"items": pods}


def _sanitize_events(resource: dict[str, Any]) -> dict[str, Any]:
    events = []
    for item in resource.get("items") or []:
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata") or {}
        involved = item.get("involvedObject") or {}
        source = item.get("source") or {}
        events.append(
            {
                "metadata": {
                    key: metadata.get(key)
                    for key in ("creationTimestamp", "name", "namespace", "uid")
                    if key in metadata
                },
                "involvedObject": {
                    key: involved.get(key)
                    for key in (
                        "apiVersion",
                        "fieldPath",
                        "kind",
                        "name",
                        "namespace",
                        "resourceVersion",
                        "uid",
                    )
                    if key in involved
                },
                "type": item.get("type"),
                "reason": item.get("reason"),
                "message": item.get("message"),
                "action": item.get("action"),
                "count": item.get("count"),
                "eventTime": item.get("eventTime"),
                "firstTimestamp": item.get("firstTimestamp"),
                "lastTimestamp": item.get("lastTimestamp"),
                "reportingComponent": item.get("reportingComponent"),
                "reportingInstance": item.get("reportingInstance"),
                "source": {key: source.get(key) for key in ("component", "host") if key in source},
            }
        )
    return {"items": events}


def _pod_summary(resource: dict[str, Any]) -> tuple[int, int, int]:
    total = 0
    ready = 0
    restarts = 0
    for item in resource.get("items") or []:
        if not isinstance(item, dict):
            continue
        total += 1
        status = item.get("status") or {}
        statuses = status.get("containerStatuses") or []
        restarts += sum(
            int(container.get("restartCount") or 0)
            for container in statuses
            if isinstance(container, dict)
        )
        if (
            status.get("phase") == "Running"
            and statuses
            and all(bool(container.get("ready")) for container in statuses)
        ):
            ready += 1
    return total, ready, restarts


def is_healthy_snapshot(cr: dict[str, Any], pods: dict[str, Any], *, expected_pods: int) -> bool:
    state = str(_status_value(cr, "status", "jobStatus", "state") or "").upper()
    lifecycle = str(_status_value(cr, "status", "lifecycleState") or "").upper()
    jm_state = str(_status_value(cr, "status", "jobManagerDeploymentStatus") or "").upper()
    total, ready, _ = _pod_summary(pods)
    return (
        state == "RUNNING"
        and lifecycle == "STABLE"
        and jm_state == "READY"
        and total == expected_pods
        and ready == expected_pods
    )


def failure_reasons(
    cr: dict[str, Any],
    pods: dict[str, Any],
    *,
    baseline_restarts: int,
    expected_pods: int,
) -> list[str]:
    reasons = []
    state = str(_status_value(cr, "status", "jobStatus", "state") or "").upper()
    lifecycle = str(_status_value(cr, "status", "lifecycleState") or "").upper()
    jm_state = str(_status_value(cr, "status", "jobManagerDeploymentStatus") or "").upper()
    if state in TERMINAL_JOB_STATES:
        reasons.append(f"flink_job_state={state}")
    elif not state:
        reasons.append("flink_job_state=missing")
    if lifecycle in FAILED_LIFECYCLE_STATES:
        reasons.append(f"flink_lifecycle_state={lifecycle}")
    if jm_state in FAILED_JM_STATES:
        reasons.append(f"jobmanager_deployment_status={jm_state}")

    total, ready, restarts = _pod_summary(pods)
    if total != expected_pods:
        reasons.append(f"pod_total={total} expected={expected_pods}")
    elif ready != expected_pods:
        reasons.append(f"pod_ready={ready}/{expected_pods}")
    if restarts > baseline_restarts:
        reasons.append(f"pod_restarts={restarts} baseline={baseline_restarts}")
    return reasons


def classify_failure_surfaces(
    trigger_reasons: list[str],
    *,
    snapshot_errors: list[str] | None = None,
) -> list[str]:
    surfaces = []
    if snapshot_errors:
        surfaces.append("api_observation")
    if any(
        reason.startswith(
            (
                "flink_job_state=",
                "flink_lifecycle_state=",
                "jobmanager_deployment_status=",
            )
        )
        for reason in trigger_reasons
    ):
        surfaces.append("terminal_flink")
    if any(
        reason.startswith(("pod_total=", "pod_ready=", "pod_restarts="))
        for reason in trigger_reasons
    ):
        surfaces.append("pod_topology")
    return surfaces


def _load_json(result: CommandResult, *, label: str) -> tuple[dict[str, Any], str | None]:
    if result.returncode != 0:
        detail = result.stderr.strip() or f"command exited {result.returncode}"
        return {}, f"{label}: {detail}"
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return {}, f"{label}: invalid JSON ({exc.msg})"
    if not isinstance(payload, dict):
        return {}, f"{label}: JSON root is not an object"
    return payload, None


def _job_id(cr: dict[str, Any], overview: dict[str, Any]) -> str | None:
    job_status = _status_value(cr, "status", "jobStatus") or {}
    if isinstance(job_status, dict):
        for key in ("jobId", "jobID", "job_id", "id"):
            value = job_status.get(key)
            if value:
                return str(value)
    for item in overview.get("jobs") or []:
        if not isinstance(item, dict):
            continue
        value = item.get("jid") or item.get("id")
        if value:
            return str(value)
    return None


def _unique_bundle_dir(root: Path, captured_at: datetime) -> Path:
    _ensure_private_dir(root)
    timestamp = captured_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    base = root / f"failure-{timestamp}"
    candidate = base
    suffix = 1
    while candidate.exists():
        suffix += 1
        candidate = root / f"{base.name}-{suffix:02d}"
    _ensure_private_dir(candidate)
    return candidate


def _record_text_command(
    *,
    client: Any,
    args: tuple[str, ...],
    destination: Path,
    label: str,
    errors: list[str],
    commands: list[dict[str, Any]],
) -> CommandResult:
    result = client.run(*args)
    command_record: dict[str, Any] = {
        "label": label,
        "operation": args[0],
        "returncode": result.returncode,
    }
    if result.returncode == 0:
        _write_private_text(destination, result.stdout)
        command_record["artifact"] = destination.name
    else:
        detail = result.stderr.strip() or f"command exited {result.returncode}"
        error_path = destination.with_suffix(".error.txt")
        _write_private_text(error_path, detail + "\n")
        command_record["error_artifact"] = error_path.name
        errors.append(f"{label}: {detail}")
    commands.append(command_record)
    return result


def _record_json_command(
    *,
    client: Any,
    args: tuple[str, ...],
    destination: Path,
    label: str,
    sanitizer: Any | None,
    errors: list[str],
    commands: list[dict[str, Any]],
) -> dict[str, Any]:
    result = client.run(*args)
    payload, error = _load_json(result, label=label)
    command_record: dict[str, Any] = {
        "label": label,
        "operation": args[0],
        "returncode": result.returncode,
    }
    if error is None:
        persisted = sanitizer(payload) if sanitizer is not None else payload
        _write_private_json(destination, persisted)
        command_record["artifact"] = destination.name
    else:
        error_path = destination.with_suffix(".error.txt")
        _write_private_text(error_path, error + "\n")
        command_record["error_artifact"] = error_path.name
        errors.append(error)
    commands.append(command_record)
    return payload


def _pod_container_names(pod: dict[str, Any]) -> list[str]:
    names = []
    spec = pod.get("spec") or {}
    status = pod.get("status") or {}
    for key in ("initContainers", "containers", "ephemeralContainers"):
        for container in spec.get(key) or []:
            if isinstance(container, dict) and container.get("name"):
                names.append(str(container["name"]))
    for key in (
        "initContainerStatuses",
        "containerStatuses",
        "ephemeralContainerStatuses",
    ):
        for container in status.get(key) or []:
            if isinstance(container, dict) and container.get("name"):
                names.append(str(container["name"]))
    return list(dict.fromkeys(names))


def _capture_pod_logs(
    *,
    client: Any,
    pod: dict[str, Any],
    log_dir: Path,
    log_since: str,
    errors: list[str],
    commands: list[dict[str, Any]],
) -> None:
    metadata = pod.get("metadata") or {}
    pod_name = str(metadata.get("name") or "")
    if not pod_name:
        errors.append("flink_logs: pod name missing")
        return
    containers = _pod_container_names(pod)
    if not containers:
        errors.append(f"flink_logs: no containers found for {pod_name}")
        return
    for container in containers:
        stem = f"{_safe_name(pod_name)}__{_safe_name(container)}"
        common = (
            "logs",
            pod_name,
            "-c",
            container,
            "--timestamps=true",
            f"--since={log_since}",
        )
        _record_text_command(
            client=client,
            args=common,
            destination=log_dir / f"{stem}.current.log",
            label=f"flink_log_current:{pod_name}:{container}",
            errors=errors,
            commands=commands,
        )
        _record_text_command(
            client=client,
            args=(*common, "--previous=true"),
            destination=log_dir / f"{stem}.previous.log",
            label=f"flink_log_previous:{pod_name}:{container}",
            errors=errors,
            commands=commands,
        )


def _capture_observer(
    *,
    client: Any,
    config: CaptureConfig,
    observer_dir: Path,
    errors: list[str],
    commands: list[dict[str, Any]],
) -> None:
    if config.observer_local_dir is not None:
        for name in OBSERVER_EVIDENCE_FILES:
            source = config.observer_local_dir / name
            try:
                _copy_private(source, observer_dir / name)
            except OSError as exc:
                errors.append(f"observer_local:{name}: {exc}")
        return

    result = client.run("get", "pods", "-l", f"job-name={config.observer_job}", "-o", "json")
    commands.append(
        {
            "label": "observer_pods",
            "operation": "get",
            "returncode": result.returncode,
        }
    )
    observer_pods, error = _load_json(result, label="observer_pods")
    if error is not None:
        errors.append(error)
        _write_private_text(observer_dir / "observer-pods.error.txt", error + "\n")
        return
    items = observer_pods.get("items") or []
    if not items:
        errors.append("observer_pods: no matching pod")
        _write_private_text(observer_dir / "observer-pods.error.txt", "no matching pod\n")
        return
    observer_pod = str((items[0].get("metadata") or {}).get("name") or "")
    if not observer_pod:
        errors.append("observer_pods: matching pod has no name")
        return

    common = (
        "logs",
        observer_pod,
        "-c",
        config.observer_container,
        "--timestamps=true",
        f"--since={config.log_since}",
    )
    _record_text_command(
        client=client,
        args=common,
        destination=observer_dir / "observer.current.log",
        label="observer_log_current",
        errors=errors,
        commands=commands,
    )
    _record_text_command(
        client=client,
        args=(*common, "--previous=true"),
        destination=observer_dir / "observer.previous.log",
        label="observer_log_previous",
        errors=errors,
        commands=commands,
    )
    evidence_root = config.observer_evidence_dir.rstrip("/") or "/"
    for name in OBSERVER_EVIDENCE_FILES:
        source = f"{evidence_root}/{name}" if evidence_root != "/" else f"/{name}"
        _record_text_command(
            client=client,
            args=(
                "exec",
                observer_pod,
                "-c",
                config.observer_container,
                "--",
                "cat",
                source,
            ),
            destination=observer_dir / name,
            label=f"observer_evidence:{name}",
            errors=errors,
            commands=commands,
        )


def capture_evidence(
    client: Any,
    config: CaptureConfig,
    *,
    trigger_reasons: list[str],
    cr: dict[str, Any] | None = None,
    pods: dict[str, Any] | None = None,
    captured_at: datetime | None = None,
) -> CaptureResult:
    captured_at = captured_at or datetime.now(UTC)
    bundle = _unique_bundle_dir(Path(config.output_dir), captured_at)
    errors: list[str] = []
    commands: list[dict[str, Any]] = []

    if cr is None:
        cr = _record_json_command(
            client=client,
            args=("get", "flinkdeployment", config.flink_deployment, "-o", "json"),
            destination=bundle / "flinkdeployment-status.json",
            label="flinkdeployment_status",
            sanitizer=_sanitize_cr,
            errors=errors,
            commands=commands,
        )
    else:
        _write_private_json(bundle / "flinkdeployment-status.json", _sanitize_cr(cr))

    if pods is None:
        pods = _record_json_command(
            client=client,
            args=("get", "pods", "-l", config.pod_selector, "-o", "json"),
            destination=bundle / "pod-termination-states.json",
            label="flink_pod_statuses",
            sanitizer=_sanitize_pods,
            errors=errors,
            commands=commands,
        )
    else:
        _write_private_json(bundle / "pod-termination-states.json", _sanitize_pods(pods))

    pod_items = [pod for pod in pods.get("items") or [] if isinstance(pod, dict)]
    if len(pod_items) != config.expected_pods:
        error = f"flink_logs: pod_total={len(pod_items)} expected={config.expected_pods}"
        errors.append(error)
        _write_private_text(bundle / "logs" / "pod-count.error.txt", error + "\n")
    for pod in pod_items:
        _capture_pod_logs(
            client=client,
            pod=pod,
            log_dir=bundle / "logs",
            log_since=config.log_since,
            errors=errors,
            commands=commands,
        )

    _record_json_command(
        client=client,
        args=("get", "events", "-o", "json"),
        destination=bundle / "namespace-events.json",
        label="namespace_events",
        sanitizer=_sanitize_events,
        errors=errors,
        commands=commands,
    )

    rest_dir = bundle / "flink"
    namespace = quote(config.namespace, safe="")
    service = quote(config.flink_rest_service, safe="")
    rest_base = (
        f"/api/v1/namespaces/{namespace}/services/http:{service}:{config.flink_rest_port}/proxy"
    )
    overview = _record_json_command(
        client=client,
        args=("get", "--raw", f"{rest_base}/jobs/overview"),
        destination=rest_dir / "jobs-overview.json",
        label="flink_jobs_overview",
        sanitizer=None,
        errors=errors,
        commands=commands,
    )
    job_id = _job_id(cr, overview)
    if job_id:
        encoded_job_id = quote(job_id, safe="")
        endpoints = (
            ("job-detail.json", f"/jobs/{encoded_job_id}"),
            (
                "job-exceptions.json",
                f"/jobs/{encoded_job_id}/exceptions?maxExceptions=100",
            ),
            (
                "job-execution-result.json",
                f"/jobs/{encoded_job_id}/execution-result",
            ),
            ("job-checkpoints.json", f"/jobs/{encoded_job_id}/checkpoints"),
        )
        for filename, endpoint in endpoints:
            _record_json_command(
                client=client,
                args=("get", "--raw", f"{rest_base}{endpoint}"),
                destination=rest_dir / filename,
                label=f"flink_rest:{filename}",
                sanitizer=None,
                errors=errors,
                commands=commands,
            )
    else:
        error = "flink_rest: job id unavailable"
        errors.append(error)
        _write_private_text(rest_dir / "job-id.error.txt", error + "\n")

    _capture_observer(
        client=client,
        config=config,
        observer_dir=bundle / "observer",
        errors=errors,
        commands=commands,
    )

    manifest = {
        "schema_version": 1,
        "captured_at_utc": captured_at.astimezone(UTC).isoformat(),
        "trigger_reasons": trigger_reasons,
        "failure_surfaces": classify_failure_surfaces(trigger_reasons),
        "context": config.context,
        "namespace": config.namespace,
        "flink_deployment": config.flink_deployment,
        "pod_selector": config.pod_selector,
        "expected_pods": config.expected_pods,
        "captured_pods": len(pod_items),
        "flink_rest_service": config.flink_rest_service,
        "observer_job": config.observer_job,
        "read_only_operations": ["exec-cat", "get", "logs"],
        "complete": not errors,
        "errors": errors,
        "commands": commands,
    }
    _write_private_json(bundle / "manifest.json", manifest)
    return CaptureResult(bundle, tuple(errors))


def _snapshot(
    client: Any, config: CaptureConfig
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    errors = []
    cr_result = client.run("get", "flinkdeployment", config.flink_deployment, "-o", "json")
    cr, error = _load_json(cr_result, label="watch_flinkdeployment")
    if error is not None:
        errors.append(error)
    pods_result = client.run("get", "pods", "-l", config.pod_selector, "-o", "json")
    pods, error = _load_json(pods_result, label="watch_flink_pods")
    if error is not None:
        errors.append(error)
    return cr, pods, errors


def watch(
    client: Any,
    config: CaptureConfig,
    *,
    poll_interval_seconds: float,
    timeout_seconds: float,
    stop_file: Path | None,
) -> int:
    output_dir = Path(config.output_dir)
    _ensure_private_dir(output_dir)
    chronology_path = output_dir / "failure-watcher-chronology.jsonl"
    state_path = output_dir / "failure-watcher-state.json"
    started = time.monotonic()
    armed = False
    baseline_restarts = 0
    sample = 0

    while True:
        sample += 1
        captured_at = datetime.now(UTC)
        if stop_file is not None and stop_file.exists():
            state = {
                "state": "stopped",
                "armed": armed,
                "sample": sample,
                "utc": captured_at.isoformat(),
            }
            _write_private_json(state_path, state)
            _append_private_jsonl(chronology_path, state)
            return 0
        if timeout_seconds > 0 and time.monotonic() - started >= timeout_seconds:
            state = {
                "state": "timeout",
                "armed": armed,
                "sample": sample,
                "utc": captured_at.isoformat(),
            }
            _write_private_json(state_path, state)
            _append_private_jsonl(chronology_path, state)
            return 3

        cr, pods, snapshot_errors = _snapshot(client, config)
        total, ready, restarts = _pod_summary(pods)
        job_state = str(_status_value(cr, "status", "jobStatus", "state") or "").upper()
        reasons: list[str] = []
        if not snapshot_errors:
            if not armed and is_healthy_snapshot(cr, pods, expected_pods=config.expected_pods):
                armed = True
                baseline_restarts = restarts
            elif armed:
                reasons = failure_reasons(
                    cr,
                    pods,
                    baseline_restarts=baseline_restarts,
                    expected_pods=config.expected_pods,
                )
        state = {
            "state": "armed" if armed else "waiting_for_healthy",
            "armed": armed,
            "sample": sample,
            "utc": captured_at.isoformat(),
            "flink_job_state": job_state or None,
            "pods_total": total,
            "pods_ready": ready,
            "pod_restarts": restarts,
            "baseline_restarts": baseline_restarts if armed else None,
            "snapshot_errors": snapshot_errors,
            "trigger_reasons": reasons,
            "failure_surfaces": classify_failure_surfaces(
                reasons,
                snapshot_errors=snapshot_errors,
            ),
        }
        _write_private_json(state_path, state)
        _append_private_jsonl(chronology_path, state)
        if reasons:
            result = capture_evidence(
                client,
                config,
                trigger_reasons=reasons,
                cr=cr,
                pods=pods,
                captured_at=captured_at,
            )
            final_state = state | {
                "state": "captured",
                "bundle_dir": str(result.bundle_dir),
                "capture_errors": list(result.errors),
            }
            _write_private_json(state_path, final_state)
            _append_private_jsonl(chronology_path, final_state)
            print(f"failure evidence captured: {result.bundle_dir}", flush=True)
            return 2
        time.sleep(poll_interval_seconds)


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--context", default="", help="kubectl context")
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--flink-deployment", required=True)
    parser.add_argument("--pod-selector", required=True)
    parser.add_argument("--flink-rest-service", required=True)
    parser.add_argument("--flink-rest-port", type=int, default=8081)
    parser.add_argument("--observer-job", required=True)
    parser.add_argument("--observer-container", default="observer")
    parser.add_argument("--observer-evidence-dir", default="/evidence")
    parser.add_argument("--observer-local-dir", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--log-since", default="6h")
    parser.add_argument("--expected-pods", type=int, default=2)
    parser.add_argument("--kubectl", default="kubectl")
    parser.add_argument("--request-timeout-seconds", type=int, default=20)


def _config_from_args(args: argparse.Namespace) -> CaptureConfig:
    return CaptureConfig(
        context=args.context,
        namespace=args.namespace,
        flink_deployment=args.flink_deployment,
        pod_selector=args.pod_selector,
        flink_rest_service=args.flink_rest_service,
        flink_rest_port=args.flink_rest_port,
        observer_job=args.observer_job,
        observer_container=args.observer_container,
        observer_evidence_dir=args.observer_evidence_dir,
        output_dir=args.output_dir,
        log_since=args.log_since,
        observer_local_dir=args.observer_local_dir,
        expected_pods=args.expected_pods,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    watch_parser = subparsers.add_parser("watch", help="arm and capture first failure")
    _add_common_arguments(watch_parser)
    watch_parser.add_argument("--poll-interval-seconds", type=float, default=10.0)
    watch_parser.add_argument("--timeout-seconds", type=float, default=21600.0)
    watch_parser.add_argument("--stop-file", type=Path)

    capture_parser = subparsers.add_parser("capture", help="capture immediately")
    _add_common_arguments(capture_parser)
    capture_parser.add_argument(
        "--reason", action="append", default=[], help="manual trigger reason"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)
    args = _parser().parse_args(argv)
    if args.request_timeout_seconds <= 0:
        raise SystemExit("--request-timeout-seconds must be positive")
    if args.expected_pods <= 0:
        raise SystemExit("--expected-pods must be positive")
    config = _config_from_args(args)
    client = KubectlClient(
        executable=args.kubectl,
        context=config.context,
        namespace=config.namespace,
        request_timeout_seconds=args.request_timeout_seconds,
    )
    if args.command == "capture":
        reasons = args.reason or ["manual_capture"]
        result = capture_evidence(client, config, trigger_reasons=reasons)
        print(
            f"evidence bundle: {result.bundle_dir} errors={len(result.errors)}",
            flush=True,
        )
        return 0
    if args.poll_interval_seconds <= 0:
        raise SystemExit("--poll-interval-seconds must be positive")
    return watch(
        client,
        config,
        poll_interval_seconds=args.poll_interval_seconds,
        timeout_seconds=args.timeout_seconds,
        stop_file=args.stop_file,
    )


if __name__ == "__main__":
    sys.exit(main())
