"""Render the latency trend from .github/perf-history.json.

Produces an interactive Plotly HTML and, when kaleido is installed, a
static PNG. Designed for `make perf-plot` and manual investigation; the
output lands under docs/perf/ so it can be linked from README.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HISTORY_PATH = PROJECT_ROOT / ".github" / "perf-history.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "docs" / "perf"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--history",
        type=Path,
        default=DEFAULT_HISTORY_PATH,
        help="Path to the rolling perf history file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory for history.html and history.png.",
    )
    return parser.parse_args()


def load_history(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        raise SystemExit(f"History file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise SystemExit(f"History file {path} is empty.")
    return data


def build_figure(history: list[dict[str, object]]):
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
    history = load_history(args.history)
    figure = build_figure(history)

    args.output.mkdir(parents=True, exist_ok=True)
    html_path = args.output / "history.html"
    figure.write_html(html_path, include_plotlyjs="cdn")
    print(f"Wrote {html_path} ({len(history)} entries)")

    png_path = args.output / "history.png"
    try:
        figure.write_image(png_path, width=1200, height=640, scale=2)
        print(f"Wrote {png_path}")
    except Exception as exc:  # noqa: BLE001 - kaleido missing is the common case
        print(f"Skipped PNG export: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
