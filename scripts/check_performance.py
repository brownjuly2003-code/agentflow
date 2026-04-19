"""Check benchmark output against the committed release gate."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE_PATH = PROJECT_ROOT / "docs" / "benchmark-baseline.json"
DEFAULT_CURRENT_PATH = PROJECT_ROOT / ".artifacts" / "benchmark" / "current.json"
CURRENT_PATH_CANDIDATES = (
    DEFAULT_CURRENT_PATH,
    PROJECT_ROOT / ".artifacts" / "load" / "results.json",
    PROJECT_ROOT / "tests" / "load" / "results.json",
)
REGRESSION_LIMIT = 0.20
DEFAULT_MAX_REGRESS_PERCENT = REGRESSION_LIMIT * 100
DEFAULT_ENTITY_P50_GATE_MS = 100.0
DEFAULT_ENTITY_P99_GATE_MS = 500.0


@dataclass(frozen=True)
class BenchmarkSample:
    p50_latency_ms: float
    p99_latency_ms: float


@dataclass(frozen=True)
class EntityGate:
    p50_ms: float
    p99_ms: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fail when benchmark latency exceeds the release gate.",
    )
    parser.add_argument(
        "baseline_path",
        nargs="?",
        type=Path,
    )
    parser.add_argument(
        "current_path",
        nargs="?",
        type=Path,
    )
    parser.add_argument(
        "--baseline",
        dest="baseline_flag",
        type=Path,
    )
    parser.add_argument(
        "--current",
        dest="current_flag",
        type=Path,
    )
    parser.add_argument(
        "--max-regress",
        type=float,
        default=DEFAULT_MAX_REGRESS_PERCENT,
        help="Max p50 regression percentage allowed before failing.",
    )
    args = parser.parse_args()
    args.baseline = args.baseline_flag or args.baseline_path or DEFAULT_BASELINE_PATH
    args.current = args.current_flag or args.current_path or DEFAULT_CURRENT_PATH
    return args


def resolve_current_path(path: Path) -> Path:
    if path.exists():
        return path
    if path == DEFAULT_CURRENT_PATH:
        for candidate in CURRENT_PATH_CANDIDATES:
            if candidate.exists():
                return candidate
    return path


def load_report(path: Path) -> dict[str, object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"Benchmark file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {path}: {exc}") from exc


def _require_number(payload: dict[str, object], keys: tuple[str, ...], label: str) -> float:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise SystemExit(f"Invalid numeric value for {label}.{key}") from exc
    raise SystemExit(f"Missing metric for {label}: expected one of {', '.join(keys)}")


def normalize_endpoint_name(name: str) -> str:
    return name.replace("[id]", "{id}").replace("[name]", "{name}")


def load_sample(payload: object, label: str) -> BenchmarkSample:
    if not isinstance(payload, dict):
        raise SystemExit(f"Expected object for {label}.")
    return BenchmarkSample(
        p50_latency_ms=_require_number(
            payload,
            ("p50_ms", "p50_latency_ms", "p50"),
            label,
        ),
        p99_latency_ms=_require_number(
            payload,
            ("p99_ms", "p99_latency_ms", "p99"),
            label,
        ),
    )


def collect_samples(report: dict[str, object], label: str) -> dict[str, BenchmarkSample]:
    samples: dict[str, BenchmarkSample] = {}

    aggregate = report.get("aggregate")
    if aggregate is not None:
        samples["ALL"] = load_sample(aggregate, f"{label} aggregate")

    endpoints = report.get("endpoints")
    if not isinstance(endpoints, dict):
        raise SystemExit(f"Expected 'endpoints' object in {label}.")

    for endpoint, payload in endpoints.items():
        if not isinstance(endpoint, str):
            raise SystemExit(f"Endpoint name must be a string in {label}.")
        samples[normalize_endpoint_name(endpoint)] = load_sample(
            payload,
            f"{label} endpoint {endpoint!r}",
        )

    if not samples:
        raise SystemExit(f"No benchmark samples found in {label}.")

    return samples


def load_entity_gate(report: dict[str, object]) -> EntityGate:
    gate = report.get("gate")
    if isinstance(gate, dict):
        entity_gate = gate.get("entity")
        if isinstance(entity_gate, dict):
            return EntityGate(
                p50_ms=_require_number(
                    entity_gate,
                    ("p50_ms", "p50_latency_ms", "p50"),
                    "gate.entity",
                ),
                p99_ms=_require_number(
                    entity_gate,
                    ("p99_ms", "p99_latency_ms", "p99"),
                    "gate.entity",
                ),
            )
    return EntityGate(
        p50_ms=DEFAULT_ENTITY_P50_GATE_MS,
        p99_ms=DEFAULT_ENTITY_P99_GATE_MS,
    )


def sort_endpoint_names(names: set[str]) -> list[str]:
    ordered = sorted(name for name in names if name != "ALL")
    if "ALL" in names:
        return ["ALL", *ordered]
    return ordered


def format_delta(baseline: float, current: float) -> str:
    if baseline == 0:
        return "0.0%" if current == 0 else "inf"
    return f"{((current / baseline) - 1.0) * 100:.1f}%"


def is_entity_endpoint(name: str) -> bool:
    return name.startswith("GET /v1/entity/")


def main() -> int:
    args = parse_args()
    current_path = resolve_current_path(args.current)
    baseline_report = load_report(args.baseline)
    current_report = load_report(current_path)
    baseline_samples = collect_samples(
        baseline_report,
        f"baseline report {args.baseline}",
    )
    current_samples = collect_samples(
        current_report,
        f"current report {current_path}",
    )
    entity_gate = load_entity_gate(baseline_report)

    shared_names = set(baseline_samples) & set(current_samples)
    if not shared_names:
        raise SystemExit("No shared benchmark endpoints between baseline and current reports.")

    regressions: list[str] = []
    rows: list[tuple[str, BenchmarkSample, BenchmarkSample, str]] = []
    regression_limit = args.max_regress / 100

    missing_names = sort_endpoint_names(set(baseline_samples) - set(current_samples))
    for name in missing_names:
        regressions.append(f"{name}: missing in current benchmark output")

    extra_names = sort_endpoint_names(set(current_samples) - set(baseline_samples))

    for name in sort_endpoint_names(shared_names):
        baseline = baseline_samples[name]
        current = current_samples[name]
        statuses: list[str] = []

        if baseline.p50_latency_ms == 0:
            if current.p50_latency_ms > 0:
                statuses.append("REGRESSION")
                regressions.append(
                    f"{name}: p50 increased from 0.0 ms to {current.p50_latency_ms:.1f} ms"
                )
        elif current.p50_latency_ms > baseline.p50_latency_ms * (1 + regression_limit):
            statuses.append("REGRESSION")
            regressions.append(
                f"{name}: p50 regressed by {format_delta(baseline.p50_latency_ms, current.p50_latency_ms)} "
                f"({baseline.p50_latency_ms:.1f} ms -> {current.p50_latency_ms:.1f} ms)"
            )

        if is_entity_endpoint(name):
            if current.p50_latency_ms > entity_gate.p50_ms:
                statuses.append("P50_GATE")
                regressions.append(
                    f"{name}: p50 {current.p50_latency_ms:.1f} ms exceeds gate {entity_gate.p50_ms:.1f} ms"
                )
            if current.p99_latency_ms > entity_gate.p99_ms:
                statuses.append("P99_GATE")
                regressions.append(
                    f"{name}: p99 {current.p99_latency_ms:.1f} ms exceeds gate {entity_gate.p99_ms:.1f} ms"
                )

        rows.append(
            (
                name,
                baseline,
                current,
                ", ".join(statuses) if statuses else "PASS",
            )
        )

    status = "FAIL" if regressions else "PASS"
    print("## Performance Gate")
    print()
    print(f"- Status: `{status}`")
    print(f"- Baseline: `{args.baseline}`")
    print(f"- Current: `{current_path}`")
    print(f"- Entity gate: `p50 <= {entity_gate.p50_ms:.0f} ms`, `p99 <= {entity_gate.p99_ms:.0f} ms`")
    print(f"- Regression threshold: `p50 <= +{args.max_regress:.0f}%`")
    print()
    print("| Endpoint | Base p50 | Curr p50 | Base p99 | Curr p99 | Status |")
    print("| --- | ---: | ---: | ---: | ---: | --- |")
    for name, baseline, current, row_status in rows:
        print(
            f"| {name} | "
            f"{baseline.p50_latency_ms:.1f} ms | "
            f"{current.p50_latency_ms:.1f} ms | "
            f"{baseline.p99_latency_ms:.1f} ms | "
            f"{current.p99_latency_ms:.1f} ms | "
            f"{row_status} |"
        )

    if extra_names:
        print()
        print("### Extra Endpoints")
        for name in extra_names:
            print(f"- {name}")

    if regressions:
        print()
        print("### Regressions")
        for regression in regressions:
            print(f"- {regression}")
        return 1

    print()
    print("### Summary")
    print("- Current benchmark is within the configured release gate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
