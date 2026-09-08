"""CLI: run the NL->SQL execution-accuracy eval and write a runtime report.

    python -m scripts.run_nl_sql_eval
    python -m scripts.run_nl_sql_eval --md .artifacts/nl-sql-eval/candidate.md

Measures whatever `translate_nl_to_sql` is configured to do: rule-based by
default, or the GraceKelly/Sonnet-5 LLM path when GRACEKELLY_URL is set. See
ADR 0008 and docs/perf/nl-sql-eval-*.md.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# F-09: invoked as `python scripts/<name>.py`, so the repository root must
# be on sys.path for the `scripts.*` package import below.
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = REPO_ROOT / ".artifacts" / "nl-sql-eval" / "current.md"
PERFORMANCE_EVIDENCE_ROOT = REPO_ROOT / "docs" / "perf"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.nl_sql_eval import EvalReport, run_eval


def _engine_label() -> str:
    return "gracekelly-llm" if os.getenv("GRACEKELLY_URL") else "rule-based"


def _render_markdown(report: EvalReport, engine: str) -> str:
    lines = [
        "# NL->SQL execution-accuracy eval",
        "",
        "> Runtime artifact: re-running replaces `.artifacts/nl-sql-eval/current.md`.",
        "> This direct-translator result on the curated demo set is not a production benchmark,",
        "> an SLA, served `/query` acceptance, or production acceptance. Promote only under",
        "> a new date-stamped evidence identity with source, host/runtime, engine/model,",
        "> exact command/configuration, and report-hash provenance.",
        "",
        f"- Engine: `{engine}`",
        f"- Overall EA: **{report.ea:.1%}** ({report.matched}/{report.total})",
    ]
    for category in report.categories():
        subset = [r for r in report.results if r.category == category]
        hit = sum(1 for r in subset if r.match)
        lines.append(f"- {category}: {report.ea_for(category):.1%} ({hit}/{len(subset)})")
    lines += ["", "| id | category | match | reason |", "|---|---|---|---|"]
    for r in report.results:
        mark = "PASS" if r.match else "FAIL"
        reason = r.reason.replace("|", "\\|")
        lines.append(f"| {r.id} | {r.category} | {mark} | {reason} |")
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NL->SQL execution-accuracy eval")
    parser.add_argument(
        "--md",
        type=Path,
        default=DEFAULT_REPORT,
        help="Write the runtime Markdown report to this path",
    )
    return parser.parse_args()


def resolve_report_path(report_path: Path) -> Path:
    resolved = report_path if report_path.is_absolute() else REPO_ROOT / report_path
    if resolved.resolve().is_relative_to(PERFORMANCE_EVIDENCE_ROOT.resolve()):
        raise ValueError(
            "Tracked performance evidence under docs/perf cannot be overwritten; "
            "write runtime artifacts under .artifacts/nl-sql-eval/ instead."
        )
    return resolved


def main() -> int:
    args = parse_args()
    try:
        report_path = resolve_report_path(args.md)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    engine = _engine_label()
    report = run_eval()

    print(f"Engine: {engine}")
    print(f"Overall EA: {report.ea:.1%} ({report.matched}/{report.total})")
    for category in report.categories():
        subset = [r for r in report.results if r.category == category]
        hit = sum(1 for r in subset if r.match)
        print(f"  {category}: {report.ea_for(category):.1%} ({hit}/{len(subset)})")
    print()
    for r in report.results:
        mark = "PASS" if r.match else "FAIL"
        print(f"  [{mark}] {r.id:<24} {r.reason}")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_render_markdown(report, engine), encoding="utf-8", newline="\n")
    print(f"\nWrote {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
