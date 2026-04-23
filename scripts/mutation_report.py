from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MUTMUT_SECTION_RE = re.compile(r"(?ms)^\[tool\.mutmut\]\n.*?(?=^\[|\Z)")
WORKSPACE_LINKS = ("src", "tests", "config", "sdk", "scripts")


@dataclass(frozen=True)
class ModuleTarget:
    threshold: float
    tests: tuple[str, ...]


MODULE_TARGETS = {
    Path("agentflow/retry.py"): ModuleTarget(
        threshold=0.75,
        tests=("tests/sdk/test_retry.py",),
    ),
}

STATUS_BY_EXIT_CODE = {
    0: "survived",
    1: "killed",
    3: "killed",
    5: "no tests",
    24: "timeout",
    33: "no tests",
    34: "skipped",
    35: "suspicious",
    36: "timeout",
    37: "caught by type check",
    152: "timeout",
    255: "timeout",
    -9: "segfault",
    -11: "segfault",
    -24: "timeout",
}

COUNTED_KILL_STATUSES = {"killed", "caught by type check"}
PROBLEM_STATUSES = {
    "check was interrupted by user",
    "no tests",
    "not checked",
    "segfault",
    "suspicious",
    "timeout",
}
STATUS_ORDER = [
    "killed",
    "caught by type check",
    "survived",
    "no tests",
    "timeout",
    "suspicious",
    "segfault",
    "skipped",
    "check was interrupted by user",
    "not checked",
]


@dataclass
class ModuleResult:
    module_path: Path
    threshold: float
    score: float
    killed: int
    survived: int
    total_scored: int
    status_counts: Counter[str]
    survived_mutants: list[str]
    problematic_mutants: list[str]
    errors: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-run", action="store_true")
    parser.add_argument("--results-dir", default="mutants")
    return parser.parse_args()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def status_from_exit_code(exit_code: int | None) -> str:
    if exit_code is None:
        return "not checked"
    return STATUS_BY_EXIT_CODE.get(exit_code, "suspicious")


def meta_path_for(results_dir: Path, module_path: Path) -> Path:
    return results_dir / Path(f"{module_path}.meta")


def render_mutmut_section(module_path: Path, tests: tuple[str, ...]) -> str:
    paths_block = f'    "{module_path.as_posix()}",'
    tests_block = "\n".join(f'    "{test_path}",' for test_path in tests)
    if module_path.parts and module_path.parts[0] == "agentflow":
        also_copy_block = (
            '    "agentflow",\n'
            '    "config",\n'
            '    "scripts",'
        )
    else:
        also_copy_block = (
            '    "src",\n'
            '    "config",\n'
            '    "sdk",\n'
            '    "scripts",'
        )
    return (
        "[tool.mutmut]\n"
        "paths_to_mutate = [\n"
        f"{paths_block}\n"
        "]\n"
        "also_copy = [\n"
        f"{also_copy_block}\n"
        "]\n"
        "tests_dir = [\n"
        f"{tests_block}\n"
        "]\n"
        "mutate_only_covered_lines = true\n"
    )


def build_workspace_pyproject(module_path: Path, target: ModuleTarget) -> str:
    original = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    rendered = render_mutmut_section(module_path, target.tests)
    if not MUTMUT_SECTION_RE.search(original):
        raise RuntimeError("Could not find [tool.mutmut] section in pyproject.toml")
    return MUTMUT_SECTION_RE.sub(rendered, original)


def copy_or_link(source: Path, destination: Path) -> None:
    try:
        os.symlink(source, destination, target_is_directory=source.is_dir())
    except OSError:
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)


def prepare_workspace(workspace: Path, module_path: Path, target: ModuleTarget) -> None:
    is_agentflow_target = bool(module_path.parts) and module_path.parts[0] == "agentflow"
    for name in WORKSPACE_LINKS:
        if is_agentflow_target and name == "sdk":
            continue
        copy_or_link(ROOT / name, workspace / name)
    if is_agentflow_target:
        copy_or_link(ROOT / "sdk" / "agentflow", workspace / "agentflow")
    (workspace / "pyproject.toml").write_text(
        build_workspace_pyproject(module_path, target),
        encoding="utf-8",
    )


def clear_previous_results(results_dir: Path) -> None:
    for module_path in MODULE_TARGETS:
        meta_path = meta_path_for(results_dir, module_path)
        if meta_path.exists():
            meta_path.unlink()
    summary_path = results_dir / "mutmut-cicd-stats.json"
    if summary_path.exists():
        summary_path.unlink()


def run_mutmut(results_dir: Path) -> dict[Path, int]:
    results_dir.mkdir(parents=True, exist_ok=True)
    clear_previous_results(results_dir)
    exit_codes: dict[Path, int] = {}
    mutmut_command = [sys.executable, "-c", "from mutmut.__main__ import cli; cli()"]

    for module_path, target in MODULE_TARGETS.items():
        print(f"Running mutmut for {module_path.name}")
        with tempfile.TemporaryDirectory(prefix="agentflow-mutmut-") as temp_dir:
            workspace = Path(temp_dir)
            prepare_workspace(workspace, module_path, target)
            env = os.environ.copy()

            run_result = subprocess.run(
                [*mutmut_command, "run"],
                cwd=workspace,
                env=env,
                check=False,
            )
            subprocess.run(
                [*mutmut_command, "export-cicd-stats"],
                cwd=workspace,
                env=env,
                check=False,
            )
            exit_codes[module_path] = run_result.returncode

            meta_source = meta_path_for(workspace / "mutants", module_path)
            meta_destination = meta_path_for(results_dir, module_path)
            if meta_source.exists():
                meta_destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(meta_source, meta_destination)

    return exit_codes


def load_module_result(results_dir: Path, module_path: Path, target: ModuleTarget) -> ModuleResult:
    meta_path = meta_path_for(results_dir, module_path)
    if not meta_path.exists():
        return ModuleResult(
            module_path=module_path,
            threshold=target.threshold,
            score=0.0,
            killed=0,
            survived=0,
            total_scored=0,
            status_counts=Counter(),
            survived_mutants=[],
            problematic_mutants=[],
            errors=[f"missing mutation data: {meta_path}"],
        )

    payload = read_json(meta_path)
    exit_code_by_key = payload.get("exit_code_by_key") or {}
    status_by_key = {
        mutant_name: status_from_exit_code(exit_code)
        for mutant_name, exit_code in exit_code_by_key.items()
    }
    status_counts = Counter(status_by_key.values())
    killed = sum(status_counts[status] for status in COUNTED_KILL_STATUSES)
    survived = status_counts["survived"]
    total_scored = killed + survived
    score = killed / total_scored if total_scored else 0.0

    return ModuleResult(
        module_path=module_path,
        threshold=target.threshold,
        score=score,
        killed=killed,
        survived=survived,
        total_scored=total_scored,
        status_counts=status_counts,
        survived_mutants=sorted(
            mutant_name
            for mutant_name, status in status_by_key.items()
            if status == "survived"
        ),
        problematic_mutants=sorted(
            f"{mutant_name}: {status}"
            for mutant_name, status in status_by_key.items()
            if status in PROBLEM_STATUSES
        ),
        errors=[],
    )


def write_overall_summary(results_dir: Path, results: list[ModuleResult]) -> dict:
    summary = {
        "killed": sum(result.killed for result in results),
        "survived": sum(result.status_counts["survived"] for result in results),
        "total": sum(result.total_scored for result in results),
        "no_tests": sum(result.status_counts["no tests"] for result in results),
        "skipped": sum(result.status_counts["skipped"] for result in results),
        "suspicious": sum(result.status_counts["suspicious"] for result in results),
        "timeout": sum(result.status_counts["timeout"] for result in results),
        "check_was_interrupted_by_user": sum(
            result.status_counts["check was interrupted by user"] for result in results
        ),
        "segfault": sum(result.status_counts["segfault"] for result in results),
    }
    write_json(results_dir / "mutmut-cicd-stats.json", summary)
    return summary


def format_counts(status_counts: Counter[str]) -> str:
    parts = [
        f"{status}={status_counts[status]}"
        for status in STATUS_ORDER
        if status_counts[status]
    ]
    return ", ".join(parts) if parts else "no mutation stats"


def print_report(results: list[ModuleResult], overall_summary: dict | None) -> None:
    print("Mutation score report")
    print("=====================")
    if overall_summary:
        print(
            "Overall: "
            f"killed={overall_summary.get('killed', 0)}, "
            f"survived={overall_summary.get('survived', 0)}, "
            f"total={overall_summary.get('total', 0)}"
        )
        print()

    for result in results:
        score_label = f"{result.score:.1%}" if result.total_scored else "n/a"
        print(
            f"{result.module_path.name}: "
            f"score={score_label} "
            f"threshold={result.threshold:.0%} "
            f"({format_counts(result.status_counts)})"
        )
        for error in result.errors:
            print(f"  error: {error}")
        if result.survived_mutants:
            print("  survived mutants:")
            for mutant_name in result.survived_mutants:
                print(f"    - {mutant_name}")
        if result.problematic_mutants:
            print("  problematic mutants:")
            for mutant_name in result.problematic_mutants:
                print(f"    - {mutant_name}")
        print()


def collect_violations(results: list[ModuleResult], exit_codes: dict[Path, int]) -> list[str]:
    violations: list[str] = []
    for module_path, exit_code in exit_codes.items():
        if exit_code != 0:
            violations.append(f"{module_path.name}: mutmut run exited with code {exit_code}")

    for result in results:
        violations.extend(result.errors)
        if result.problematic_mutants:
            violations.append(
                f"{result.module_path.name}: "
                f"{len(result.problematic_mutants)} problematic mutant(s) found"
            )
        if result.total_scored == 0:
            violations.append(f"{result.module_path.name}: no scored mutants found")
            continue
        if result.score < result.threshold:
            violations.append(
                f"{result.module_path.name}: "
                f"score={result.score:.1%} < threshold {result.threshold:.0%}"
            )
    return violations


def main() -> int:
    args = parse_args()
    results_dir = Path(args.results_dir)
    exit_codes: dict[Path, int] = {}
    if not args.skip_run:
        exit_codes = run_mutmut(results_dir)

    results = [
        load_module_result(results_dir, module_path, target)
        for module_path, target in MODULE_TARGETS.items()
    ]
    overall_summary = write_overall_summary(results_dir, results)
    print_report(results, overall_summary)

    violations = collect_violations(results, exit_codes)
    if violations:
        print("Mutation score below threshold:")
        for violation in violations:
            print(f"  - {violation}")
        return 1

    print("Mutation scores meet thresholds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
