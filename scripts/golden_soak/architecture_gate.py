#!/usr/bin/env python3
"""Run the local CI-soak architecture checks and emit one terminal verdict."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

MAX_AUDIT_BYTES = 256 * 1024
MAX_MANIFEST_BYTES = 64 * 1024
MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_CAPTURE_BYTES = 1024
EXPECTED_PACK_FILES = 8

_HEAD_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PACK_PATH_RE = re.compile(r"^pack/[A-Za-z0-9_.-]+$")
_LOCAL_FINDINGS = tuple(f"A-{index:02d}" for index in range(1, 10))
_BLOCKER_ORDER = (
    *_LOCAL_FINDINGS,
    "A-10",
    "A-11",
    "G-TESTS",
    "G-RUFF",
    "G-COMPILE",
    "G-COMPOSE",
    "G-DIFF",
    "G-CLEAN",
    "G-PACK",
    "G-ENCODING",
    "G-HEAD",
)

_PYTHON_PATHS = (
    "scripts/golden_soak/runtime.py",
    "scripts/golden_soak/pods_shim.py",
    "scripts/golden_soak/wrapper.py",
    "scripts/golden_soak/architecture_gate.py",
    "tests/unit/test_ci_soak_runtime.py",
    "tests/unit/test_ci_soak_foundation.py",
    "tests/unit/test_ci_soak_wrapper.py",
    "tests/unit/test_ci_soak_architecture_gate.py",
)

_TEXT_PATHS = (
    *_PYTHON_PATHS,
    "scripts/golden_soak/README.md",
    "ci-soak-r1-r7-architecture-audit.md",
    "ci-soak-runtime-harness.md",
    "ci-soak-architecture-gate-plan.md",
)


@dataclass(frozen=True)
class CommandCheck:
    name: str
    blocker: str
    argv: tuple[str, ...]
    timeout_seconds: int
    capture_stdout: bool = False


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""


class Runner(Protocol):
    def run(self, check: CommandCheck, *, cwd: Path) -> CommandResult: ...


class SubprocessRunner:
    def run(self, check: CommandCheck, *, cwd: Path) -> CommandResult:
        try:
            completed = subprocess.run(  # noqa: S603
                check.argv,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE if check.capture_stdout else subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=check.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return CommandResult(returncode=124)
        except OSError:
            return CommandResult(returncode=127)

        output = ""
        if check.capture_stdout and len(completed.stdout) <= MAX_CAPTURE_BYTES:
            try:
                output = completed.stdout.decode("utf-8")
            except UnicodeDecodeError:
                pass
        return CommandResult(returncode=completed.returncode, stdout=output)


@dataclass(frozen=True)
class GateConfig:
    repo_root: Path
    audit_path: Path
    manifest_path: Path
    pack_root: Path
    text_paths: tuple[Path, ...]
    command_checks: tuple[CommandCheck, ...]
    head_check: CommandCheck


@dataclass(frozen=True)
class GateResult:
    status: str
    blockers: tuple[str, ...]
    head: str

    def line(self) -> str:
        blocker_text = "0" if not self.blockers else ",".join(self.blockers)
        return f"ARCHITECTURE_READY={self.status} blockers={blocker_text} head={self.head}"


def build_config(repo_root: Path) -> GateConfig:
    python_prefix = (sys.executable, "-m")
    command_checks = (
        CommandCheck(
            name="focused_tests",
            blocker="G-TESTS",
            argv=(
                *python_prefix,
                "pytest",
                "tests/unit/test_ci_soak_runtime.py",
                "tests/unit/test_ci_soak_foundation.py",
                "tests/unit/test_ci_soak_wrapper.py",
                "-q",
            ),
            timeout_seconds=180,
        ),
        CommandCheck(
            name="ruff_check",
            blocker="G-RUFF",
            argv=(*python_prefix, "ruff", "check", *_PYTHON_PATHS),
            timeout_seconds=60,
        ),
        CommandCheck(
            name="ruff_format",
            blocker="G-RUFF",
            argv=(*python_prefix, "ruff", "format", "--check", *_PYTHON_PATHS),
            timeout_seconds=60,
        ),
        CommandCheck(
            name="py_compile",
            blocker="G-COMPILE",
            argv=(*python_prefix, "py_compile", *_PYTHON_PATHS),
            timeout_seconds=60,
        ),
        CommandCheck(
            name="compose_config",
            blocker="G-COMPOSE",
            argv=(
                "docker",
                "compose",
                "-f",
                "docker-compose.yml",
                "-f",
                "docker-compose.flink.yml",
                "-f",
                "docker-compose.soak.yml",
                "config",
                "--quiet",
            ),
            timeout_seconds=60,
        ),
        CommandCheck(
            name="diff_check",
            blocker="G-DIFF",
            argv=("git", "diff", "--check", "HEAD", "--"),
            timeout_seconds=30,
        ),
        CommandCheck(
            name="clean_tree",
            blocker="G-CLEAN",
            argv=("git", "diff", "--quiet", "HEAD", "--"),
            timeout_seconds=30,
        ),
    )
    return GateConfig(
        repo_root=repo_root,
        audit_path=repo_root / "ci-soak-r1-r7-architecture-audit.md",
        manifest_path=repo_root / "scripts" / "golden_soak" / "MANIFEST.json",
        pack_root=repo_root / "scripts" / "golden_soak",
        text_paths=tuple(repo_root / relative for relative in _TEXT_PATHS),
        command_checks=command_checks,
        head_check=CommandCheck(
            name="head",
            blocker="G-HEAD",
            argv=("git", "rev-parse", "HEAD"),
            timeout_seconds=30,
            capture_stdout=True,
        ),
    )


def _read_bounded(path: Path, maximum: int) -> bytes:
    raw = path.read_bytes()
    if not raw or len(raw) > maximum:
        raise ValueError("bounded_file_invalid")
    return raw


def _audit_blockers(path: Path) -> list[str]:
    try:
        text = _read_bounded(path, MAX_AUDIT_BYTES).decode("utf-8")
    except (OSError, UnicodeDecodeError, ValueError):
        return [*_LOCAL_FINDINGS, "A-10", "A-11"]

    blockers: list[str] = []
    for finding in (*_LOCAL_FINDINGS, "A-10", "A-11"):
        rows = re.findall(rf"^\| `{re.escape(finding)}` \|.*$", text, flags=re.MULTILINE)
        if len(rows) != 1:
            blockers.append(finding)
            continue
        cells = rows[0].split("|")
        severity = cells[2] if len(cells) > 2 else ""
        if finding in _LOCAL_FINDINGS:
            closed = "`CLOSED-LOCAL`" in severity
        elif finding == "A-10":
            closed = "`ACCEPTED-RISK`" in severity
        else:
            closed = "`CLOSED-DOC`" in rows[0]
        if not closed:
            blockers.append(finding)
    return blockers


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError("duplicate_json_key")
        payload[key] = value
    return payload


def _pack_is_valid(manifest_path: Path, pack_root: Path) -> bool:
    try:
        raw = _read_bounded(manifest_path, MAX_MANIFEST_BYTES)
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_json_object)
        files = payload["files"]
        if not isinstance(files, dict) or len(files) != EXPECTED_PACK_FILES:
            return False
        resolved_root = pack_root.resolve(strict=True)
        for relative, expected in files.items():
            if not isinstance(relative, str) or not _PACK_PATH_RE.fullmatch(relative):
                return False
            if not isinstance(expected, dict) or set(expected) != {"bytes", "sha256"}:
                return False
            expected_bytes = expected["bytes"]
            expected_sha256 = expected["sha256"]
            if type(expected_bytes) is not int or expected_bytes < 0:
                return False
            if not isinstance(expected_sha256, str) or not _SHA256_RE.fullmatch(expected_sha256):
                return False
            target = (resolved_root / relative).resolve(strict=True)
            target.relative_to(resolved_root)
            content = target.read_bytes()
            if len(content) != expected_bytes:
                return False
            if hashlib.sha256(content).hexdigest() != expected_sha256:
                return False
    except (KeyError, OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return False
    return True


def _encoding_is_valid(paths: tuple[Path, ...]) -> bool:
    for path in paths:
        try:
            raw = _read_bounded(path, MAX_TEXT_BYTES)
            raw.decode("utf-8")
        except (OSError, UnicodeDecodeError, ValueError):
            return False
        if raw.startswith(b"\xef\xbb\xbf") or b"\0" in raw or b"\r" in raw:
            return False
    return True


def _ordered_unique(blockers: list[str]) -> tuple[str, ...]:
    blocker_set = set(blockers)
    ordered = [blocker for blocker in _BLOCKER_ORDER if blocker in blocker_set]
    ordered.extend(sorted(blocker_set.difference(_BLOCKER_ORDER)))
    return tuple(ordered)


def evaluate_gate(config: GateConfig, runner: Runner) -> GateResult:
    blockers = _audit_blockers(config.audit_path)
    for check in config.command_checks:
        result = runner.run(check, cwd=config.repo_root)
        if result.returncode != 0:
            blockers.append(check.blocker)

    if not _pack_is_valid(config.manifest_path, config.pack_root):
        blockers.append("G-PACK")
    if not _encoding_is_valid(config.text_paths):
        blockers.append("G-ENCODING")

    head_result = runner.run(config.head_check, cwd=config.repo_root)
    head_lines = head_result.stdout.splitlines()
    if head_result.returncode == 0 and len(head_lines) == 1 and _HEAD_RE.fullmatch(head_lines[0]):
        head = head_lines[0]
    else:
        head = "UNKNOWN"
        blockers.append("G-HEAD")

    ordered = _ordered_unique(blockers)
    return GateResult(
        status="PASS" if not ordered else "BLOCKED",
        blockers=ordered,
        head=head,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path)
    return parser


def main(
    argv: list[str] | None = None,
    *,
    config: GateConfig | None = None,
    runner: Runner | None = None,
) -> int:
    args = _parser().parse_args(argv)
    if config is None:
        repo_root = (
            args.repo_root.resolve()
            if args.repo_root is not None
            else Path(__file__).resolve().parents[2]
        )
        config = build_config(repo_root)
    result = evaluate_gate(config, runner or SubprocessRunner())
    print(result.line(), flush=True)
    return 0 if result.status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
