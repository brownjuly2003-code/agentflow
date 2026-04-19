from __future__ import annotations

import json
import sys
from pathlib import Path


def _load_report(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _issue_key(issue: dict) -> tuple[str, str, int]:
    filename = str(issue["filename"]).replace("\\", "/")
    return (
        str(issue["test_id"]),
        filename,
        int(issue["line_number"]),
    )


def main() -> int:
    baseline_path = Path(sys.argv[1])
    current_path = Path(sys.argv[2])
    baseline = _load_report(baseline_path)
    current = _load_report(current_path)
    baseline_keys = {_issue_key(issue) for issue in baseline.get("results", [])}
    new_findings = [
        issue
        for issue in current.get("results", [])
        if _issue_key(issue) not in baseline_keys
    ]

    if new_findings:
        print(f"New bandit findings: {len(new_findings)}")
        for issue in new_findings:
            print(
                f"{issue['test_id']} {issue['filename']}:{issue['line_number']} "
                f"- {issue['issue_text']}"
            )
        return 1

    print(f"No new findings (baseline: {len(baseline.get('results', []))} issues)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
