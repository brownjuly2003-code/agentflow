#!/usr/bin/env python3
"""Pre-start the verifier and delegate only after producer evidence is stable."""

from __future__ import annotations

import math
import os
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path

DEFAULT_PRODUCER_WAIT_S = 15_000.0
POLL_S = 0.2
_RUN_LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


def _required_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"missing_env={name}")
    return value


def _producer_wait_seconds() -> float:
    raw = os.environ.get("PRODUCER_FINAL_WAIT_SECONDS", "")
    if not raw:
        return DEFAULT_PRODUCER_WAIT_S
    try:
        value = float(raw)
    except ValueError as exc:
        raise SystemExit(f"invalid_producer_final_wait_seconds={raw}") from exc
    if not math.isfinite(value) or value <= 0:
        raise SystemExit(f"non_positive_producer_final_wait_seconds={raw}")
    return value


def wait_for_producer_final(
    evidence_dir: Path,
    run_label: str,
    timeout_s: float,
    *,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Path:
    """Wait fail-closed for one stable producer-final file or an abort marker."""
    if not evidence_dir.is_dir() or evidence_dir.is_symlink():
        raise SystemExit(f"evidence_dir_invalid={evidence_dir}")
    if not _RUN_LABEL_RE.fullmatch(run_label):
        raise SystemExit(f"run_label_invalid={run_label}")
    if not math.isfinite(timeout_s) or timeout_s <= 0:
        raise SystemExit(f"producer_final_wait_invalid={timeout_s}")

    final_path = evidence_dir / f"{run_label}-final.json"
    abort_path = evidence_dir / "ABORT"
    deadline = monotonic() + timeout_s
    print(
        f"verifier_wait_start final={final_path.name} timeout_s={timeout_s}",
        flush=True,
    )
    while True:
        if abort_path.is_file():
            detail = abort_path.read_text(encoding="utf-8", errors="replace").strip()
            raise SystemExit(f"ABORT detail={detail}")
        try:
            first = final_path.stat()
        except OSError:
            first = None
        if first is not None and first.st_size > 0 and not final_path.is_symlink():
            sleep(POLL_S)
            try:
                second = final_path.stat()
            except OSError:
                second = None
            if (
                second is not None
                and second.st_size == first.st_size
                and second.st_mtime_ns == first.st_mtime_ns
            ):
                print(
                    f"verifier_wait_done final={final_path.name} bytes={first.st_size}",
                    flush=True,
                )
                return final_path
        if monotonic() >= deadline:
            raise SystemExit(
                f"producer_final_wait_timeout path={final_path.name} timeout_s={timeout_s}"
            )
        sleep(POLL_S)


def main() -> int:
    run_label = _required_env("RUN_LABEL")
    evidence_dir = Path(_required_env("EVIDENCE_DIR"))
    verify_path = Path("/golden-pack/pack/verify.py")
    if not verify_path.is_file() or verify_path.is_symlink():
        raise SystemExit(f"verify_script_invalid={verify_path}")

    wait_for_producer_final(
        evidence_dir,
        run_label,
        _producer_wait_seconds(),
    )
    # Both paths are fixed and validated; no shell or user command is involved.
    os.execv(sys.executable, [sys.executable, str(verify_path)])  # noqa: S606
    return 127  # pragma: no cover - os.execv replaces this process


if __name__ == "__main__":
    raise SystemExit(main())
