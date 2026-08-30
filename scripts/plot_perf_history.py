"""Render the latency trend from ignored local performance history.

Produces an interactive Plotly HTML and, when kaleido is installed, a
static PNG. Designed for `make perf-plot` and manual investigation; the
output lands under `.artifacts/perf-history/` and is not tracked evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from plotly.graph_objects import Figure

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / ".artifacts" / "perf-history"
DEFAULT_HISTORY_PATH = DEFAULT_OUTPUT_DIR / "history.json"
DOCS_ROOT = PROJECT_ROOT / "docs"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--history",
        type=Path,
        default=DEFAULT_HISTORY_PATH,
        help="Path to the rolling runtime history.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Runtime output directory for history.html and history.png.",
    )
    return parser.parse_args()


def resolve_history_path(history_path: str | Path) -> Path:
    candidate = Path(history_path)
    return candidate if candidate.is_absolute() else PROJECT_ROOT / candidate


def resolve_output_dir(output_dir: str | Path) -> Path:
    candidate = Path(output_dir)
    resolved = candidate if candidate.is_absolute() else PROJECT_ROOT / candidate
    try:
        resolved.resolve().relative_to(DOCS_ROOT.resolve())
    except ValueError:
        return resolved
    raise ValueError(
        "Performance-history plots are runtime artifacts; write them under "
        ".artifacts/perf-history/ instead of docs/."
    )


def load_history(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        raise SystemExit(f"History file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise SystemExit(f"History file {path} is empty.")
    return data


def build_figure(history: list[dict[str, object]]) -> Figure:
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError as exc:
        raise SystemExit(
            "plotly is required. Install with `pip install plotly` or `pip install -e .[viz]`."
        ) from exc

    timestamps = [entry["timestamp"] for entry in history]
    commits = [entry.get("commit_sha", "") for entry in history]

    figure = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        subplot_titles=("Latency (ms)", "Throughput (req/s)"),
        vertical_spacing=0.12,
    )

    for metric, name, color in (
        ("p50_ms", "p50", "#22c55e"),
        ("p95_ms", "p95", "#f59e0b"),
        ("p99_ms", "p99", "#ef4444"),
    ):
        figure.add_trace(
            go.Scatter(
                x=timestamps,
                y=[entry.get(metric, 0.0) for entry in history],
                mode="lines+markers",
                name=name,
                text=commits,
                hovertemplate="%{x}<br>%{y:.1f} ms<br>commit %{text}<extra>" + name + "</extra>",
                line={"color": color},
            ),
            row=1,
            col=1,
        )

    figure.add_trace(
        go.Scatter(
            x=timestamps,
            y=[entry.get("throughput_rps", 0.0) for entry in history],
            mode="lines+markers",
            name="throughput",
            text=commits,
            hovertemplate="%{x}<br>%{y:.1f} req/s<br>commit %{text}<extra>throughput</extra>",
            line={"color": "#3b82f6"},
        ),
        row=2,
        col=1,
    )

    figure.update_layout(
        title="AgentFlow benchmark trend",
        height=640,
        template="plotly_white",
        legend={"orientation": "h", "y": -0.15},
    )
    figure.update_yaxes(title_text="ms", row=1, col=1)
    figure.update_yaxes(title_text="req/s", row=2, col=1)
    return figure


def main() -> int:
    args = parse_args()
    try:
        history_path = resolve_history_path(args.history)
        output_dir = resolve_output_dir(args.output)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    history = load_history(history_path)
    figure = build_figure(history)

    output_dir.mkdir(parents=True, exist_ok=True)
    html_path = output_dir / "history.html"
    figure.write_html(html_path, include_plotlyjs="cdn")
    print(f"Wrote {html_path} ({len(history)} entries)")

    png_path = output_dir / "history.png"
    try:
        figure.write_image(png_path, width=1200, height=640, scale=2)
        print(f"Wrote {png_path}")
    except Exception as exc:  # noqa: BLE001 - kaleido missing is the common case
        print(f"Skipped PNG export: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
