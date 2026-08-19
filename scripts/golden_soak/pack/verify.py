#!/usr/bin/env python3
"""Exact end-to-end verifier for golden 4h canary/soak/post-rollback.

FIX4 product contract (D + C1-20):
  - canary default: kind residual-after-produce ≤ 20 s (clock from producer_end)
  - soak default: dual mean ≥ 90 (clock from producer_start; deadline = N/90)
  - golden dual-mean canary available via AGENTFLOW_RATE_CONTRACT=dual_mean_90
  - start-based applied_mean always recorded as telemetry on canary/soak

Environment:
  RUN_LABEL, SOURCE, EVENT_PREFIX, ORDER_PREFIX, EXPECTED,
  KAFKA_VERIFY_GROUP, EVIDENCE_DIR, VERIFY_PHASE (canary|soak|post-rollback),
  STOP_OBSERVER (true|false; post-rollback creates STOP only after PASS),
  FLINK_FAILED_CHECKPOINT_BASELINE (required non-negative int; no default),
  AGENTFLOW_RATE_CONTRACT (optional: kind_residual_20 | dual_mean_90),
  AGENTFLOW_RESIDUAL_AFTER_PRODUCE_S (optional float; default 20 for residual mode)

Uses compact bitset for sequence coverage — never a set of 1.44M strings.
Fail-closed on ABORT and the active rate-contract gate (canary/soak only).
Distinct evidence files per phase; post-rollback never recomputes soak mean.
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

VALID_PHASES = frozenset({"canary", "soak", "post-rollback"})
VALID_RATE_CONTRACTS = frozenset({"kind_residual_20", "dual_mean_90"})
DEFAULT_RESIDUAL_AFTER_PRODUCE_S = 20.0
DUAL_MEAN_FLOOR = 90.0


def resolve_rate_contract(phase: str, env: dict[str, str] | None = None) -> str:
    """Resolve rate contract for phase (D+C1-20 defaults)."""
    source = env if env is not None else os.environ
    raw = str(source.get("AGENTFLOW_RATE_CONTRACT", "") or "").strip().lower()
    if raw:
        if raw not in VALID_RATE_CONTRACTS:
            raise SystemExit(f"invalid_agentflow_rate_contract={raw}")
        return raw
    if phase == "canary":
        return "kind_residual_20"
    if phase == "soak":
        return "dual_mean_90"
    return "dual_mean_90"


def residual_budget_s(env: dict[str, str] | None = None) -> float:
    """Residual-after-produce budget seconds (kind canary)."""
    source = env if env is not None else os.environ
    raw = str(source.get("AGENTFLOW_RESIDUAL_AFTER_PRODUCE_S", "") or "").strip()
    if raw == "":
        return DEFAULT_RESIDUAL_AFTER_PRODUCE_S
    try:
        value = float(raw)
    except ValueError as exc:
        raise SystemExit(f"invalid_agentflow_residual_after_produce_s={raw}") from exc
    if value <= 0:
        raise SystemExit(f"non_positive_agentflow_residual_after_produce_s={value}")
    return value


def compute_catchup_deadline(
    *,
    phase: str,
    rate_contract: str,
    producer_start_epoch: float,
    producer_end_epoch: float,
    expected: int,
    now: float,
    residual_s: float = DEFAULT_RESIDUAL_AFTER_PRODUCE_S,
) -> float:
    """Return catch-up wall-clock deadline epoch for CH exactness wait."""
    if phase not in ("canary", "soak"):
        return now + 600.0
    if rate_contract == "kind_residual_20":
        return producer_end_epoch + residual_s
    # dual_mean_90: deadline dual of applied_mean >= 90 from producer_start
    return producer_start_epoch + (expected / DUAL_MEAN_FLOOR)


def evaluate_rate_gate(
    *,
    rate_contract: str,
    expected: int,
    producer_start_epoch: float,
    producer_end_epoch: float,
    catchup_pass_epoch: float,
    residual_s: float = DEFAULT_RESIDUAL_AFTER_PRODUCE_S,
) -> dict[str, Any]:
    """Evaluate rate gate; return telemetry + optional fail reason."""
    wall_from_start = catchup_pass_epoch - producer_start_epoch
    if wall_from_start <= 0:
        return {
            "ok": False,
            "reason": "catchup_before_producer_start",
            "applied_mean_eps": 0.0,
            "residual_after_produce_s": catchup_pass_epoch - producer_end_epoch,
            "applied_mean_gate": "telemetry_only"
            if rate_contract == "kind_residual_20"
            else "enforced",
        }
    applied_mean = expected / wall_from_start
    residual = catchup_pass_epoch - producer_end_epoch
    if rate_contract == "kind_residual_20":
        ok = residual <= residual_s
        return {
            "ok": ok,
            "reason": None if ok else "residual_after_produce",
            "applied_mean_eps": applied_mean,
            "residual_after_produce_s": residual,
            "residual_budget_s": residual_s,
            "applied_mean_gate": "telemetry_only",
        }
    # Tiny absolute eps absorbs IEEE inverse of N/90 wall (still fail-closed on real lag).
    ok = applied_mean + 1e-9 >= DUAL_MEAN_FLOOR
    return {
        "ok": ok,
        "reason": None if ok else "applied_mean_eps",
        "applied_mean_eps": applied_mean,
        "residual_after_produce_s": residual,
        "residual_budget_s": None,
        "applied_mean_gate": "enforced",
        "applied_mean_floor": DUAL_MEAN_FLOOR,
    }


class SeqBitset:
    """1-based sequence bitset for seq in [1, n]."""

    __slots__ = ("n", "data", "count")

    def __init__(self, n: int) -> None:
        if n < 1:
            raise ValueError("n")
        self.n = n
        self.data = bytearray((n + 7) // 8)
        self.count = 0

    def add(self, seq: int) -> str | None:
        """Return None on success, or error token on reject."""
        if seq < 1 or seq > self.n:
            return "out_of_range"
        idx = seq - 1
        byte_i = idx >> 3
        bit = 1 << (idx & 7)
        if self.data[byte_i] & bit:
            return "duplicate"
        self.data[byte_i] |= bit
        self.count += 1
        return None

    def missing_count(self) -> int:
        return self.n - self.count


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value == "":
        raise SystemExit(f"missing_env={name}")
    return value


def _parse_failed_checkpoint_baseline() -> int:
    """Required accepted cumulative failed-checkpoint baseline; no silent default."""
    raw = _env("FLINK_FAILED_CHECKPOINT_BASELINE")
    try:
        value = int(raw, 10)
    except ValueError as exc:
        raise SystemExit(f"invalid_flink_failed_checkpoint_baseline={raw}") from exc
    if value < 0:
        raise SystemExit(f"negative_flink_failed_checkpoint_baseline={value}")
    return value


def _as_int_or_sentinel(value: Any, sentinel: int = -1) -> int:
    """Convert to int; return sentinel for absent/None/bool/malformed/non-integral.

    Preserves real numeric/string zero as 0 and positive integers exactly.
    Does not silently truncate non-integral floats (e.g. 1.5 -> sentinel).
    Booleans are rejected (bool is a subclass of int in Python).
    """
    if value is None or isinstance(value, bool):
        return sentinel
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return sentinel
        if not value.is_integer():
            return sentinel
        return int(value)
    if isinstance(value, str):
        try:
            return int(value, 10)
        except ValueError:
            return sentinel
    return sentinel


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=True) + "\n"
    tmp.write_text(data, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _parse_seq(event_id: str, prefix: str) -> int | None:
    if not event_id.startswith(prefix):
        return None
    tail = event_id[len(prefix) :]
    if len(tail) != 12:
        return None
    try:
        return int(tail, 16)
    except ValueError:
        return None


def _ch_query(sql: str) -> str:
    host = _env("CLICKHOUSE_HOST")
    port = _env("CLICKHOUSE_PORT", "8123")
    db = _env("CLICKHOUSE_DATABASE", "agentflow")
    url = f"http://{host}:{port}/?database={db}"
    req = urllib.request.Request(url, data=sql.encode("utf-8"), method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8").strip()


def _ch_count(sql: str) -> int:
    body = _ch_query(sql)
    if not body:
        return 0
    return int(body.splitlines()[0].strip())


def count_pipeline_events(event_prefix: str) -> tuple[int, int]:
    """Physical and unique pipeline counts on the canonical validated journal.

    Successful order processing also writes a distinct ``{event_id}-status`` row
    on topic ``orders.status``. Count gates must only see ``events.validated``
    so expected N is not doubled, while still keeping physical vs unique separate
    for fail-closed duplicate detection within that surface.
    """
    where = (
        f"WHERE event_id LIKE '{event_prefix}%' "
        "AND topic = 'events.validated' "
        "FORMAT TabSeparated"
    )
    physical = _ch_count(f"SELECT count() FROM pipeline_events {where}")  # noqa: S608
    unique = _ch_count(f"SELECT uniqExact(event_id) FROM pipeline_events {where}")  # noqa: S608
    return physical, unique


def _http_json(url: str, headers: dict[str, str] | None = None, timeout: float = 15.0) -> Any:
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _api_get(path: str) -> tuple[int, Any]:
    base = _env("TASK_API_BASE").rstrip("/")
    key = _env("DEMO_API_KEY")
    req = urllib.request.Request(
        f"{base}{path}",
        headers={"X-API-Key": key, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body)
        except Exception:
            payload = {"raw": body[:200]}
        return exc.code, payload


def _load_producer_final(evidence_dir: Path, run_label: str) -> dict[str, Any]:
    path = evidence_dir / f"{run_label}-final.json"
    if not path.exists():
        raise SystemExit("producer_final_missing")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"producer_final_corrupt detail={type(exc).__name__}") from exc


def _load_json_required(path: Path, label: str) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"{label}_missing path={path.name}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"{label}_corrupt detail={type(exc).__name__}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"{label}_not_object")
    return data


def _kafka_scan(
    *,
    bootstrap: str,
    group: str,
    source: str,
    event_prefix: str,
    expected: int,
) -> dict[str, Any]:
    from confluent_kafka import Consumer, KafkaError, TopicPartition

    validated_bs = SeqBitset(expected)
    dlq = 0
    physical = 0
    invalid = 0
    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": group,
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
        }
    )
    try:
        md = consumer.list_topics(timeout=20)
        tps: list[Any] = []
        for topic in ("events.validated", "events.deadletter"):
            tmeta = md.topics.get(topic)
            if tmeta is None or tmeta.error is not None:
                continue
            for p in tmeta.partitions:
                low, _high = consumer.get_watermark_offsets(
                    TopicPartition(topic, p), timeout=15
                )
                tps.append(TopicPartition(topic, p, low))
        if not tps:
            return {
                "validated_physical": 0,
                "validated_unique": 0,
                "dlq": 0,
                "invalid": 0,
                "missing": expected,
                "duplicates": 0,
            }
        consumer.assign(tps)
        idle = 0
        deadline = time.time() + 600
        dup_count = 0
        while time.time() < deadline and idle < 12:
            messages = consumer.consume(num_messages=1000, timeout=1.0)
            if not messages:
                idle += 1
                continue
            idle = 0
            for msg in messages:
                if msg is None:
                    continue
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    raise RuntimeError(str(msg.error()))
                try:
                    payload = json.loads(msg.value().decode("utf-8"))
                except Exception:
                    continue
                eid = str(payload.get("event_id") or "")
                if not eid.startswith(event_prefix):
                    continue
                src = str(payload.get("source") or "")
                if msg.topic() == "events.deadletter":
                    dlq += 1
                    continue
                if msg.topic() != "events.validated":
                    continue
                physical += 1
                # Right prefix but wrong source is invalid and fails exactness.
                if src != source:
                    invalid += 1
                    continue
                seq = _parse_seq(eid, event_prefix)
                if seq is None:
                    invalid += 1
                    continue
                err = validated_bs.add(seq)
                if err == "duplicate":
                    dup_count += 1
                elif err == "out_of_range":
                    invalid += 1
        return {
            "validated_physical": physical,
            "validated_unique": validated_bs.count,
            "dlq": dlq,
            "invalid": invalid,
            "missing": validated_bs.missing_count(),
            "duplicates": dup_count,
        }
    finally:
        consumer.close()


def _iceberg_scan(*, source: str, event_prefix: str, expected: int) -> dict[str, Any]:
    from pyiceberg.expressions import EqualTo, Reference, literal

    from src.processing.iceberg_sink import IcebergSink

    config = _env("AGENTFLOW_ICEBERG_CONFIG", "/app/config/iceberg.yaml")
    sink = IcebergSink(config)
    table = sink.catalog.load_table(sink._identifier("validated_events"))
    filt = EqualTo(Reference("source"), literal(source))
    bs = SeqBitset(expected)
    physical = 0
    invalid = 0
    duplicates = 0
    scan = table.scan(row_filter=filt, selected_fields=("event_id", "source"))
    try:
        reader = scan.to_arrow_batch_reader()
        for batch in reader:
            col = batch.column(batch.schema.get_field_index("event_id"))
            for i in range(batch.num_rows):
                eid = str(col[i].as_py())
                if not eid.startswith(event_prefix):
                    # Source match but unexpected prefix — count as invalid.
                    physical += 1
                    invalid += 1
                    continue
                physical += 1
                seq = _parse_seq(eid, event_prefix)
                if seq is None:
                    invalid += 1
                    continue
                err = bs.add(seq)
                if err == "duplicate":
                    duplicates += 1
                elif err == "out_of_range":
                    invalid += 1
    except Exception:
        arrow = scan.to_arrow()
        for eid in arrow.column("event_id").to_pylist():
            eid_s = str(eid)
            if not eid_s.startswith(event_prefix):
                physical += 1
                invalid += 1
                continue
            physical += 1
            seq = _parse_seq(eid_s, event_prefix)
            if seq is None:
                invalid += 1
                continue
            err = bs.add(seq)
            if err == "duplicate":
                duplicates += 1
            elif err == "out_of_range":
                invalid += 1
    return {
        "physical": physical,
        "unique": bs.count,
        "invalid": invalid,
        "missing": bs.missing_count(),
        "duplicates": duplicates,
    }


def _kafka_group_lag(bootstrap: str, group_id: str, topic: str) -> int | None:
    """Best-effort source end lag for a consumer group."""
    try:
        from confluent_kafka import Consumer, TopicPartition
        from confluent_kafka.admin import AdminClient
    except Exception:
        return None
    try:
        admin = AdminClient({"bootstrap.servers": bootstrap})
        md = admin.list_topics(topic=topic, timeout=15)
        tmeta = md.topics.get(topic)
        if tmeta is None or tmeta.error is not None:
            return None
        consumer = Consumer(
            {
                "bootstrap.servers": bootstrap,
                "group.id": group_id,
                "enable.auto.commit": False,
            }
        )
        try:
            parts = [TopicPartition(topic, p) for p in tmeta.partitions]
            committed = consumer.committed(parts, timeout=15)
            lag = 0
            for tp in committed:
                low, high = consumer.get_watermark_offsets(
                    TopicPartition(tp.topic, tp.partition), timeout=10
                )
                offset = tp.offset
                if offset is None or offset < 0:
                    # No committed offset — lag is full high-water (from 0).
                    lag += max(high - low, 0)
                else:
                    lag += max(high - offset, 0)
            return int(lag)
        finally:
            consumer.close()
    except Exception:
        return None


def _flink_health(rest_base: str, failed_checkpoint_baseline: int) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": False}
    try:
        overview = _http_json(f"{rest_base}/jobs/overview")
        jobs = overview.get("jobs") or []
        if not jobs:
            out["error"] = "no_jobs"
            return out
        job = jobs[0]
        job_id = str(job.get("jid") or "")
        state = str(job.get("state") or "")
        tasks = job.get("tasks") or {}
        out["job_id"] = job_id
        out["state"] = state
        out["tasks_total"] = int(tasks.get("total", 0) or 0)
        out["tasks_running"] = int(tasks.get("running", 0) or 0)
        cps = _http_json(f"{rest_base}/jobs/{job_id}/checkpoints")
        counts = cps.get("counts") or {}
        out["checkpoints_completed"] = int(counts.get("completed", 0) or 0)
        out["checkpoints_failed_baseline"] = failed_checkpoint_baseline
        failed_val = _as_int_or_sentinel(counts.get("failed"))
        if failed_val < 0:
            out["error"] = "checkpoints_failed_missing_or_invalid"
            return out
        out["checkpoints_failed"] = failed_val
        out["checkpoints_failed_delta"] = (
            out["checkpoints_failed"] - failed_checkpoint_baseline
        )
        out["ok"] = (
            state == "RUNNING"
            and out["tasks_total"] > 0
            and out["tasks_running"] == out["tasks_total"]
            and out["checkpoints_completed"] > 0
            and out["checkpoints_failed_delta"] == 0
        )
        return out
    except Exception as exc:  # noqa: BLE001
        out["error"] = type(exc).__name__
        return out


def _pods_health(
    *,
    api_host: str,
    namespace: str,
    label_selector: str,
    token_path: Path,
    ca_path: Path,
) -> dict[str, Any]:
    """Require readable listing, exactly 2/2 Ready, restarts 0."""
    out: dict[str, Any] = {
        "ok": False,
        "ready": 0,
        "total": 0,
        "restarts": 0,
        "items": [],
    }
    try:
        token = token_path.read_text(encoding="utf-8").strip()
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
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        ready = 0
        restarts = 0
        items = body.get("items") or []
        items_out = []
        for item in items:
            meta = item.get("metadata") or {}
            status = item.get("status") or {}
            phase = str(status.get("phase") or "")
            cstatuses = status.get("containerStatuses") or []
            all_ready = bool(cstatuses) and all(bool(cs.get("ready")) for cs in cstatuses)
            pod_restarts = 0
            for cs in cstatuses:
                pod_restarts += int(cs.get("restartCount") or 0)
            restarts += pod_restarts
            if all_ready and phase == "Running":
                ready += 1
            items_out.append(
                {
                    "name": str(meta.get("name") or ""),
                    "phase": phase,
                    "ready": all_ready and phase == "Running",
                    "restarts": pod_restarts,
                }
            )
        out["ready"] = ready
        out["total"] = len(items)
        out["restarts"] = restarts
        out["items"] = items_out
        # Exactly 2/2 Ready, restarts 0, listing readable.
        out["ok"] = ready == 2 and len(items) == 2 and restarts == 0
        return out
    except Exception as exc:  # noqa: BLE001
        out["error"] = type(exc).__name__
        return out


def _sample_order_ids(order_prefix: str, expected: int) -> list[int]:
    """At least 20 deterministic sequences including first and last."""
    seqs = {1, expected}
    if expected >= 20:
        step = max(expected // 18, 1)
        for i in range(1, 19):
            seqs.add(min(1 + i * step, expected))
    else:
        for i in range(1, expected + 1):
            seqs.add(i)
    # Ensure >= 20 when possible.
    i = 1
    while len(seqs) < 20 and i <= expected:
        seqs.add(i)
        i += 1
    return sorted(seqs)


def _api_samples(order_prefix: str, event_prefix: str, expected: int) -> dict[str, Any]:
    ok = 0
    fail = 0
    details = []
    for seq in _sample_order_ids(order_prefix, expected):
        order_id = f"{order_prefix}{seq:07d}"
        event_id = f"{event_prefix}{seq:012x}"
        status, body = _api_get(f"/v1/entity/order/{order_id}")
        entity_ok = status == 200 and (
            body.get("entity_id") == order_id
            or str((body.get("data") or {}).get("order_id") or "") == order_id
        )
        status_t, body_t = _api_get(f"/v1/entity/order/{order_id}/timeline")
        trail = []
        if status_t == 200:
            trail = body_t.get("pipeline_trail") or body_t.get("events") or []
        matches = [item for item in trail if str(item.get("event_id")) == event_id]
        timeline_ok = len(matches) == 1
        if entity_ok and timeline_ok:
            ok += 1
        else:
            fail += 1
            if len(details) < 5:
                details.append(
                    {
                        "order_id": order_id,
                        "entity_status": status,
                        "timeline_status": status_t,
                        "timeline_matches": len(matches),
                    }
                )
    return {"ok": ok, "fail": fail, "sampled": ok + fail, "details": details}


def _check_observer_jsonl(
    evidence_dir: Path,
    producer: dict[str, Any],
    failed_checkpoint_baseline: int,
) -> dict[str, Any]:
    """Fail-closed observer evidence for full soak / post-rollback."""
    path = evidence_dir / "soak-observer.jsonl"
    if not path.exists():
        raise SystemExit("observer_jsonl_missing")
    samples: list[dict[str, Any]] = []
    try:
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                samples.append(json.loads(line))
            except Exception as exc:  # noqa: BLE001
                raise SystemExit(
                    f"observer_jsonl_corrupt line={line_no} detail={type(exc).__name__}"
                ) from exc
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"observer_jsonl_read_error detail={type(exc).__name__}") from exc

    if not samples:
        raise SystemExit("observer_jsonl_empty")

    producer_start = float(producer.get("start_epoch") or 0.0)
    producer_end = float(producer.get("end_epoch") or 0.0)
    if producer_start <= 0 or producer_end <= 0:
        raise SystemExit("observer_span_producer_epochs_missing")

    first = samples[0]
    last = samples[-1]
    first_epoch = first.get("epoch")
    last_epoch = last.get("epoch")
    if first_epoch is None or last_epoch is None:
        raise SystemExit("observer_sample_epoch_missing")
    first_epoch = float(first_epoch)
    last_epoch = float(last_epoch)

    # Span producer interval allowing at most one 60s sampling edge each side.
    if first_epoch > producer_start + 60.0:
        raise SystemExit(
            f"observer_span_late first_epoch={first_epoch} producer_start={producer_start}"
        )
    if last_epoch < producer_end - 60.0:
        raise SystemExit(
            f"observer_span_early last_epoch={last_epoch} producer_end={producer_end}"
        )

    span_s = max(last_epoch - first_epoch, 0.0)
    expected_approx = (span_s / 60.0) + 1.0
    # Approximate sample count: within 20% or ±3 samples, whichever is looser.
    tol = max(3.0, expected_approx * 0.20)
    if abs(len(samples) - expected_approx) > tol:
        raise SystemExit(
            f"observer_sample_count_mismatch got={len(samples)} "
            f"approx={expected_approx:.1f} tol={tol:.1f}"
        )

    for s in samples:
        if s.get("abort_reason"):
            raise SystemExit(f"observer_abort_in_sample sample={s.get('sample')}")
        pods = s.get("pods") or {}
        if not pods.get("ok"):
            raise SystemExit(f"observer_pods_not_ok sample={s.get('sample')}")
        if _as_int_or_sentinel(pods.get("ready_count")) != 2 or _as_int_or_sentinel(
            pods.get("total_count")
        ) != 2:
            raise SystemExit(
                f"observer_pods_not_2_2 sample={s.get('sample')} "
                f"ready={pods.get('ready_count')}/{pods.get('total_count')}"
            )
        if _as_int_or_sentinel(pods.get("restart_total")) != 0:
            raise SystemExit(
                f"observer_pod_restarts sample={s.get('sample')} "
                f"restarts={pods.get('restart_total')}"
            )
        flink = s.get("flink") or {}
        if "checkpoints_failed" not in flink or flink.get("checkpoints_failed") is None:
            raise SystemExit(
                f"observer_checkpoints_failed_missing sample={s.get('sample')}"
            )
        failed_val = _as_int_or_sentinel(flink.get("checkpoints_failed"))
        if failed_val < 0:
            raise SystemExit(
                f"observer_checkpoints_failed_invalid sample={s.get('sample')} "
                f"failed={flink.get('checkpoints_failed')}"
            )
        if failed_val != failed_checkpoint_baseline:
            raise SystemExit(
                f"observer_failed_checkpoints sample={s.get('sample')} "
                f"failed={failed_val} baseline={failed_checkpoint_baseline}"
            )

    first_cp = (first.get("flink") or {}).get("checkpoints_completed")
    last_cp = (last.get("flink") or {}).get("checkpoints_completed")
    if first_cp is None or last_cp is None:
        raise SystemExit("observer_checkpoint_counts_missing")
    if int(last_cp) <= int(first_cp):
        raise SystemExit(
            f"observer_checkpoints_not_growing first={first_cp} last={last_cp}"
        )

    return {
        "samples": len(samples),
        "first_epoch": first_epoch,
        "last_epoch": last_epoch,
        "first_cp": int(first_cp),
        "last_cp": int(last_cp),
        "span_s": round(span_s, 3),
    }


def _bind_soak_evidence_for_post_rollback(
    *,
    soak: dict[str, Any],
    run_label: str,
    source: str,
    event_prefix: str,
    order_prefix: str,
    expected: int,
) -> str | None:
    """Require immutable soak JSON to match this exact post-rollback run.

    Returns None on success, or a fail-closed reason token. Does not recompute
    applied mean — only validates stored soak PASS evidence before reuse.
    """
    if soak.get("result") != "PASS":
        return f"soak_evidence_not_pass got={soak.get('result')}"
    if soak.get("verify_phase") != "soak":
        return f"soak_evidence_phase got={soak.get('verify_phase')} expected=soak"
    if soak.get("run_label") != run_label:
        return (
            f"soak_evidence_run_label got={soak.get('run_label')} "
            f"expected={run_label}"
        )
    if soak.get("source") != source:
        return f"soak_evidence_source got={soak.get('source')} expected={source}"
    if soak.get("event_prefix") != event_prefix:
        return (
            f"soak_evidence_event_prefix got={soak.get('event_prefix')} "
            f"expected={event_prefix}"
        )
    if soak.get("order_prefix") != order_prefix:
        return (
            f"soak_evidence_order_prefix got={soak.get('order_prefix')} "
            f"expected={order_prefix}"
        )
    if _as_int_or_sentinel(soak.get("expected")) != expected:
        return (
            f"soak_evidence_expected got={soak.get('expected')} expected={expected}"
        )

    prod = soak.get("producer") or {}
    if not isinstance(prod, dict):
        return "soak_evidence_producer_not_object"
    if _as_int_or_sentinel(prod.get("delivered")) != expected:
        return (
            f"soak_evidence_producer_delivered got={prod.get('delivered')} "
            f"expected={expected}"
        )
    if _as_int_or_sentinel(prod.get("attempted")) != expected:
        return (
            f"soak_evidence_producer_attempted got={prod.get('attempted')} "
            f"expected={expected}"
        )
    if _as_int_or_sentinel(prod.get("failures")) != 0:
        return f"soak_evidence_producer_failures got={prod.get('failures')}"
    if float(prod.get("rate_eps") or 0.0) != 100.0:
        return f"soak_evidence_producer_rate_eps got={prod.get('rate_eps')}"
    if float(prod.get("elapsed_s") or 0.0) < 14_400.0:
        return (
            f"soak_evidence_producer_elapsed got={prod.get('elapsed_s')} min=14400"
        )

    kafka = soak.get("kafka") or {}
    if not isinstance(kafka, dict):
        return "soak_evidence_kafka_not_object"
    if not (
        _as_int_or_sentinel(kafka.get("validated_physical")) == expected
        and _as_int_or_sentinel(kafka.get("validated_unique")) == expected
        and _as_int_or_sentinel(kafka.get("dlq")) == 0
        and _as_int_or_sentinel(kafka.get("invalid")) == 0
        and _as_int_or_sentinel(kafka.get("missing")) == 0
        and _as_int_or_sentinel(kafka.get("duplicates")) == 0
    ):
        return (
            "soak_evidence_kafka_not_exact "
            f"physical={kafka.get('validated_physical')} "
            f"unique={kafka.get('validated_unique')} dlq={kafka.get('dlq')} "
            f"invalid={kafka.get('invalid')} missing={kafka.get('missing')} "
            f"duplicates={kafka.get('duplicates')}"
        )

    iceberg = soak.get("iceberg") or {}
    if not isinstance(iceberg, dict):
        return "soak_evidence_iceberg_not_object"
    if not (
        _as_int_or_sentinel(iceberg.get("physical")) == expected
        and _as_int_or_sentinel(iceberg.get("unique")) == expected
        and _as_int_or_sentinel(iceberg.get("invalid")) == 0
        and _as_int_or_sentinel(iceberg.get("missing")) == 0
        and _as_int_or_sentinel(iceberg.get("duplicates")) == 0
    ):
        return (
            "soak_evidence_iceberg_not_exact "
            f"physical={iceberg.get('physical')} unique={iceberg.get('unique')} "
            f"invalid={iceberg.get('invalid')} missing={iceberg.get('missing')} "
            f"duplicates={iceberg.get('duplicates')}"
        )

    ch = soak.get("clickhouse") or {}
    if not isinstance(ch, dict):
        return "soak_evidence_clickhouse_not_object"
    if not (
        _as_int_or_sentinel(ch.get("pipeline_physical")) == expected
        and _as_int_or_sentinel(ch.get("pipeline_unique")) == expected
        and _as_int_or_sentinel(ch.get("orders_physical")) == expected
        and _as_int_or_sentinel(ch.get("orders_unique")) == expected
    ):
        return (
            "soak_evidence_clickhouse_not_exact "
            f"pipeline_phys={ch.get('pipeline_physical')} "
            f"pipeline_uniq={ch.get('pipeline_unique')} "
            f"orders_phys={ch.get('orders_physical')} "
            f"orders_uniq={ch.get('orders_unique')}"
        )

    soak_applied_mean = float(soak.get("applied_mean_eps") or 0.0)
    if soak_applied_mean < 90.0:
        return (
            f"soak_applied_mean_below_floor applied_mean={soak_applied_mean}"
        )
    return None


def _assert_exact_surfaces(
    *,
    kafka: dict[str, Any],
    iceberg: dict[str, Any],
    ch_pipeline_phys: int,
    ch_pipeline_uniq: int,
    ch_orders_phys: int,
    ch_orders_uniq: int,
    expected: int,
    api: dict[str, Any],
    source_lag: int | None,
    lake_lag: int | None,
    serving_lag: int | None,
    flink: dict[str, Any],
    pods: dict[str, Any],
) -> None:
    if not (
        kafka["validated_physical"] == expected
        and kafka["validated_unique"] == expected
        and kafka["dlq"] == 0
        and kafka["invalid"] == 0
        and kafka["missing"] == 0
        and kafka["duplicates"] == 0
    ):
        raise SystemExit(
            "kafka_exactness "
            f"physical={kafka['validated_physical']} unique={kafka['validated_unique']} "
            f"dlq={kafka['dlq']} invalid={kafka['invalid']} missing={kafka['missing']} "
            f"duplicates={kafka['duplicates']}"
        )
    if not (
        iceberg["physical"] == expected
        and iceberg["unique"] == expected
        and iceberg["invalid"] == 0
        and iceberg["missing"] == 0
        and iceberg["duplicates"] == 0
    ):
        raise SystemExit(
            "iceberg_exactness "
            f"physical={iceberg['physical']} unique={iceberg['unique']} "
            f"invalid={iceberg['invalid']} missing={iceberg['missing']} "
            f"duplicates={iceberg['duplicates']}"
        )
    if not (
        ch_pipeline_phys == expected
        and ch_pipeline_uniq == expected
        and ch_orders_phys == expected
        and ch_orders_uniq == expected
    ):
        raise SystemExit(
            "clickhouse_exactness "
            f"pipeline_phys={ch_pipeline_phys} pipeline_uniq={ch_pipeline_uniq} "
            f"orders_phys={ch_orders_phys} orders_uniq={ch_orders_uniq} "
            f"expected={expected}"
        )
    if api["fail"] != 0 or (api["ok"] < 20 and expected >= 20):
        raise SystemExit(
            f"api_samples ok={api['ok']} fail={api['fail']} sampled={api['sampled']}"
        )
    if expected < 20 and api["ok"] != expected:
        raise SystemExit(f"api_samples ok={api['ok']} expected={expected}")
    if source_lag is None:
        raise SystemExit("source_lag_unknown")
    if source_lag > 100:
        raise SystemExit(f"source_lag lag={source_lag}")
    if lake_lag is None:
        raise SystemExit("lake_lag_unknown")
    if lake_lag != 0:
        raise SystemExit(f"lake_lag lag={lake_lag}")
    if serving_lag is None:
        raise SystemExit("serving_lag_unknown")
    if serving_lag != 0:
        raise SystemExit(f"serving_lag lag={serving_lag}")
    if not flink.get("ok"):
        raise SystemExit(f"flink_health flink={json.dumps(flink, separators=(',', ':'))}")
    if not pods.get("ok"):
        raise SystemExit(f"pods_health pods={json.dumps(pods, separators=(',', ':'))}")


def main() -> int:
    run_label = _env("RUN_LABEL")
    source = _env("SOURCE")
    event_prefix = _env("EVENT_PREFIX")
    order_prefix = _env("ORDER_PREFIX")
    expected = int(_env("EXPECTED"))
    group = _env("KAFKA_VERIFY_GROUP")
    evidence_dir = Path(_env("EVIDENCE_DIR"))
    phase = _env("VERIFY_PHASE")
    if phase not in VALID_PHASES:
        raise SystemExit(f"invalid_verify_phase={phase}")
    stop_observer = _env("STOP_OBSERVER", "false").lower() in ("1", "true", "yes")
    failed_checkpoint_baseline = _parse_failed_checkpoint_baseline()
    bootstrap = _env("KAFKA_BOOTSTRAP_SERVERS", "kafka.agentflow.svc.cluster.local:9092")
    flink_rest = _env(
        "FLINK_REST_BASE",
        "http://agentflow-soak-rv-stream-processor-rest:8081",
    ).rstrip("/")
    flink_group = _env("FLINK_SOURCE_GROUP", "agentflow-golden-soak-rv-20260802-01")
    lake_group = os.environ.get("LAKE_GROUP", "agentflow-lake-rv-20260802-01")
    serving_group = os.environ.get("SERVING_GROUP", "agentflow-serving-rv-20260802-01")

    abort_path = evidence_dir / "ABORT"
    if abort_path.exists():
        reason = abort_path.read_text(encoding="utf-8", errors="replace").strip()
        print(f"result=FAIL reason=ABORT detail={reason}", flush=True)
        return 1

    out_path = evidence_dir / f"{run_label}-{phase}-verify.json"

    # --- Post-rollback: load immutable soak PASS evidence first ---
    # Bind to this exact run before reusing applied mean (never recompute mean).
    soak_evidence: dict[str, Any] | None = None
    soak_applied_mean: float | None = None
    if phase == "post-rollback":
        soak_path = evidence_dir / f"{run_label}-soak-verify.json"
        soak_evidence = _load_json_required(soak_path, "soak_verify")
        bind_err = _bind_soak_evidence_for_post_rollback(
            soak=soak_evidence,
            run_label=run_label,
            source=source,
            event_prefix=event_prefix,
            order_prefix=order_prefix,
            expected=expected,
        )
        if bind_err is not None:
            print(f"result=FAIL reason={bind_err}", flush=True)
            return 1
        soak_applied_mean = float(soak_evidence.get("applied_mean_eps") or 0.0)

    producer = _load_producer_final(evidence_dir, run_label)
    if _as_int_or_sentinel(producer.get("delivered")) != expected:
        print(
            f"result=FAIL reason=producer_delivered "
            f"got={producer.get('delivered')} expected={expected}",
            flush=True,
        )
        return 1
    if _as_int_or_sentinel(producer.get("failures")) != 0:
        print(f"result=FAIL reason=producer_failures got={producer.get('failures')}", flush=True)
        return 1
    if _as_int_or_sentinel(producer.get("attempted")) != expected:
        print(
            f"result=FAIL reason=producer_attempted "
            f"got={producer.get('attempted')} expected={expected}",
            flush=True,
        )
        return 1

    rate_eps = float(producer.get("rate_eps") or 0.0)
    if rate_eps != 100.0:
        print(f"result=FAIL reason=producer_rate_eps got={rate_eps} expected=100", flush=True)
        return 1

    producer_elapsed = float(producer.get("elapsed_s") or 0.0)
    min_duration = expected / rate_eps
    if producer_elapsed < min_duration:
        print(
            f"result=FAIL reason=producer_duration_short "
            f"elapsed_s={producer_elapsed} min={min_duration}",
            flush=True,
        )
        return 1

    producer_start_epoch = float(producer.get("start_epoch") or 0.0)
    if producer_start_epoch <= 0:
        print("result=FAIL reason=producer_start_epoch_missing", flush=True)
        return 1

    producer_end_epoch = float(producer.get("end_epoch") or 0.0)
    rate_contract = "dual_mean_90"
    residual_budget = DEFAULT_RESIDUAL_AFTER_PRODUCE_S
    if phase in ("canary", "soak"):
        try:
            rate_contract = resolve_rate_contract(phase)
            if rate_contract == "kind_residual_20":
                residual_budget = residual_budget_s()
        except SystemExit as exc:
            print(f"result=FAIL reason={exc}", flush=True)
            return 1
        if rate_contract == "kind_residual_20" and producer_end_epoch <= 0:
            print("result=FAIL reason=producer_end_epoch_missing", flush=True)
            return 1
        if producer_end_epoch > 0 and producer_end_epoch < producer_start_epoch:
            print("result=FAIL reason=producer_end_before_start", flush=True)
            return 1

    # Canary/soak: bounded catch-up under active rate contract (D+C1-20).
    # Post-rollback: no mean recomputation; still allow short catch-up for exactness.
    try:
        deadline = compute_catchup_deadline(
            phase=phase,
            rate_contract=rate_contract,
            producer_start_epoch=producer_start_epoch,
            producer_end_epoch=producer_end_epoch,
            expected=expected,
            now=time.time(),
            residual_s=residual_budget,
        )
    except SystemExit as exc:
        print(f"result=FAIL reason={exc}", flush=True)
        return 1

    def remaining_ok() -> bool:
        return time.time() <= deadline + 1.0

    ch_pipeline_phys = 0
    ch_pipeline_uniq = 0
    ch_orders_phys = 0
    ch_orders_uniq = 0
    while True:
        if abort_path.exists():
            reason = abort_path.read_text(encoding="utf-8", errors="replace").strip()
            print(f"result=FAIL reason=ABORT detail={reason}", flush=True)
            return 1
        try:
            ch_pipeline_phys, ch_pipeline_uniq = count_pipeline_events(event_prefix)
            # Physical orders_v2 WITHOUT FINAL so ReplacingMergeTree dupes surface.
            ch_orders_phys = _ch_count(
                "SELECT count() FROM orders_v2 "
                f"WHERE order_id LIKE '{order_prefix}%' FORMAT TabSeparated"
            )
            ch_orders_uniq = _ch_count(
                "SELECT uniqExact(order_id) FROM orders_v2 "
                f"WHERE order_id LIKE '{order_prefix}%' FORMAT TabSeparated"
            )
        except Exception as exc:  # noqa: BLE001
            if not remaining_ok():
                print(f"result=FAIL reason=clickhouse_error detail={type(exc).__name__}", flush=True)
                return 1
            time.sleep(5)
            continue

        # Fail immediately on over-count (cannot hide RMT duplicates).
        if (
            ch_pipeline_phys > expected
            or ch_pipeline_uniq > expected
            or ch_orders_phys > expected
            or ch_orders_uniq > expected
        ):
            print(
                "result=FAIL reason=clickhouse_over_count "
                f"pipeline_phys={ch_pipeline_phys} pipeline_uniq={ch_pipeline_uniq} "
                f"orders_phys={ch_orders_phys} orders_uniq={ch_orders_uniq} "
                f"expected={expected}",
                flush=True,
            )
            return 1

        if (
            ch_pipeline_phys == expected
            and ch_pipeline_uniq == expected
            and ch_orders_phys == expected
            and ch_orders_uniq == expected
        ):
            break
        if not remaining_ok():
            if phase in ("canary", "soak") and rate_contract == "kind_residual_20":
                reason = "catchup_residual_floor"
            else:
                reason = "catchup_rate_floor"
            print(
                f"result=FAIL reason={reason} "
                f"ch_pipeline_phys={ch_pipeline_phys} ch_pipeline_uniq={ch_pipeline_uniq} "
                f"ch_orders_phys={ch_orders_phys} ch_orders_uniq={ch_orders_uniq} "
                f"expected={expected} rate_contract={rate_contract}",
                flush=True,
            )
            return 1
        time.sleep(5)

    # First exact CH catch-up moment for applied mean (canary/soak).
    catchup_pass_epoch = time.time()

    # Kafka exactness (snapshot, no commits).
    try:
        kafka = _kafka_scan(
            bootstrap=bootstrap,
            group=group,
            source=source,
            event_prefix=event_prefix,
            expected=expected,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"result=FAIL reason=kafka_error detail={type(exc).__name__}", flush=True)
        return 1

    # Iceberg (sparingly — once after CH catch-up).
    try:
        iceberg = _iceberg_scan(
            source=source, event_prefix=event_prefix, expected=expected
        )
    except Exception as exc:  # noqa: BLE001
        print(f"result=FAIL reason=iceberg_error detail={type(exc).__name__}", flush=True)
        return 1

    if not (
        iceberg["physical"] == expected
        and iceberg["unique"] == expected
        and iceberg["invalid"] == 0
        and iceberg["missing"] == 0
        and iceberg["duplicates"] == 0
    ):
        # One bounded retry if still catching up and rate budget remains.
        if remaining_ok():
            time.sleep(10)
            try:
                iceberg = _iceberg_scan(
                    source=source, event_prefix=event_prefix, expected=expected
                )
            except Exception as exc:  # noqa: BLE001
                print(
                    f"result=FAIL reason=iceberg_error detail={type(exc).__name__}",
                    flush=True,
                )
                return 1

    # API samples.
    try:
        api = _api_samples(order_prefix, event_prefix, expected)
    except Exception as exc:  # noqa: BLE001
        print(f"result=FAIL reason=api_error detail={type(exc).__name__}", flush=True)
        return 1

    # Lags must be known.
    source_lag = _kafka_group_lag(bootstrap, flink_group, "orders.raw")
    lake_lag = _kafka_group_lag(bootstrap, lake_group, "events.validated")
    serving_lag = _kafka_group_lag(bootstrap, serving_group, "events.validated")

    flink = _flink_health(flink_rest, failed_checkpoint_baseline)
    pods = _pods_health(
        api_host=_env("KUBERNETES_API", "https://kubernetes.default.svc"),
        namespace=_env("POD_NAMESPACE", "agentflow"),
        label_selector=_env(
            "FLINK_POD_SELECTOR", "app=agentflow-soak-rv-stream-processor"
        ),
        token_path=Path(
            _env("SA_TOKEN_PATH", "/var/run/secrets/kubernetes.io/serviceaccount/token")
        ),
        ca_path=Path(
            _env("SA_CA_PATH", "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")
        ),
    )

    try:
        _assert_exact_surfaces(
            kafka=kafka,
            iceberg=iceberg,
            ch_pipeline_phys=ch_pipeline_phys,
            ch_pipeline_uniq=ch_pipeline_uniq,
            ch_orders_phys=ch_orders_phys,
            ch_orders_uniq=ch_orders_uniq,
            expected=expected,
            api=api,
            source_lag=source_lag,
            lake_lag=lake_lag,
            serving_lag=serving_lag,
            flink=flink,
            pods=pods,
        )
    except SystemExit as exc:
        print(f"result=FAIL reason={exc}", flush=True)
        return 1

    delivered_eps = float(producer.get("delivered_eps") or 0.0)
    if expected >= 1_440_000:
        if producer_elapsed < 14_400.0:
            print(
                f"result=FAIL reason=soak_duration elapsed_s={producer_elapsed}",
                flush=True,
            )
            return 1
        if delivered_eps > 100.1:
            print(
                f"result=FAIL reason=delivered_eps_over_cap delivered_eps={delivered_eps}",
                flush=True,
            )
            return 1

    # Observer evidence required for full soak and post-rollback.
    observer_summary: dict[str, Any] | None = None
    if phase in ("soak", "post-rollback"):
        try:
            observer_summary = _check_observer_jsonl(
                evidence_dir, producer, failed_checkpoint_baseline
            )
        except SystemExit as exc:
            print(f"result=FAIL reason={exc}", flush=True)
            return 1

    # Rate gate: canary/soak evaluate at first exact catch-up PASS.
    # Post-rollback reuses immutable soak mean — never recompute on rollback clock.
    residual_after_produce: float | None = None
    residual_budget_out: float | None = None
    applied_mean_gate = "soak_immutable"
    if phase in ("canary", "soak"):
        gate = evaluate_rate_gate(
            rate_contract=rate_contract,
            expected=expected,
            producer_start_epoch=producer_start_epoch,
            producer_end_epoch=producer_end_epoch
            if producer_end_epoch > 0
            else producer_start_epoch,
            catchup_pass_epoch=catchup_pass_epoch,
            residual_s=residual_budget,
        )
        applied_mean = float(gate["applied_mean_eps"])
        residual_after_produce = float(gate["residual_after_produce_s"])
        residual_budget_out = gate.get("residual_budget_s")
        applied_mean_gate = str(gate["applied_mean_gate"])
        if not gate["ok"]:
            reason = gate["reason"] or "rate_gate"
            if reason == "residual_after_produce":
                print(
                    f"result=FAIL reason=residual_after_produce "
                    f"residual_s={residual_after_produce:.4f} "
                    f"budget_s={residual_budget_out} "
                    f"applied_mean_eps={applied_mean:.4f} "
                    f"rate_contract={rate_contract}",
                    flush=True,
                )
            elif reason == "applied_mean_eps":
                print(
                    f"result=FAIL reason=applied_mean_eps "
                    f"applied_mean={applied_mean:.4f} min={DUAL_MEAN_FLOOR} "
                    f"rate_contract={rate_contract}",
                    flush=True,
                )
            else:
                print(
                    f"result=FAIL reason={reason} rate_contract={rate_contract}",
                    flush=True,
                )
            return 1
        verify_pass_epoch = catchup_pass_epoch
    else:
        applied_mean = float(soak_applied_mean or 0.0)
        verify_pass_epoch = time.time()
        rate_contract = "soak_immutable"

    result: dict[str, Any] = {
        "run_label": run_label,
        "verify_phase": phase,
        "source": source,
        "event_prefix": event_prefix,
        "order_prefix": order_prefix,
        "expected": expected,
        "rate_contract": rate_contract,
        "producer": {
            "delivered": producer.get("delivered"),
            "attempted": producer.get("attempted"),
            "failures": producer.get("failures"),
            "elapsed_s": producer_elapsed,
            "delivered_eps": delivered_eps,
            "rate_eps": rate_eps,
            "start_epoch": producer_start_epoch,
            "end_epoch": producer.get("end_epoch"),
        },
        "kafka": kafka,
        "iceberg": iceberg,
        "clickhouse": {
            "pipeline_physical": ch_pipeline_phys,
            "pipeline_unique": ch_pipeline_uniq,
            "orders_physical": ch_orders_phys,
            "orders_unique": ch_orders_uniq,
            "orders_physical_uses_final": False,
        },
        "api": api,
        "lags": {
            "source_group": flink_group,
            "source_lag": source_lag,
            "lake_group": lake_group,
            "lake_lag": lake_lag,
            "serving_group": serving_group,
            "serving_lag": serving_lag,
        },
        "flink": flink,
        "pods": pods,
        "applied_mean_eps": round(applied_mean, 6),
        "applied_mean_source": (
            "soak_immutable" if phase == "post-rollback" else "catchup_pass"
        ),
        "applied_mean_gate": applied_mean_gate,
        "residual_after_produce_s": (
            None
            if residual_after_produce is None
            else round(residual_after_produce, 6)
        ),
        "residual_budget_s": residual_budget_out,
        "verify_pass_epoch": verify_pass_epoch,
        "verify_pass_utc": datetime.now(UTC).isoformat(),
        "observer": observer_summary,
        "result": "PASS",
    }
    if phase == "post-rollback" and soak_evidence is not None:
        result["soak_evidence"] = {
            "path": f"{run_label}-soak-verify.json",
            "result": soak_evidence.get("result"),
            "applied_mean_eps": soak_evidence.get("applied_mean_eps"),
            "verify_pass_epoch": soak_evidence.get("verify_pass_epoch"),
        }

    _atomic_write(out_path, result)

    # STOP_OBSERVER only after post-rollback PASS (or explicit true after PASS).
    if stop_observer:
        stop_path = evidence_dir / "STOP_OBSERVER"
        tmp = stop_path.with_suffix(".tmp")
        tmp.write_text("PASS\n", encoding="utf-8", newline="\n")
        os.replace(tmp, stop_path)

    residual_print = (
        "n/a"
        if residual_after_produce is None
        else f"{residual_after_produce:.4f}"
    )
    print(
        f"result=PASS phase={phase} run={run_label} expected={expected} "
        f"kafka_validated={kafka['validated_unique']} dlq={kafka['dlq']} "
        f"iceberg={iceberg['unique']} "
        f"ch_pipeline={ch_pipeline_uniq} ch_orders={ch_orders_uniq} "
        f"api_ok={api['ok']} applied_mean_eps={applied_mean:.4f} "
        f"residual_after_produce_s={residual_print} "
        f"rate_contract={rate_contract} "
        f"source_lag={source_lag} lake_lag={lake_lag} serving_lag={serving_lag} "
        f"duplicates=0 apply_failure=0 out={out_path.name}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit as exc:
        # Normalize bare SystemExit from helpers into FAIL lines when stringy.
        code = exc.code
        if isinstance(code, str):
            print(f"result=FAIL reason={code}", flush=True)
            sys.exit(1)
        if code is None:
            sys.exit(0)
        if isinstance(code, int):
            sys.exit(code)
        print(f"result=FAIL reason={code}", flush=True)
        sys.exit(1)
