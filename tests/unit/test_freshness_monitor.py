"""Unit tests for the FreshnessMonitor.

Closes the 0% coverage gap on `src/quality/monitors/freshness_monitor.py`
flagged in Codex audit p5. We mock confluent_kafka.Consumer and the message
shape so we can exercise `_process_message` paths without a live broker.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.quality.monitors import freshness_monitor as fm_module
from src.quality.monitors.freshness_monitor import FreshnessMonitor


def _make_msg(value: bytes, topic: str = "events.validated", partition: int = 0, offset: int = 0):
    msg = MagicMock()
    msg.value.return_value = value
    msg.topic.return_value = topic
    msg.partition.return_value = partition
    msg.offset.return_value = offset
    return msg


@pytest.fixture
def monitor():
    with patch.object(fm_module, "Consumer", return_value=MagicMock()):
        return FreshnessMonitor(
            bootstrap_servers="localhost:9092",
            topics=["events.validated"],
        )


def test_process_message_records_latency_and_marks_sla_ok(monitor):
    fresh_ts = datetime.now(UTC).isoformat()
    payload = json.dumps(
        {"event_id": "ev-1", "event_type": "order.created", "timestamp": fresh_ts}
    ).encode()
    msg = _make_msg(payload)

    with patch.object(fm_module.PIPELINE_LATENCY, "labels") as latency_labels, patch.object(
        fm_module.EVENTS_PROCESSED, "labels"
    ) as count_labels, patch.object(fm_module.SLA_COMPLIANCE, "labels") as sla_labels:
        latency_label = MagicMock()
        latency_labels.return_value = latency_label
        count_label = MagicMock()
        count_labels.return_value = count_label
        sla_label = MagicMock()
        sla_labels.return_value = sla_label

        monitor._process_message(msg)

        latency_labels.assert_called_once_with(topic="events.validated", event_type="order.created")
        latency_label.observe.assert_called_once()
        count_label.inc.assert_called_once()
        sla_label.set.assert_called_once_with(1.0)


def test_process_message_marks_breach_when_event_is_old(monitor):
    stale_ts = (datetime.now(UTC) - timedelta(seconds=120)).isoformat()
    payload = json.dumps(
        {"event_id": "ev-2", "event_type": "order.created", "timestamp": stale_ts}
    ).encode()
    msg = _make_msg(payload)

    with patch.object(fm_module, "logger") as logger:
        monitor._process_message(msg)

    # Breach should produce an explicit warning event
    assert any(call.args and call.args[0] == "sla_breach" for call in logger.warning.call_args_list)


def test_process_message_skips_invalid_json(monitor):
    msg = _make_msg(b"\xff\xfenot-json")

    with patch.object(fm_module, "logger") as logger:
        monitor._process_message(msg)

    skip_calls = [c for c in logger.warning.call_args_list if c.args and c.args[0] == "freshness_message_skipped"]
    assert skip_calls, "expected freshness_message_skipped warning on invalid payload"
    assert skip_calls[0].kwargs.get("reason") == "invalid_payload"


def test_process_message_skips_missing_timestamp(monitor):
    payload = json.dumps({"event_id": "ev-3", "event_type": "order.created"}).encode()
    msg = _make_msg(payload)

    with patch.object(fm_module, "logger") as logger:
        monitor._process_message(msg)

    reason = next(
        (c.kwargs.get("reason") for c in logger.warning.call_args_list if c.args and c.args[0] == "freshness_message_skipped"),
        None,
    )
    assert reason == "missing_timestamp"


def test_process_message_skips_invalid_timestamp(monitor):
    payload = json.dumps(
        {"event_id": "ev-4", "event_type": "order.created", "timestamp": "not-a-date"}
    ).encode()
    msg = _make_msg(payload)

    with patch.object(fm_module, "logger") as logger:
        monitor._process_message(msg)

    reason = next(
        (c.kwargs.get("reason") for c in logger.warning.call_args_list if c.args and c.args[0] == "freshness_message_skipped"),
        None,
    )
    assert reason == "invalid_timestamp"


def test_sla_window_is_capped_to_configured_size(monitor):
    monitor._window_size = 5
    fresh_ts = datetime.now(UTC).isoformat()
    payload = json.dumps(
        {"event_id": "ev-cap", "event_type": "order.created", "timestamp": fresh_ts}
    ).encode()

    for i in range(7):
        monitor._process_message(_make_msg(payload, offset=i))

    assert len(monitor._sla_window["events.validated"]) == 5


def test_naive_timestamp_is_treated_as_utc(monitor):
    naive_now = datetime.now(UTC).replace(tzinfo=None).isoformat()
    payload = json.dumps(
        {"event_id": "ev-naive", "event_type": "order.created", "timestamp": naive_now}
    ).encode()
    msg = _make_msg(payload)

    # Should not raise and should record the latency observation
    with patch.object(fm_module.PIPELINE_LATENCY, "labels") as latency_labels:
        latency_labels.return_value = MagicMock()
        monitor._process_message(msg)
        assert latency_labels.called


def test_start_handles_partition_eof_and_real_kafka_errors(monitor):
    # Three poll() yields: real error → ignored EOF → KeyboardInterrupt to exit.
    eof_code = fm_module.KafkaError._PARTITION_EOF
    real_err = SimpleNamespace(code=lambda: -999)  # any code that is not _PARTITION_EOF
    eof_err = SimpleNamespace(code=lambda: eof_code)
    err_msg = MagicMock()
    err_msg.error.return_value = real_err
    eof_msg = MagicMock()
    eof_msg.error.return_value = eof_err

    consumer = monitor.consumer
    consumer.poll.side_effect = [err_msg, eof_msg, KeyboardInterrupt()]

    with patch.object(fm_module, "start_http_server"), patch.object(
        fm_module, "logger"
    ) as logger:
        monitor.start(metrics_port=18001)

    # Real error logged once; EOF must NOT log a kafka_error.
    kafka_error_calls = [c for c in logger.error.call_args_list if c.args and c.args[0] == "kafka_error"]
    assert len(kafka_error_calls) == 1
    consumer.close.assert_called_once()
