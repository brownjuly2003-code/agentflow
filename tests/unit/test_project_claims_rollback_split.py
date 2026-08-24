from __future__ import annotations

import tomllib
from pathlib import Path

from scripts.check_docs_links import load_tracked_paths

ROOT = Path(__file__).resolve().parents[2]

ROLLBACK_EVIDENCE = "corrected-rollback-pair-runtime-20260823-01.md"
SOAK_CAPACITY_EVIDENCE = "ci-soak-f02-capacity-decision-20260823-01.md"
HISTORICAL_PENDING = ["4h soak and rollback rehearsal on the golden topology"]


def test_rollback_mechanics_and_soak_capacity_gates_are_split() -> None:
    manifest = tomllib.loads((ROOT / "config" / "project_claims.toml").read_text(encoding="utf-8"))
    production = manifest["production"]
    required = manifest["required_evidence"]
    tracked = load_tracked_paths(ROOT)

    assert tracked is not None
    assert production["rollback_mechanics"] == "PASS"
    assert production["rollback_mechanics_evidence"] == ROLLBACK_EVIDENCE
    assert production["full_soak_plus_rollback_after_traffic"] == "BLOCKED_HOST_CAPACITY"
    assert production["full_soak_plus_rollback_after_traffic_evidence"] == SOAK_CAPACITY_EVIDENCE
    assert ROLLBACK_EVIDENCE in required
    assert SOAK_CAPACITY_EVIDENCE in required
    assert ROLLBACK_EVIDENCE in tracked
    assert SOAK_CAPACITY_EVIDENCE in tracked
    assert production["pending_acceptance"] == HISTORICAL_PENDING
