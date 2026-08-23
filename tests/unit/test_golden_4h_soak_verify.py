"""Contract tests for golden 4h soak verifier ClickHouse pipeline counts."""

from __future__ import annotations

import importlib.util
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VERIFY_PATH = (
    PROJECT_ROOT / ".codex-grok-tasks" / "golden-4h-soak-reverify-20260802-01" / "verify.py"
)


def _load_verify():
    assert VERIFY_PATH.exists(), f"missing verifier at {VERIFY_PATH}"
    spec = importlib.util.spec_from_file_location("golden_4h_soak_verify_under_test", VERIFY_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pipeline_counts_use_validated_topic_and_separate_physical_unique(monkeypatch):
    """Canonical journal surface is topic='events.validated'; keep phys/uniq distinct."""
    module = _load_verify()
    assert hasattr(module, "count_pipeline_events"), (
        "expected testable helper count_pipeline_events for pipeline CH counts"
    )

    captured: list[str] = []

    def fake_ch_count(sql: str) -> int:
        captured.append(sql)
        # Distinct sentinels prove physical vs unique are returned separately.
        if "uniqExact(event_id)" in sql:
            return 42
        if "count()" in sql:
            return 41
        return -1

    monkeypatch.setattr(module, "_ch_count", fake_ch_count)

    prefix = "CANARY2EVT"
    physical, unique = module.count_pipeline_events(prefix)

    assert physical == 41
    assert unique == 42
    assert len(captured) == 2

    phys_sql, uniq_sql = captured
    for sql in (phys_sql, uniq_sql):
        assert f"event_id LIKE '{prefix}%'" in sql
        assert "topic = 'events.validated'" in sql
        assert "FROM pipeline_events" in sql

    assert "count()" in phys_sql
    assert "uniqExact(event_id)" not in phys_sql
    assert "uniqExact(event_id)" in uniq_sql
    assert "count()" not in uniq_sql
