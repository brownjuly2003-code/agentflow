from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

AUDIT_LOG_PATH_ENV = "AGENTFLOW_AUDIT_LOG_PATH"


class AuditPublisher(Protocol):
    def publish(self, payload: Mapping[str, object]) -> None: ...


class NoopAuditPublisher:
    def publish(self, payload: Mapping[str, object]) -> None:
        del payload


class HashChainedFileAuditPublisher:
    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._cached_hash: str | None = None
        self._cached_sequence: int | None = None  # None until the tail is read once

    def publish(self, payload: Mapping[str, object]) -> None:
        with self._lock:
            if self._cached_sequence is None:
                # Read the tail once per process to resume the chain. Subsequent
                # writes use the in-memory head — this is the only writer and the
                # log is append-only under the lock — instead of re-reading the
                # whole growing file every call, which was O(file) per request
                # and O(n^2) over the log's lifetime. (audit_28_06_26.md #14)
                self._cached_hash, self._cached_sequence = _last_hash_and_sequence(self._path)
            previous_hash = self._cached_hash
            sequence = self._cached_sequence
            record: dict[str, object] = {
                "sequence": sequence + 1,
                "previous_hash": previous_hash,
                "payload": dict(payload),
            }
            record["hash"] = _hash_record(record)
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(record, sort_keys=True, default=str))
                handle.write("\n")
            self._cached_hash = str(record["hash"])
            self._cached_sequence = sequence + 1


def build_audit_publisher_from_env() -> AuditPublisher:
    path = os.getenv(AUDIT_LOG_PATH_ENV)
    if path is None or not path.strip():
        return NoopAuditPublisher()
    return HashChainedFileAuditPublisher(path)


def verify_hash_chain(path: Path | str) -> bool:
    previous_hash: str | None = None
    expected_sequence = 1
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        current_hash = record.get("hash")
        if record.get("sequence") != expected_sequence:
            return False
        if record.get("previous_hash") != previous_hash:
            return False
        if current_hash != _hash_record(record):
            return False
        previous_hash = current_hash
        expected_sequence += 1
    return True


def _last_hash_and_sequence(path: Path) -> tuple[str | None, int]:
    if not path.exists():
        return None, 0
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        return None, 0
    record = json.loads(lines[-1])
    return record["hash"], int(record["sequence"])


def _hash_record(record: Mapping[str, object]) -> str:
    unsigned = {key: value for key, value in record.items() if key != "hash"}
    canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
