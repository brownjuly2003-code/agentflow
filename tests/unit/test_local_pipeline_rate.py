"""_format_rate guards the --burst progress log against a zero elapsed window.

audit_28_06_26.md §5 (low): on coarse-resolution monotonic clocks the first
100-event progress tick of a burst run can have elapsed == 0.0, which raised
ZeroDivisionError in the inline ``total / elapsed`` rate string.
"""

from __future__ import annotations

from src.processing.local_pipeline import _format_rate


def test_format_rate_handles_zero_elapsed_without_zerodivision() -> None:
    # Must not raise even when 100 events report a 0.0s elapsed window.
    rate = _format_rate(100, 0.0)
    assert rate.endswith("evt/s")


def test_format_rate_computes_events_per_second() -> None:
    assert _format_rate(100, 2.0) == "50 evt/s"
