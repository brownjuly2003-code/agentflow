"""CLI: run the NL->SQL execution-accuracy eval and print / write a report.

    python -m scripts.run_nl_sql_eval                 # print to stdout
    python -m scripts.run_nl_sql_eval --md report.md  # also write a markdown report

Measures whatever `translate_nl_to_sql` is configured to do: rule-based by
default, or the GraceKelly/Sonnet-5 LLM path when GRACEKELLY_URL is set. See
ADR 0008 and docs/perf/nl-sql-eval-*.md.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from scripts.nl_sql_eval import EvalReport, run_eval


def _engine_label() -> str:
    return "gracekelly-llm" if os.getenv("GRACEKELLY_URL") else "rule-based"


def _render_markdown(report: EvalReport, engine: str) -> str:
    lines = [
        "# NL->SQL execution-accuracy eval",
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


def main() -> int:
    parser = argparse.ArgumentParser(description="NL->SQL execution-accuracy eval")
    parser.add_argument(
        "--md", type=Path, default=None, help="Write a markdown report to this path"
    )
    args = parser.parse_args()

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

    if args.md is not None:
        args.md.write_text(_render_markdown(report, engine), encoding="utf-8")
        print(f"\nWrote {args.md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
