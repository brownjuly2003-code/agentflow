"""Decide whether a chaos pytest run failed or merely crashed during teardown.

The chaos lanes intermittently die with SIGABRT (``terminate called without an
active exception``) *after* the pytest session has finished and the JSON report
is on disk — a native-library thread being torn down at interpreter exit, not a
scenario regression (observed 2026-06-18, 2026-06-26, 2026-07-01; every log
shows the full ``N passed`` summary before the abort). This guard keeps the
lane honest: the workflow re-checks the machine-written JSON report and
tolerates the crash only when the session itself was green.

Tolerated (exit 0, with a loud warning): the pytest process died from a signal
(shell exit code > 128) AND the JSON report exists, recorded ``exitcode: 0``,
collected at least one test, and counted zero failures/errors. The report is
written at session end, so a crash mid-run leaves either no report or a red one.

Anything else — a real test failure, a collection error, an interrupted run —
propagates the original pytest exit code unchanged.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def evaluate(pytest_exit_code: int, report_path: Path) -> tuple[int, str]:
    """Return (final_exit_code, human_readable_reason)."""
    if pytest_exit_code == 0:
        return 0, "pytest exited cleanly"

    if pytest_exit_code <= 128:
        return (
            pytest_exit_code,
            f"pytest exit code {pytest_exit_code} is a pytest verdict, not a signal death",
        )

    if not report_path.exists():
        return (
            pytest_exit_code,
            f"no JSON report at {report_path} — the session did not finish",
        )

    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return pytest_exit_code, f"JSON report unreadable ({exc}) — treating as a real failure"

    session_exit = report.get("exitcode")
    summary = report.get("summary", {})
    collected = int(summary.get("total", 0) or 0)
    failed = int(summary.get("failed", 0) or 0)
    errors = int(summary.get("error", 0) or 0)

    if session_exit == 0 and collected > 0 and failed == 0 and errors == 0:
        return 0, (
            f"session was green ({collected} collected, 0 failed) but the process died "
            f"with exit code {pytest_exit_code} after the report was written — "
            "known native-library teardown abort at interpreter exit, tolerating"
        )

    return pytest_exit_code, (
        f"JSON report is not green (exitcode={session_exit}, failed={failed}, "
        f"errors={errors}, collected={collected})"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True, help="pytest-json-report file")
    parser.add_argument(
        "--pytest-exit-code",
        type=int,
        required=True,
        help="exit code the pytest process finished with",
    )
    args = parser.parse_args(argv)

    code, reason = evaluate(args.pytest_exit_code, args.report)
    stream = sys.stderr if code != 0 else sys.stdout
    prefix = "chaos-teardown-guard:"
    if code == 0 and args.pytest_exit_code != 0:
        print(f"::warning title=Chaos teardown abort tolerated::{reason}")
    print(f"{prefix} {reason}", file=stream)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
