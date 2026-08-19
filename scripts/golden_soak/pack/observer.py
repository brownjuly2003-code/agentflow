#!/usr/bin/env python3
"""Fail-closed soak observer: resources, Flink health, pod restarts.

Samples every 60s until <EVIDENCE_DIR>/STOP_OBSERVER or deadline.
Creates <EVIDENCE_DIR>/ABORT atomically on fail-closed conditions.
Never logs service-account tokens.
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SAMPLE_INTERVAL_S = 60.0
DISK_ABORT_PCT = 90.0
DISK_ABORT_FREE_BYTES = 2 * 1024 * 1024 * 1024
MEM_ABORT_KB = 400 * 1024  # 400 MiB in kB
CONSECUTIVE_NEED = 2
# Transient K8s API / Flink failover blips under node pressure (seen as
# TimeoutError/URLError and short SUSPENDED windows). Do not abort soak on
# a single 60–120s API stall — that is what killed 20260807-01/02.
CONSECUTIVE_API_NEED = 5
CONSECUTIVE_FLINK_NEED = 5
CHECKPOINT_STAGNATION_SAMPLES = 5
# Allow one TM/JM container restart without fail-closed (recovery path).
MAX_POD_RESTARTS = 1
# K8s list timeout — 10s was too tight when apiserver contended.
K8S_LIST_TIMEOUT_S = 30.0
API_TRANSPORT_ERRORS = frozenset(
    {"TimeoutError", "URLError", "HTTPError", "OSError", "SSLError"}
)

# --- Abort policy (verbatim logic of scripts/soak_observer_policy.py @2fa6042).
# Terminal Flink state decides immediately; API observation failures can only
# abort as pods_api_unhealthy; Flink-led degradation is re-attributed instead
# of being stored as a pod-topology reason (soak -01..-05 RCA).
from dataclasses import dataclass

TERMINAL_JOB_STATES = frozenset({"FAILED"})


@dataclass(frozen=True)
class FlinkSample:
    ok: bool
    job_state: str | None
    tasks_running: int
    tasks_total: int
    tasks_all_running: bool
    error: str | None = None


@dataclass(frozen=True)
class PodsSample:
    ok: bool
    api_error: str | None
    ready_count: int
    total_count: int
    all_running_ready: bool
    restart_total: int


@dataclass(frozen=True)
class AbortDecision:
    reason_class: str
    detail: str


class FlinkPodsAbortPolicy:
    def __init__(
        self,
        *,
        expected_pods: int,
        max_pod_restarts: int,
        api_streak_need: int,
        flink_streak_need: int,
        topology_streak_need: int,
    ) -> None:
        self._expected_pods = expected_pods
        self._max_pod_restarts = max_pod_restarts
        self._api_streak_need = api_streak_need
        self._flink_streak_need = flink_streak_need
        self._topology_streak_need = topology_streak_need
        self._flink_bad_streak = 0
        self._api_bad_streak = 0
        self._topology_bad_streak = 0
        self._decision: AbortDecision | None = None

    @property
    def decision(self) -> AbortDecision | None:
        return self._decision

    def observe(self, flink: FlinkSample, pods: PodsSample) -> AbortDecision | None:
        if self._decision is not None:
            return self._decision

        flink_bad = (
            (not flink.ok)
            or str(flink.job_state or "") != "RUNNING"
            or not flink.tasks_all_running
        )
        self._flink_bad_streak = self._flink_bad_streak + 1 if flink_bad else 0

        api_err = bool(pods.api_error) or (
            (not pods.ok) and str(pods.api_error or "") in API_TRANSPORT_ERRORS
        )
        if api_err:
            self._api_bad_streak += 1
        else:
            self._api_bad_streak = 0
            topology_bad = (not pods.ok) or (
                pods.total_count != self._expected_pods
                or pods.ready_count != self._expected_pods
                or not pods.all_running_ready
            )
            self._topology_bad_streak = (
                self._topology_bad_streak + 1 if topology_bad else 0
            )

        flink_context = (
            f"flink_state={flink.job_state} "
            f"tasks={flink.tasks_running}/{flink.tasks_total} "
            f"flink_error={flink.error}"
        )
        pods_context = (
            f"pods_ready={pods.ready_count}/{pods.total_count} "
            f"pods_error={pods.api_error}"
        )

        if str(flink.job_state or "") in TERMINAL_JOB_STATES:
            return self._decide("flink_terminal", f"{flink_context} {pods_context}")

        if self._flink_bad_streak >= self._flink_streak_need:
            return self._decide(
                "flink_unhealthy",
                f"{flink_context} streak={self._flink_bad_streak} {pods_context}",
            )

        if pods.ok and pods.restart_total > self._max_pod_restarts:
            return self._decide(
                "pod_restart_budget",
                f"pod_restarts={pods.restart_total} "
                f"max={self._max_pod_restarts} {flink_context}",
            )

        if self._api_bad_streak >= self._api_streak_need:
            return self._decide(
                "pods_api_unhealthy",
                f"{pods_context} streak={self._api_bad_streak} {flink_context}",
            )

        if self._topology_bad_streak >= self._topology_streak_need:
            if self._flink_bad_streak >= self._topology_bad_streak:
                return self._decide(
                    "flink_led_topology_loss",
                    f"{flink_context} flink_streak={self._flink_bad_streak} "
                    f"{pods_context} topology_streak={self._topology_bad_streak}",
                )
            return self._decide(
                "pod_topology_unhealthy",
                f"{pods_context} streak={self._topology_bad_streak} {flink_context}",
            )

        return None

    def _decide(self, reason_class: str, detail: str) -> AbortDecision:
        self._decision = AbortDecision(reason_class=reason_class, detail=detail)
        return self._decision


def _policy_samples(
    flink: dict[str, Any], pods: dict[str, Any]
) -> tuple[FlinkSample, PodsSample]:
    """Map the observer snapshot dicts onto the policy dataclasses.

    Folds the -05 dual-field API-error detection (pods["api_error"] plus
    transport-class pods["error"]) into the single policy api_error field.
    """
    api_error = pods.get("api_error")
    if not api_error and not pods.get("ok"):
        err = str(pods.get("error") or "")
        if err in API_TRANSPORT_ERRORS:
            api_error = err
    return (
        FlinkSample(
            ok=bool(flink.get("ok")),
            job_state=flink.get("job_state"),
            tasks_running=int(flink.get("tasks_running") or 0),
            tasks_total=int(flink.get("tasks_total") or 0),
            tasks_all_running=bool(flink.get("tasks_all_running")),
            error=str(flink.get("error")) if flink.get("error") is not None else None,
        ),
        PodsSample(
            ok=bool(pods.get("ok")),
            api_error=str(api_error) if api_error else None,
            ready_count=int(pods.get("ready_count") or 0),
            total_count=int(pods.get("total_count") or 0),
            all_running_ready=bool(pods.get("all_running_ready")),
            restart_total=int(pods.get("restart_total") or 0),
        ),
    )


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value == "":
        raise SystemExit(f"missing_env={name}")
    return value


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=True) + "\n"
    tmp.write_text(data, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, separators=(",", ":"), ensure_ascii=True) + "\n"
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())


def _create_abort(evidence_dir: Path, reason: str) -> None:
    """Preserve the first ABORT atomically; never overwrite."""
    abort_path = evidence_dir / "ABORT"
    if abort_path.exists():
        return
    tmp = abort_path.with_suffix(".tmp")
    body = reason.strip() + "\n"
    tmp.write_text(body, encoding="utf-8", newline="\n")
    os.replace(tmp, abort_path)


def _read_mem_available_kb(meminfo_path: Path) -> int | None:
    try:
        text = meminfo_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("MemAvailable:"):
            parts = line.split()
            if len(parts) >= 2:
                return int(parts[1])
    return None


def _disk_stats(path: Path) -> dict[str, Any]:
    try:
        st = os.statvfs(path)
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    total = st.f_frsize * st.f_blocks
    free = st.f_frsize * st.f_bavail
    used = total - free
    used_pct = (used / total * 100.0) if total > 0 else 100.0
    return {
        "ok": True,
        "total_bytes": total,
        "free_bytes": free,
        "used_bytes": used,
        "used_pct": round(used_pct, 3),
    }


def _http_json(url: str, timeout: float = 10.0, headers: dict[str, str] | None = None) -> Any:
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _flink_snapshot(rest_base: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "ok": False,
        "job_id": None,
        "job_state": None,
        "tasks_total": None,
        "tasks_running": None,
        "tasks_all_running": False,
        "checkpoints_completed": None,
        "checkpoints_failed": None,
        "latest_checkpoint": None,
        "error": None,
    }
    try:
        overview = _http_json(f"{rest_base}/jobs/overview")
        jobs = overview.get("jobs") or []
        if not jobs:
            out["error"] = "no_jobs"
            return out
        job = jobs[0]
        job_id = str(job.get("jid") or job.get("id") or "")
        state = str(job.get("state") or "")
        out["job_id"] = job_id
        out["job_state"] = state
        tasks = job.get("tasks") or {}
        tasks_total = int(tasks.get("total", 0) or 0)
        tasks_running = int(tasks.get("running", 0) or 0)
        out["tasks_total"] = tasks_total
        out["tasks_running"] = tasks_running
        out["tasks_all_running"] = tasks_total > 0 and tasks_running == tasks_total
        if job_id:
            cps = _http_json(f"{rest_base}/jobs/{job_id}/checkpoints")
            counts = cps.get("counts") or {}
            out["checkpoints_completed"] = int(counts.get("completed", 0) or 0)
            out["checkpoints_failed"] = int(counts.get("failed", 0) or 0)
            latest = cps.get("latest") or {}
            completed = latest.get("completed") or {}
            out["latest_checkpoint"] = completed.get("id")
        out["ok"] = True
        return out
    except Exception as exc:  # noqa: BLE001 — observer must stay up
        out["error"] = type(exc).__name__
        return out


def _k8s_pods(
    *,
    api_host: str,
    namespace: str,
    label_selector: str,
    token_path: Path,
    ca_path: Path,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "ok": False,
        "pods": [],
        "ready_count": 0,
        "total_count": 0,
        "restart_total": 0,
        "all_running_ready": False,
        "error": None,
    }
    try:
        token = token_path.read_text(encoding="utf-8").strip()
        # urllib.request.quote does not exist — use urllib.parse.quote.
        quoted = urllib.parse.quote(label_selector, safe="")
        url = (
            f"{api_host}/api/v1/namespaces/{urllib.parse.quote(namespace, safe='')}/pods"
            f"?labelSelector={quoted}"
        )
        ctx = ssl.create_default_context(cafile=str(ca_path))
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            method="GET",
        )
        with urllib.request.urlopen(
            req, timeout=K8S_LIST_TIMEOUT_S, context=ctx
        ) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        pods_out = []
        ready_count = 0
        restart_total = 0
        for item in body.get("items") or []:
            meta = item.get("metadata") or {}
            status = item.get("status") or {}
            name = str(meta.get("name") or "")
            phase = str(status.get("phase") or "")
            restarts = 0
            ready = False
            cstatuses = status.get("containerStatuses") or []
            for cs in cstatuses:
                restarts += int(cs.get("restartCount") or 0)
            if cstatuses:
                ready = all(bool(cs.get("ready")) for cs in cstatuses)
            if ready and phase == "Running":
                ready_count += 1
            restart_total += restarts
            pods_out.append(
                {
                    "name": name,
                    "phase": phase,
                    "ready": ready,
                    "restarts": restarts,
                }
            )
        out["pods"] = pods_out
        out["ready_count"] = ready_count
        out["total_count"] = len(pods_out)
        out["restart_total"] = restart_total
        # Ready topology = 2 Running+Ready; restarts are tracked separately.
        out["all_running_ready"] = len(pods_out) == 2 and ready_count == 2
        out["ok"] = True
        out["api_error"] = False
        return out
    except Exception as exc:  # noqa: BLE001
        err_name = type(exc).__name__
        out["error"] = err_name
        out["api_error"] = err_name in API_TRANSPORT_ERRORS
        return out


def _read_producer(evidence_dir: Path, run_label: str) -> dict[str, Any]:
    final_path = evidence_dir / f"{run_label}-final.json"
    progress_path = evidence_dir / f"{run_label}-progress.json"
    for path in (final_path, progress_path):
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
    return {}


def main() -> int:
    evidence_dir = Path(_env("EVIDENCE_DIR"))
    run_label = os.environ.get("RUN_LABEL", "golden-4h-soak-rv-20260802-01")
    flink_rest = _env(
        "FLINK_REST_BASE",
        "http://agentflow-soak-rv-stream-processor-rest:8081",
    ).rstrip("/")
    meminfo_path = Path(_env("HOST_MEMINFO_PATH", "/host/proc/meminfo"))
    disk_path = Path(_env("HOST_DISK_PATH", "/host/var"))
    k8s_host = _env("KUBERNETES_API", "https://kubernetes.default.svc")
    namespace = _env("POD_NAMESPACE", "agentflow")
    label_selector = _env("FLINK_POD_SELECTOR", "app=agentflow-soak-rv-stream-processor")
    token_path = Path(
        _env("SA_TOKEN_PATH", "/var/run/secrets/kubernetes.io/serviceaccount/token")
    )
    ca_path = Path(
        _env("SA_CA_PATH", "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")
    )
    deadline_s = float(os.environ.get("OBSERVER_DEADLINE_S", "19800"))
    # Cumulative failed-checkpoint baseline from Gate A (not "must be zero").
    failed_cp_baseline = int(_env("FLINK_FAILED_CHECKPOINT_BASELINE"), 10)
    if failed_cp_baseline < 0:
        raise SystemExit(f"negative_flink_failed_checkpoint_baseline={failed_cp_baseline}")

    evidence_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = evidence_dir / "soak-observer.jsonl"
    latest_path = evidence_dir / "soak-observer-latest.json"
    stop_path = evidence_dir / "STOP_OBSERVER"
    abort_path = evidence_dir / "ABORT"

    if abort_path.exists():
        reason = abort_path.read_text(encoding="utf-8", errors="replace").strip()
        print(f"result=FAIL reason=preexisting_abort detail={reason}", flush=True)
        return 1

    start = time.monotonic()
    mem_low_streak = 0
    mem_unavail_streak = 0
    disk_unavail_streak = 0
    flink_bad_streak = 0
    pods_bad_streak = 0
    pods_api_bad_streak = 0
    policy = FlinkPodsAbortPolicy(
        expected_pods=2,
        max_pod_restarts=MAX_POD_RESTARTS,
        api_streak_need=CONSECUTIVE_API_NEED,
        flink_streak_need=CONSECUTIVE_FLINK_NEED,
        topology_streak_need=CONSECUTIVE_NEED,
    )
    cp_window: list[int] = []
    sample_n = 0
    first_abort_reason: str | None = None

    print(
        f"observer_start run={run_label} interval_s={SAMPLE_INTERVAL_S} "
        f"api_need={CONSECUTIVE_API_NEED} flink_need={CONSECUTIVE_FLINK_NEED} "
        f"max_pod_restarts={MAX_POD_RESTARTS}",
        flush=True,
    )

    while True:
        if stop_path.exists():
            print("observer_stop reason=STOP_OBSERVER", flush=True)
            return 0
        if time.monotonic() - start >= deadline_s:
            print("observer_stop reason=deadline", flush=True)
            return 0

        sample_n += 1
        now_epoch = time.time()
        now_utc = datetime.now(UTC).isoformat()
        mono = time.monotonic()
        producer = _read_producer(evidence_dir, run_label)
        mem_kb = _read_mem_available_kb(meminfo_path)
        disk = _disk_stats(disk_path)
        flink = _flink_snapshot(flink_rest)
        pods = _k8s_pods(
            api_host=k8s_host,
            namespace=namespace,
            label_selector=label_selector,
            token_path=token_path,
            ca_path=ca_path,
        )

        abort_reason: str | None = None

        # Disk threshold fail-closed (single sample when readable).
        if disk.get("ok"):
            disk_unavail_streak = 0
            if float(disk["used_pct"]) >= DISK_ABORT_PCT:
                abort_reason = f"disk_used_pct={disk['used_pct']}"
            elif int(disk["free_bytes"]) < DISK_ABORT_FREE_BYTES:
                abort_reason = f"disk_free_bytes={disk['free_bytes']}"
        else:
            disk_unavail_streak += 1
            if disk_unavail_streak >= CONSECUTIVE_NEED and abort_reason is None:
                abort_reason = f"disk_unavailable error={disk.get('error')}"

        # Memory: two consecutive low OR two consecutive unavailable.
        if mem_kb is None:
            mem_unavail_streak += 1
            mem_low_streak = 0
            if mem_unavail_streak >= CONSECUTIVE_NEED and abort_reason is None:
                abort_reason = "mem_available_unavailable"
        else:
            mem_unavail_streak = 0
            if mem_kb < MEM_ABORT_KB:
                mem_low_streak += 1
            else:
                mem_low_streak = 0
            if mem_low_streak >= CONSECUTIVE_NEED and abort_reason is None:
                abort_reason = f"mem_available_kb={mem_kb}"

        # Flink / API / pod-topology decision via the RCA-grounded policy
        # (terminal state immediate; API errors never become topology reasons).
        flink_sample, pods_sample = _policy_samples(flink, pods)
        decision = policy.observe(flink_sample, pods_sample)
        if decision is not None and abort_reason is None:
            abort_reason = f"{decision.reason_class} {decision.detail}"
        flink_bad_streak = policy._flink_bad_streak
        pods_api_bad_streak = policy._api_bad_streak
        pods_bad_streak = policy._topology_bad_streak

        # Failed-checkpoint increase above Gate A baseline is fatal immediately.
        failed_cp = flink.get("checkpoints_failed")
        if (
            failed_cp is not None
            and int(failed_cp) > failed_cp_baseline
            and abort_reason is None
        ):
            abort_reason = (
                f"failed_checkpoints={failed_cp} baseline={failed_cp_baseline}"
            )

        # Checkpoint stagnation over a bounded five-sample window → ABORT.
        if flink.get("ok") and flink.get("checkpoints_completed") is not None:
            cp_window.append(int(flink["checkpoints_completed"]))
            if len(cp_window) > CHECKPOINT_STAGNATION_SAMPLES:
                cp_window.pop(0)
            if (
                len(cp_window) == CHECKPOINT_STAGNATION_SAMPLES
                and len(set(cp_window)) == 1
                and abort_reason is None
            ):
                abort_reason = (
                    f"checkpoint_stagnation completed={cp_window[0]} "
                    f"window={CHECKPOINT_STAGNATION_SAMPLES}"
                )

        # Record first_abort_reason before constructing/writing this sample so
        # the first aborting sample itself carries the preserved reason.
        if abort_reason is not None and first_abort_reason is None:
            first_abort_reason = abort_reason

        sample = {
            "sample": sample_n,
            "utc": now_utc,
            "epoch": now_epoch,
            "mono": mono,
            "run_label": run_label,
            "producer_delivered": producer.get("delivered"),
            "producer_attempted": producer.get("attempted"),
            "producer_failures": producer.get("failures"),
            "producer_result": producer.get("result"),
            "mem_available_kb": mem_kb,
            "disk": disk,
            "flink": {
                "ok": flink.get("ok"),
                "job_id": flink.get("job_id"),
                "job_state": flink.get("job_state"),
                "tasks_total": flink.get("tasks_total"),
                "tasks_running": flink.get("tasks_running"),
                "tasks_all_running": flink.get("tasks_all_running"),
                "checkpoints_completed": flink.get("checkpoints_completed"),
                "checkpoints_failed": flink.get("checkpoints_failed"),
                "latest_checkpoint": flink.get("latest_checkpoint"),
                "error": flink.get("error"),
            },
            "pods": {
                "ok": pods.get("ok"),
                "ready_count": pods.get("ready_count"),
                "total_count": pods.get("total_count"),
                "restart_total": pods.get("restart_total"),
                "all_running_ready": pods.get("all_running_ready"),
                "error": pods.get("error"),
                "items": pods.get("pods") or [],
                "names": [p.get("name") for p in (pods.get("pods") or [])],
            },
            "mem_low_streak": mem_low_streak,
            "mem_unavail_streak": mem_unavail_streak,
            "disk_unavail_streak": disk_unavail_streak,
            "flink_bad_streak": flink_bad_streak,
            "pods_bad_streak": pods_bad_streak,
            "pods_api_bad_streak": pods_api_bad_streak,
            "cp_window": list(cp_window),
            "abort_reason": abort_reason,
            "first_abort_reason": first_abort_reason,
        }
        _append_jsonl(jsonl_path, sample)
        _atomic_write(latest_path, sample)

        print(
            f"observer sample={sample_n} epoch={now_epoch:.0f} utc={now_utc} "
            f"mem_kb={mem_kb} disk_pct={disk.get('used_pct')} "
            f"flink={flink.get('job_state')} "
            f"cp_done={flink.get('checkpoints_completed')} "
            f"cp_fail={flink.get('checkpoints_failed')} "
            f"pods_ready={pods.get('ready_count')}/{pods.get('total_count')} "
            f"restarts={pods.get('restart_total')}",
            flush=True,
        )

        if abort_reason:
            _create_abort(evidence_dir, abort_reason)
            print(f"result=ABORT reason={abort_reason}", flush=True)
            # Keep running through final verification / rollback until STOP_OBSERVER.
            # Do not exit; continue sampling with preserved first ABORT reason.

        # Sleep in 1s slices so STOP_OBSERVER is noticed promptly.
        wake = time.monotonic() + SAMPLE_INTERVAL_S
        while time.monotonic() < wake:
            if stop_path.exists():
                print("observer_stop reason=STOP_OBSERVER", flush=True)
                return 0
            time.sleep(1.0)


if __name__ == "__main__":
    sys.exit(main())
