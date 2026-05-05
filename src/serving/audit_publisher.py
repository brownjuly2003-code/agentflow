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

    def publish(self, payload: Mapping[str, object]) -> None:
        with self._lock:
            previous_hash, sequence = _last_hash_and_sequence(self._path)
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
