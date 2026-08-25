"""Per-module coverage floors for the control-plane critical set (audit F-12).

The repository-wide floor is a single number over hundreds of files, so a
surface can sit at 21% while the aggregate reads 78%. F-12 named the modules
that were hiding there; this script is the gate that keeps them out of hiding.

Two things make the numbers here different from the repository floor:

* **The critical set is risk-based, not everything.** The PostgreSQL
  control-plane adapters carry the claim semantics (leases, `SKIP LOCKED`,
  one-transaction invariants) that decide whether two replicas double-deliver
  an event or lose one. A regression there is silent in production and
  expensive; a regression in a formatter is neither.
* **Unit and live coverage are counted together.** Most branches in these
  adapters only execute against a real server, so a unit-only number measures
  the absence of a database, not the absence of tests. The measurement command
  in the module docstring below runs both into one coverage data file.

Measure and check locally -- `docs/testing-control-plane.md` carries the exact
commands and the throwaway-PostgreSQL recipe the live half needs. In short:
run the control-plane and node-ingest unit files and the control-plane/ops/
node-topology integration files under one `coverage run --append`, then this
script.

Floors sit a few points under the measured value: they are a ratchet against
regression, not a target to code to. Raise one when the real number moves up
and stays there; never lower one to make a red build green without saying why
in the commit that does it.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_PACKAGE_ROOT = REPO_ROOT / "src" / "agentflow_runtime"

# Module (repo-relative, POSIX) -> minimum line coverage percent.
# Measured 2026-08-25 with the documented commands against PostgreSQL 14.24:
# node/ingest 100, postgres_outbox_replay 99, ops 98, postgres_alert 95,
# postgres_base 93, embedded_usage_audit 91, postgres_usage_audit 87,
# reconciliation 87, postgres 82, postgres_webhook 80.
#
# All nine modules F-12 named. `serving/node/ingest.py` -- the center's
# node-federation ingest, whose bearer ladder and idempotency filter are its
# own and not the control plane's -- was the last in: the 24-30% it read at
# was the same accounting artifact as the others (the node-topology
# integration file exercised 98% of it and nothing counted that file), plus a
# unit file for the two lines it could not reach.
CRITICAL_SET: dict[str, int] = {
    "src/agentflow_runtime/serving/api/routers/ops.py": 90,
    "src/agentflow_runtime/serving/control_plane/embedded_usage_audit.py": 85,
    "src/agentflow_runtime/serving/control_plane/postgres.py": 78,
    "src/agentflow_runtime/serving/control_plane/postgres_alert.py": 90,
    "src/agentflow_runtime/serving/control_plane/postgres_base.py": 88,
    "src/agentflow_runtime/serving/control_plane/postgres_outbox_replay.py": 95,
    "src/agentflow_runtime/serving/control_plane/postgres_usage_audit.py": 82,
    "src/agentflow_runtime/serving/control_plane/postgres_webhook.py": 75,
    "src/agentflow_runtime/serving/node/ingest.py": 95,
    "src/agentflow_runtime/serving/semantic_layer/reconciliation.py": 80,
}


@dataclass(frozen=True)
class Breach:
    """One module below its floor."""

    module: str
    measured: float
    floor: int

    def __str__(self) -> str:
        return f"{self.module}: {self.measured:.0f}% < {self.floor}% floor"


def evaluate_floors(measured: dict[str, float], floors: dict[str, int]) -> list[Breach]:
    """Modules that are below their floor, or that were not measured at all.

    An unmeasured module is a breach reported as 0%, deliberately: the usual
    reason a critical module has no coverage data is that the live-PostgreSQL
    tests skipped themselves for want of a DSN, and a gate that stays green
    when its evidence is missing is not a gate.
    """
    breaches = [
        Breach(module=module, measured=measured.get(module, 0.0), floor=floor)
        for module, floor in sorted(floors.items())
        if measured.get(module, 0.0) < floor
    ]
    return breaches


def measure(data_file: str | None = None) -> dict[str, float]:
    """Per-module line coverage from an existing coverage data file."""
    from coverage import Coverage

    coverage = Coverage(data_file=data_file) if data_file else Coverage()
    coverage.load()
    measured: dict[str, float] = {}
    for filename in coverage.get_data().measured_files():
        path = Path(filename)
        try:
            relative = path.resolve().relative_to(REPO_ROOT).as_posix()
        except ValueError:
            continue  # site-packages and other out-of-tree files
        _, statements, _, missing, _ = coverage.analysis2(filename)
        if not statements:
            continue
        measured[relative] = 100.0 * (len(statements) - len(missing)) / len(statements)
    return measured


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-file",
        default=None,
        help="coverage data file to read (default: coverage's own resolution)",
    )
    args = parser.parse_args(argv)

    measured = measure(args.data_file)
    for module, floor in sorted(CRITICAL_SET.items()):
        value = measured.get(module)
        shown = f"{value:5.1f}%" if value is not None else "   --  "
        print(f"{shown}  (floor {floor:3d}%)  {module}")

    breaches = evaluate_floors(measured, CRITICAL_SET)
    if not breaches:
        print(f"control-plane critical set: OK ({len(CRITICAL_SET)} modules)")
        return 0
    print("\ncontrol-plane critical set: BELOW FLOOR")
    for breach in breaches:
        print(f"  {breach}")
    print(
        "\nIf a module reads 0%, the live PostgreSQL tests probably skipped: "
        "AGENTFLOW_TEST_PG_DSN must point at a reachable server."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
