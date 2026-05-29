from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_project_dependencies(pyproject_path: Path) -> list[str]:
    if not pyproject_path.exists():
        return []
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    return list(data.get("project", {}).get("dependencies", []))


def load_requirements(requirements_path: Path) -> list[str]:
    if not requirements_path.exists():
        return []
    requirements: list[str] = []
    for line in requirements_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        requirements.append(stripped)
    return requirements


def write_requirements(target: Path, entries: list[str]) -> None:
    deduped = list(dict.fromkeys(entries))
    target.write_text("\n".join(deduped) + "\n", encoding="utf-8")


def resolve_requirements(name: str, entries: list[str], target: Path, work_dir: Path) -> int:
    temp_input = work_dir / f"{name}.in"
    write_requirements(temp_input, entries)

    venv_dir = work_dir / f"safety-{name}-venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)  # noqa: S603
    scripts_dir = venv_dir / ("Scripts" if sys.platform == "win32" else "bin")
    python = scripts_dir / ("python.exe" if sys.platform == "win32" else "python")
    subprocess.run(  # noqa: S603
        [str(python), "-m", "pip", "install", "--upgrade", "pip"],
        check=True,
    )
    subprocess.run(  # noqa: S603
        [str(python), "-m", "pip", "install", "-r", str(temp_input)],
        check=True,
    )
    freeze = subprocess.run(  # noqa: S603
        [str(python), "-m", "pip", "freeze"],
        check=True,
        capture_output=True,
        text=True,
    )

    resolved = [line for line in freeze.stdout.splitlines() if line.strip()]
    if any("==" not in line for line in resolved):
        raise SystemExit(f"{name} requirements were not fully resolved")
    target.write_text("\n".join(resolved) + "\n", encoding="utf-8")
    return len(resolved)


def build_resolved_requirement_files(temp_path: Path) -> tuple[Path, Path, Path]:
    main_requirements = temp_path / "requirements-main.txt"
    sdk_requirements = temp_path / "requirements-sdk.txt"
    integrations_requirements = temp_path / "requirements-integrations.txt"

    resolve_requirements(
        "main",
        load_project_dependencies(REPO_ROOT / "pyproject.toml")
        + load_requirements(REPO_ROOT / "requirements.txt"),
        main_requirements,
        temp_path,
    )
    resolve_requirements(
        "sdk",
        load_project_dependencies(REPO_ROOT / "sdk" / "pyproject.toml"),
        sdk_requirements,
        temp_path,
    )
    integrations_deps = [
        dep
        for dep in load_project_dependencies(REPO_ROOT / "integrations" / "pyproject.toml")
        if not dep.lower().startswith(("agentflow-client", "agentflow-runtime"))
    ]
    resolve_requirements(
        "integrations",
        integrations_deps,
        integrations_requirements,
        temp_path,
    )
    return main_requirements, sdk_requirements, integrations_requirements


def resolve_command(program: str) -> str:
    command = shutil.which(program)
    if command:
        return command

    scripts_dir = Path(sys.executable).resolve().parent
    candidates = [scripts_dir / program]
    if sys.platform == "win32":
        candidates.insert(0, scripts_dir / f"{program}.exe")

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    raise FileNotFoundError(
        f"Required command '{program}' was not found. Install with: "
        'pip install bandit "safety<3" pip-audit'
    )


def run_check(name: str, command: list[str]) -> bool:
    print(f"\n{'=' * 60}\n{name}\n{'=' * 60}")
    result = subprocess.run(command, cwd=REPO_ROOT, check=False)  # noqa: S603
    return result.returncode == 0


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="agentflow-security-") as temp_dir:
        temp_path = Path(temp_dir)
        main_requirements, sdk_requirements, integrations_requirements = (
            build_resolved_requirement_files(temp_path)
        )

        checks = [
            (
                "Bandit (SAST)",
                [
                    sys.executable,
                    "-m",
                    "bandit",
                    "-r",
                    "src",
                    "sdk",
                    "--ini",
                    ".bandit",
                    "--severity-level",
                    "medium",
                ],
            ),
            (
                "Safety (CVE)",
                [
                    resolve_command("safety"),
                    "check",
                    "-r",
                    str(main_requirements),
                    "-r",
                    str(sdk_requirements),
                    "-r",
                    str(integrations_requirements),
                ],
            ),
            (
                "pip-audit",
                [
                    resolve_command("pip-audit"),
                    "-r",
                    str(main_requirements),
                    "-r",
                    str(sdk_requirements),
                    "-r",
                    str(integrations_requirements),
                    "--progress-spinner",
                    "off",
                ],
            ),
        ]

        failed: list[str] = []
        for name, command in checks:
            try:
                passed = run_check(name, command)
            except FileNotFoundError as error:
                print(error)
                passed = False
            if not passed:
                failed.append(name)

    if failed:
        print(f"\nFAILED: {', '.join(failed)}")
        return 1

    print("\nAll security checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
