"""Append a benchmark run to .github/perf-history.json.

Consumes the aggregate block of `results.json` produced by
`tests/load/run_load_test.py` (or `scripts/run_benchmark.py`) and
records one trend entry per invocation. History is kept append-only
with a rolling cap so the file stays small.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HISTORY_PATH = PROJECT_ROOT / ".github" / "perf-history.json"
DEFAULT_RESULTS_PATH = PROJECT_ROOT / ".artifacts" / "load" / "results.json"
DEFAULT_MAX_ENTRIES = 500


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results",
        type=Path,
        default=DEFAULT_RESULTS_PATH,
        help="Path to the benchmark results.json to ingest.",
    )
    parser.add_argument(
        "--history",
        type=Path,
        default=DEFAULT_HISTORY_PATH,
        help="Path to the rolling perf history file.",
    )
    parser.add_argument(
        "--commit-sha",
        default=os.environ.get("GITHUB_SHA", ""),
        help="Commit SHA to attach to the entry (defaults to $GITHUB_SHA).",
    )
    parser.add_argument(
        "--branch",
        default=os.environ.get("GITHUB_REF_NAME", "main"),
        help="Branch name to attach to the entry (defaults to $GITHUB_REF_NAME).",
    )
    parser.add_argument(
        "--max-entries",
        type=int,
        default=DEFAULT_MAX_ENTRIES,
        help="Maximum number of entries retained in the history file.",
    )
    return parser.parse_args()


def load_history(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit(f"Expected a list in {path}, got {type(data).__name__}.")
    return data


def build_entry(results_path: Path, commit_sha: str, branch: str) -> dict[str, object]:
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    aggregate = payload.get("aggregate")
    if not isinstance(aggregate, dict):
        raise SystemExit(f"Missing 'aggregate' block in {results_path}.")

    return {
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit_sha": (commit_sha or "")[:7],
        "branch": branch,
        "p50_ms": float(aggregate.get("p50_ms", 0.0)),
        "p95_ms": float(aggregate.get("p95_ms", 0.0)),
        "p99_ms": float(aggregate.get("p99_ms", 0.0)),
        "throughput_rps": float(aggregate.get("requests_per_second", 0.0)),
    }


def main() -> int:
    args = parse_args()
    history = load_history(args.history)
    entry = build_entry(args.results, args.commit_sha, args.branch)
    history.append(entry)
    if args.max_entries > 0 and len(history) > args.max_entries:
        history = history[-args.max_entries :]

    args.history.parent.mkdir(parents=True, exist_ok=True)
    args.history.write_text(
        json.dumps(history, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Recorded benchmark entry for {entry['commit_sha']} (history size: {len(history)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
