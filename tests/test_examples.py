from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_ROOT = PROJECT_ROOT / "examples"
EXAMPLE_NAMES = ("support-agent", "ops-agent", "merch-agent")
README_SECTIONS = ("Prerequisites", "Setup", "Run", "Expected Output")


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("example_name", EXAMPLE_NAMES)
def test_example_files_exist(example_name: str):
    example_dir = EXAMPLES_ROOT / example_name

    assert example_dir.exists()
    assert (example_dir / "main.py").exists()
    assert (example_dir / "README.md").exists()


@pytest.mark.parametrize("example_name", EXAMPLE_NAMES)
def test_example_readme_covers_required_sections(example_name: str):
    readme = (EXAMPLES_ROOT / example_name / "README.md").read_text(encoding="utf-8")

    for section in README_SECTIONS:
        assert f"## {section}" in readme


@pytest.mark.parametrize("example_name", EXAMPLE_NAMES)
def test_example_module_supports_dry_run(example_name: str):
    module = _load_module(EXAMPLES_ROOT / example_name / "main.py")

    assert hasattr(module, "run_demo")
    assert hasattr(module, "main")

    payload = module.run_demo(dry_run=True)

    assert isinstance(payload, dict)
    assert payload["agent"] == example_name
    assert payload["mode"] == "dry-run"
    assert payload["steps"]
    assert payload["expected_output"]
    assert module.main(["--dry-run"]) == 0


def test_examples_index_links_all_examples():
    readme = (EXAMPLES_ROOT / "README.md").read_text(encoding="utf-8")

    for example_name in EXAMPLE_NAMES:
        assert f"[{example_name}]({example_name}/README.md)" in readme
