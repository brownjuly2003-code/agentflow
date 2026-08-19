#!/usr/bin/env python3
"""Paced, delivery-ACKed Kafka producer for golden 4h canary/soak.

Environment (required):
  RUN_LABEL, SOURCE, EVENT_PREFIX, ORDER_PREFIX, COUNT, RATE_EPS,
  KAFKA_BOOTSTRAP_SERVERS, EVIDENCE_DIR

Counts only delivery-callback ACKs. Never treats produce() attempt as delivered.
Aborts immediately if <EVIDENCE_DIR>/ABORT appears.

Pacing: schedule event k (1-based) at t = start + k / RATE_EPS so N events
span at least COUNT/RATE_EPS wall seconds (never a shortened run under the
eps cap). After a successful produce of event k (attempted becomes k), the
next target is start + (k+1)/RATE_EPS — not start + k/RATE_EPS again.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Canonical OrderEvent.order_id pattern (src/ingestion/schemas/events.py).
_ORDER_ID_RE = re.compile(r"^ORD-\d{8}-\d{4,}$")
# Canonical BaseEvent.event_id pattern (UUID-shaped, 36 chars).
_EVENT_ID_RE = re.compile(r"^[a-f0-9\-]{36}$")


def _pace_target_offset(k: int, interval: float) -> float:
    """Wall offset for 1-based event k: k * interval = k / RATE_EPS."""
    if k < 1:
        raise ValueError("k_must_be_ge_1")
    if interval <= 0:
        raise ValueError("interval_must_be_positive")
    return float(k) * float(interval)


def _self_test_pacing() -> None:
    """Deterministic arithmetic: targets 1,2,N map to 1/r,2/r,N/r and increase."""
    rate = 100.0
    interval = 1.0 / rate
    n = 1_440_000
    t1 = _pace_target_offset(1, interval)
    t2 = _pace_target_offset(2, interval)
    tn = _pace_target_offset(n, interval)
    if t1 != interval:
        raise SystemExit(f"pace_self_test t1={t1} expected={interval}")
    if t2 != 2.0 * interval:
        raise SystemExit(f"pace_self_test t2={t2} expected={2.0 * interval}")
    if tn != float(n) * interval:
        raise SystemExit(f"pace_self_test tn={tn} expected={float(n) * interval}")
    if not (t1 < t2 < tn):
        raise SystemExit(f"pace_self_test not_strictly_increasing t1={t1} t2={t2} tn={tn}")
    # After successful send of event k (attempted=k), next target index is k+1:
    # start_mono + ((attempted + 1) * interval).
    for attempted in (1, 2, n - 1):
        cur = _pace_target_offset(attempted, interval)
        nxt = (attempted + 1) * interval
        if nxt <= cur:
            raise SystemExit(
                f"pace_self_test next_not_after_current attempted={attempted} "
                f"cur={cur} nxt={nxt}"
            )
        if abs(nxt - _pace_target_offset(attempted + 1, interval)) > 1e-12:
            raise SystemExit(
                f"pace_self_test next_formula attempted={attempted} nxt={nxt}"
            )


def _env(name: str) -> str:
    value = os.environ.get(name)
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


def _check_abort(evidence_dir: Path) -> None:
    abort_path = evidence_dir / "ABORT"
    if abort_path.exists():
        reason = abort_path.read_text(encoding="utf-8", errors="replace").strip()
        raise SystemExit(f"aborted reason={reason or 'ABORT_present'}")


def _build_event(
    *,
    seq: int,
    source: str,
    event_prefix: str,
    order_prefix: str,
) -> tuple[str, dict[str, Any]]:
    # UUID-shaped id: fixed 24-char prefix + 12 lowercase hex digits.
    event_id = f"{event_prefix}{seq:012x}"
    order_id = f"{order_prefix}{seq:07d}"
    user_id = f"USR-{(seq % 1000) + 1:04d}"
    unit_price = "79.99"
    quantity = 1
    total_amount = "79.99"
    # Fresh aware UTC per event — never a fixed future timestamp.
    ts = datetime.now(UTC).isoformat().replace("+00:00", "+00:00")
    event = {
        "event_id": event_id,
        "event_type": "order.created",
        "timestamp": ts,
        "source": source,
        "order_id": order_id,
        "user_id": user_id,
        "status": "confirmed",
        "items": [
            {
                "product_id": "PROD-001",
                "quantity": quantity,
                "unit_price": unit_price,
            }
        ],
        "total_amount": total_amount,
        "currency": "USD",
    }
    # tenant omitted so PyFlink stamps default
    return event_id, event


def _validate_startup(
    *,
    source: str,
    event_prefix: str,
    order_prefix: str,
    count: int,
    rate_eps: float,
) -> None:
    """Fail before produce if prefix/count combination cannot yield valid events."""
    if count < 1:
        raise SystemExit("invalid_count")
    if rate_eps <= 0:
        raise SystemExit("invalid_rate_eps")
    if len(event_prefix) + 12 != 36:
        raise SystemExit("invalid_event_prefix_len expected_total_uuid_36")
    if not source or len(source) > 64:
        raise SystemExit("invalid_source")
    if not order_prefix:
        raise SystemExit("invalid_order_prefix_empty")

    # Probe first and last sequence — both must satisfy canonical ID shapes.
    for seq in (1, count):
        event_id, event = _build_event(
            seq=seq,
            source=source,
            event_prefix=event_prefix,
            order_prefix=order_prefix,
        )
        if not _EVENT_ID_RE.match(event_id):
            raise SystemExit(f"invalid_event_id seq={seq} event_id={event_id}")
        order_id = str(event["order_id"])
        if order_id != f"{order_prefix}{seq:07d}":
            raise SystemExit(f"invalid_order_id_construction seq={seq}")
        if not _ORDER_ID_RE.match(order_id):
            raise SystemExit(
                f"invalid_order_id_schema seq={seq} order_id={order_id} "
                f"expected_pattern=^ORD-\\d{{8}}-\\d{{4,}}$"
            )
        if not order_id.startswith(order_prefix):
            raise SystemExit(f"order_id_prefix_mismatch seq={seq}")


def main() -> int:
    run_label = _env("RUN_LABEL")
    source = _env("SOURCE")
    event_prefix = _env("EVENT_PREFIX")
    order_prefix = _env("ORDER_PREFIX")
    count = int(_env("COUNT"))
    rate_eps = float(_env("RATE_EPS"))
    bootstrap = _env("KAFKA_BOOTSTRAP_SERVERS")
    evidence_dir = Path(_env("EVIDENCE_DIR"))

    _validate_startup(
        source=source,
        event_prefix=event_prefix,
        order_prefix=order_prefix,
        count=count,
        rate_eps=rate_eps,
    )

    from confluent_kafka import Producer

    evidence_dir.mkdir(parents=True, exist_ok=True)
    progress_path = evidence_dir / f"{run_label}-progress.json"
    progress_jsonl = evidence_dir / f"{run_label}-progress.jsonl"
    final_path = evidence_dir / f"{run_label}-final.json"

    topic = "orders.raw"
    delivered = 0
    failures = 0
    attempted = 0
    # Bound in-flight so memory stays low under long soaks.
    max_inflight = 500
    inflight = 0
    last_abort_check = 0.0
    last_progress_write = 0.0
    last_log = 0.0

    state: dict[str, Any] = {
        "run_label": run_label,
        "source": source,
        "event_prefix": event_prefix,
        "order_prefix": order_prefix,
        "count": count,
        "rate_eps": rate_eps,
        "topic": topic,
        "bootstrap": bootstrap,
        "attempted": 0,
        "delivered": 0,
        "failures": 0,
        "inflight": 0,
    }

    def on_delivery(err: Any, _msg: Any) -> None:
        nonlocal delivered, failures, inflight
        inflight -= 1
        if err is not None:
            failures += 1
            return
        delivered += 1

    conf = {
        "bootstrap.servers": bootstrap,
        "acks": "all",
        "enable.idempotence": True,
        "max.in.flight.requests.per.connection": 5,
        "linger.ms": 5,
        "compression.type": "lz4",
        "queue.buffering.max.messages": 100000,
    }
    producer = Producer(conf)

    start_mono = time.monotonic()
    start_epoch = time.time()
    start_utc = datetime.now(UTC).isoformat()
    state["start_utc"] = start_utc
    state["start_epoch"] = start_epoch
    state["start_mono"] = start_mono
    _atomic_write(progress_path, dict(state))
    _append_jsonl(progress_jsonl, dict(state))

    # Schedule event k at t = start + k/rate_eps (1-based) so N events span N/rate.
    # Final event N targets start + COUNT/RATE_EPS; duration/cap guards still apply.
    interval = 1.0 / rate_eps
    min_wall_s = count / rate_eps
    _self_test_pacing()
    seq = 1
    next_send = start_mono + _pace_target_offset(1, interval)

    try:
        while seq <= count:
            now = time.monotonic()
            if now - last_abort_check >= 1.0:
                _check_abort(evidence_dir)
                last_abort_check = now

            if failures > 0:
                raise SystemExit(f"delivery_failures={failures}")

            # Drain callbacks and bound queue pressure.
            while inflight >= max_inflight:
                producer.poll(0.05)
                now = time.monotonic()
                if now - last_abort_check >= 1.0:
                    _check_abort(evidence_dir)
                    last_abort_check = now
                if failures > 0:
                    raise SystemExit(f"delivery_failures={failures}")

            if now < next_send:
                sleep_for = min(next_send - now, 0.05)
                if sleep_for > 0:
                    time.sleep(sleep_for)
                producer.poll(0)
                continue

            event_id, event = _build_event(
                seq=seq,
                source=source,
                event_prefix=event_prefix,
                order_prefix=order_prefix,
            )
            payload = json.dumps(event, separators=(",", ":"), ensure_ascii=True).encode(
                "utf-8"
            )
            try:
                producer.produce(
                    topic,
                    key=event_id.encode("utf-8"),
                    value=payload,
                    on_delivery=on_delivery,
                )
            except BufferError:
                producer.poll(0.1)
                continue

            attempted += 1
            inflight += 1
            seq += 1
            # After successful send of event k (attempted==k), next target is
            # start + (k+1)/rate — never reuse the just-hit target for event k+1.
            next_send = start_mono + ((attempted + 1) * interval)
            producer.poll(0)

            now = time.monotonic()
            if now - last_progress_write >= 60.0 or attempted == 1:
                elapsed = now - start_mono
                state.update(
                    {
                        "utc": datetime.now(UTC).isoformat(),
                        "epoch": time.time(),
                        "mono": now,
                        "attempted": attempted,
                        "delivered": delivered,
                        "failures": failures,
                        "inflight": inflight,
                        "elapsed_s": round(elapsed, 3),
                        "delivered_eps": round(delivered / elapsed, 4) if elapsed > 0 else 0.0,
                    }
                )
                _atomic_write(progress_path, dict(state))
                _append_jsonl(progress_jsonl, dict(state))
                last_progress_write = now

            if now - last_log >= 60.0:
                elapsed = now - start_mono
                print(
                    f"progress run={run_label} attempted={attempted} "
                    f"delivered={delivered} failures={failures} "
                    f"inflight={inflight} elapsed_s={elapsed:.1f}",
                    flush=True,
                )
                last_log = now

        # Final flush: wait for all outstanding ACKs.
        deadline = time.monotonic() + 120.0
        while inflight > 0 and time.monotonic() < deadline:
            _check_abort(evidence_dir)
            producer.poll(0.1)
            if failures > 0:
                raise SystemExit(f"delivery_failures={failures}")

        remaining = producer.flush(60)
        # One zero-time poll after successful flush; do not add a fixed multi-
        # second callback-drain once remaining/inflight are already zero.
        producer.poll(0)
        if remaining != 0 or inflight > 0:
            raise SystemExit(
                f"flush_incomplete remaining={remaining} inflight={inflight}"
            )
        if failures > 0:
            raise SystemExit(f"delivery_failures={failures}")
        if delivered != count:
            raise SystemExit(
                f"delivered_mismatch delivered={delivered} expected={count} "
                f"attempted={attempted}"
            )
        if attempted != count:
            raise SystemExit(
                f"attempted_mismatch attempted={attempted} expected={count}"
            )

        # Never finish before the scheduled wall window (COUNT/RATE_EPS).
        # Small extra wait only if callback timing finished slightly early.
        end_mono = time.monotonic()
        elapsed = end_mono - start_mono
        if elapsed < min_wall_s:
            time.sleep(min_wall_s - elapsed)
            end_mono = time.monotonic()
            elapsed = end_mono - start_mono

        if elapsed < min_wall_s:
            raise SystemExit(
                f"duration_short elapsed_s={elapsed:.3f} required_s={min_wall_s:.3f}"
            )

        # Cap: delivered_eps must not exceed rate (tiny measurement tolerance only).
        delivered_eps = delivered / elapsed if elapsed > 0 else 0.0
        if delivered_eps > rate_eps + 0.1:
            raise SystemExit(
                f"delivered_eps_over_cap delivered_eps={delivered_eps:.6f} "
                f"cap={rate_eps}"
            )

        # Explicit soak floor (same arithmetic as min_wall for 1.44M @ 100).
        if count >= 1_440_000 and elapsed < 14_400.0:
            raise SystemExit(
                f"duration_short elapsed_s={elapsed:.3f} required_s=14400"
            )

        end_epoch = time.time()
        final = {
            "run_label": run_label,
            "source": source,
            "event_prefix": event_prefix,
            "order_prefix": order_prefix,
            "count": count,
            "rate_eps": rate_eps,
            "topic": topic,
            "bootstrap": bootstrap,
            "start_utc": start_utc,
            "end_utc": datetime.now(UTC).isoformat(),
            "start_epoch": start_epoch,
            "end_epoch": end_epoch,
            "start_mono": start_mono,
            "end_mono": end_mono,
            "elapsed_s": round(elapsed, 6),
            "attempted": attempted,
            "delivered": delivered,
            "failures": failures,
            "delivered_eps": round(delivered_eps, 6),
            "min_wall_s": min_wall_s,
            "result": "PASS",
        }
        _atomic_write(final_path, final)
        _atomic_write(progress_path, final)
        _append_jsonl(progress_jsonl, final)
        print(
            f"result=PASS run={run_label} delivered={delivered} failures={failures} "
            f"elapsed_s={elapsed:.3f} delivered_eps={final['delivered_eps']}",
            flush=True,
        )
        return 0
    except SystemExit:
        end_mono = time.monotonic()
        elapsed = end_mono - start_mono
        fail_doc = {
            "run_label": run_label,
            "source": source,
            "attempted": attempted,
            "delivered": delivered,
            "failures": failures,
            "elapsed_s": round(elapsed, 6),
            "result": "FAIL",
            "end_utc": datetime.now(UTC).isoformat(),
            "end_epoch": time.time(),
        }
        try:
            _atomic_write(progress_path, fail_doc)
            _append_jsonl(progress_jsonl, fail_doc)
        except Exception:
            pass
        raise


if __name__ == "__main__":
    sys.exit(main())
