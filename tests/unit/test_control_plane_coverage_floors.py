"""The control-plane critical-set gate (audit F-12).

A repository-wide coverage floor averages a surface that must not regress
together with hundreds of files that may. This gate holds the PostgreSQL
control-plane adapters -- the ones carrying lease and one-transaction
semantics -- to their own floors.

The tests below pin the two properties that make it a gate rather than a
report: a module below its floor fails, and a module with no coverage data at
all fails too (the usual cause is the live-PostgreSQL tests skipping for want
of a DSN, which must not read as "green").
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_control_plane_coverage import (
    CRITICAL_SET,
    REPO_ROOT,
    Breach,
    evaluate_floors,
    main,
)


def test_a_set_at_or_above_its_floors_passes() -> None:
    floors = {"a.py": 90, "b.py": 75}

    assert evaluate_floors({"a.py": 90.0, "b.py": 99.9}, floors) == []


def test_a_module_below_its_floor_is_reported_with_the_measured_value() -> None:
    breaches = evaluate_floors({"a.py": 74.5}, {"a.py": 90})

    assert breaches == [Breach(module="a.py", measured=74.5, floor=90)]
    assert "74% < 90%" in str(breaches[0])


def test_an_unmeasured_module_fails_rather_than_passing_silently() -> None:
    """The live-PostgreSQL tests skip themselves when AGENTFLOW_TEST_PG_DSN is
    absent. If that made the gate green, the gate would be strongest exactly
    when its evidence was missing."""
    breaches = evaluate_floors({"other.py": 100.0}, {"a.py": 90})

    assert [breach.module for breach in breaches] == ["a.py"]
    assert breaches[0].measured == 0.0


def test_every_module_in_the_critical_set_still_exists() -> None:
    # A renamed or split module must move the declaration with it, not leave a
    # floor pointing at nothing -- which the unmeasured rule above would then
    # report as a permanent 0%.
    missing = [module for module in CRITICAL_SET if not (REPO_ROOT / Path(module)).is_file()]

    assert missing == []


@pytest.mark.parametrize(("module", "floor"), sorted(CRITICAL_SET.items()))
def test_floors_are_meaningful_percentages(module: str, floor: int) -> None:
    # A floor of 0 is not a floor, and one above 100 can never be met.
    assert 1 <= floor <= 100, module


def test_main_reports_and_fails_on_a_breach(monkeypatch, capsys) -> None:
    module = next(iter(sorted(CRITICAL_SET)))
    monkeypatch.setattr(
        "scripts.check_control_plane_coverage.measure",
        lambda data_file=None: {module: 1.0},
    )

    exit_code = main([])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "BELOW FLOOR" in output
    assert "AGENTFLOW_TEST_PG_DSN" in output  # the likeliest cause, named


def test_main_passes_when_every_module_meets_its_floor(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "scripts.check_control_plane_coverage.measure",
        lambda data_file=None: dict.fromkeys(CRITICAL_SET, 100.0),
    )

    exit_code = main([])

    assert exit_code == 0
    assert "OK" in capsys.readouterr().out
