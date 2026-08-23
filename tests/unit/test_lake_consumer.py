from __future__ import annotations

import json

from agentflow_runtime.processing.lake_consumer import ValidatedLakeConsumer


class _Message:
    def __init__(self, event: dict, *, offset: int = 0) -> None:
        self._value = json.dumps(event).encode()
        self._offset = offset

    def value(self) -> bytes:
        return self._value

    def topic(self) -> str:
        return "events.validated"

    def partition(self) -> int:
        return 0

    def offset(self) -> int:
        return self._offset

    def error(self):
        return None


class _Consumer:
    def __init__(self, batches) -> None:
        self.batches = list(batches)
        self.commits = 0
        self.seeks = []

    def consume(self, *, num_messages: int, timeout: float):
        return self.batches.pop(0) if self.batches else []

    def commit(self, *, asynchronous: bool) -> None:
        self.commits += 1

    def seek(self, position) -> None:
        self.seeks.append((position.topic, position.partition, position.offset))


class _Sink:
    def __init__(self, *, fail: bool = False) -> None:
        self.identities: set[tuple[str, str]] = set()
        self.rows: list[dict] = []
        self.fail = fail

    def existing_event_identities(
        self,
        table_name: str,
        identities: list[tuple[str, str]],
    ) -> set[tuple[str, str]]:
        assert table_name == "validated_events"
        return self.identities.intersection(identities)

    def write_batch(self, table_name: str, records: list[dict]) -> int:
        assert table_name == "validated_events"
        if self.fail:
            raise RuntimeError("catalog unavailable")
        self.rows.extend(records)
        self.identities.update(
            (str(record["tenant"]), str(record["event_id"])) for record in records
        )
        return len(records)


def _event(event_id: str, tenant: str) -> dict:
    return {
        "event_id": event_id,
        "event_type": "order.created",
        "tenant": tenant,
        "timestamp": "2026-07-23T12:00:00+00:00",
        "source": "unit",
    }


def test_replay_is_deduplicated_before_append() -> None:
    event = _event("evt-1", "acme")
    consumer = _Consumer([[_Message(event, offset=4)], [_Message(event, offset=4)]])
    sink = _Sink()
    materializer = ValidatedLakeConsumer(consumer, sink=sink, retry_backoff_seconds=0)

    first = materializer.run_once()
    replay = materializer.run_once()

    assert (first.appended, first.duplicates) == (1, 0)
    assert (replay.appended, replay.duplicates) == (0, 1)
    assert [row["event_id"] for row in sink.rows] == ["evt-1"]
    assert consumer.commits == 2


def test_two_tenants_keep_same_business_identity_as_distinct_lake_rows() -> None:
    events = [_event("evt-shared", "acme"), _event("evt-shared", "demo")]
    for event in events:
        event["entity_type"] = "order"
        event["entity_id"] = "ORD-SHARED"
    consumer = _Consumer([[_Message(event, offset=index) for index, event in enumerate(events)]])
    sink = _Sink()
    materializer = ValidatedLakeConsumer(consumer, sink=sink, retry_backoff_seconds=0)

    result = materializer.run_once()

    assert result.appended == 2
    assert {(row["tenant"], row["entity_id"]) for row in sink.rows} == {
        ("acme", "ORD-SHARED"),
        ("demo", "ORD-SHARED"),
    }


def test_catalog_failure_does_not_commit_offsets(monkeypatch) -> None:
    consumer = _Consumer([[_Message(_event("evt-1", "acme"), offset=7)]])
    sink = _Sink(fail=True)
    materializer = ValidatedLakeConsumer(consumer, sink=sink, retry_backoff_seconds=0)

    class _TopicPartition:
        def __init__(self, topic: str, partition: int, offset: int) -> None:
            self.topic = topic
            self.partition = partition
            self.offset = offset

    monkeypatch.setattr("confluent_kafka.TopicPartition", _TopicPartition)

    assert materializer.run_once() is None
    assert consumer.commits == 0
    assert consumer.seeks == [("events.validated", 0, 7)]
