from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

from scripts import profile_entity

ROOT = Path(__file__).resolve().parents[2]


def test_parse_args_defaults_to_ignored_runtime_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "profile_entity.py",
            "--entity-type",
            "order",
            "--entity-id",
            "ORD-20260404-1001",
        ],
    )

    args = profile_entity.parse_args()

    assert args.output == profile_entity.DEFAULT_OUTPUT_PATH
    assert args.output == ROOT / ".artifacts" / "perf-smoke" / "entity-profile.json"
    assert ".artifacts/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_relative_output_resolves_from_project_root() -> None:
    assert (
        profile_entity.resolve_output_path(".artifacts/perf-smoke/custom.json")
        == ROOT / ".artifacts" / "perf-smoke" / "custom.json"
    )


@pytest.mark.parametrize(
    "output_path",
    [
        "docs/perf/ci-smoke-latest.json",
        "docs/perf/entity-latency-new.json",
        ROOT / "docs" / "perf" / "entity-latency-baseline-2026-04-24.json",
    ],
)
def test_profile_refuses_documentation_output(output_path: str | Path) -> None:
    with pytest.raises(ValueError, match=r"\.artifacts/perf-smoke"):
        profile_entity.resolve_output_path(output_path)


def test_main_rejects_docs_output_before_http(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        profile_entity,
        "parse_args",
        lambda: argparse.Namespace(output=Path("docs/perf/entity-latency-new.json")),
    )

    async def fail_before_http(_args: argparse.Namespace) -> dict[str, object]:
        pytest.fail("HTTP benchmark must not start for protected documentation output")

    monkeypatch.setattr(profile_entity, "run", fail_before_http)

    assert profile_entity.main() == 2
    assert ".artifacts/perf-smoke" in capsys.readouterr().err


def test_main_creates_runtime_parent_and_writes_lf_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "nested" / "entity-profile.json"
    monkeypatch.setattr(
        profile_entity,
        "parse_args",
        lambda: argparse.Namespace(output=output_path),
    )

    async def fake_run(_args: argparse.Namespace) -> dict[str, object]:
        return {"p99_ms": 123.4, "success_count": 10}

    monkeypatch.setattr(profile_entity, "run", fake_run)

    assert profile_entity.main() == 0
    assert json.loads(output_path.read_text(encoding="utf-8")) == {
        "p99_ms": 123.4,
        "success_count": 10,
    }
    assert b"\r" not in output_path.read_bytes()


def test_entity_profile_docs_name_runtime_owner_and_promotion_boundary() -> None:
    contract = " ".join(
        (ROOT / "docs" / "perf" / "entity-benchmark-contract.md")
        .read_text(encoding="utf-8")
        .split()
    )
    perf_hub = " ".join((ROOT / "docs" / "perf" / "README.md").read_text(encoding="utf-8").split())
    docs_hub = " ".join((ROOT / "docs" / "README.md").read_text(encoding="utf-8").split())
    decision = " ".join(
        (ROOT / "docs" / "perf" / "benchmark-split-decision.md").read_text(encoding="utf-8").split()
    )
    contributing = " ".join((ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8").split())
    evidence_index = " ".join(
        (ROOT / "docs" / "evidence" / "INDEX.md").read_text(encoding="utf-8").split()
    )
    plan = " ".join((ROOT / "plan_26_08_2026.md").read_text(encoding="utf-8").split())

    for current_doc in (contract, perf_hub, docs_hub, contributing, evidence_index):
        assert ".artifacts/perf-smoke/entity-profile.json" in current_doc
    assert "docs/perf/ci-smoke-latest.json" in decision
    assert ".artifacts/perf-smoke/entity-profile.json" in decision
    assert "date-stamped" in contract
    assert "Entity perf-smoke runtime artifact sub-slice" in plan
    assert "Пункт 6 остаётся открыт" in plan
