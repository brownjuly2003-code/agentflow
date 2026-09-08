"""Contract: `opslab/` stays an explained, isolated distribution (audit FB-16).

The audit found eight tracked files under `opslab/` that no `pyproject.toml`,
workflow, or documentation page referenced — unexplainable from the repository
alone. `opslab/README.md` now explains them, and these tests keep the claims on
that page true: the benchmark distribution cannot reach a published runtime
artifact, it is a distribution of its own rather than a subpackage, and it is
discoverable from the repository root.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OPSLAB_ROOT = PROJECT_ROOT / "opslab"
OPSLAB_README = OPSLAB_ROOT / "README.md"
ROOT_README = PROJECT_ROOT / "README.md"
ROOT_PYPROJECT = PROJECT_ROOT / "pyproject.toml"
CI_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"


def _root_metadata() -> dict:
    return tomllib.loads(ROOT_PYPROJECT.read_text(encoding="utf-8"))


def test_runtime_wheel_cannot_ship_the_benchmark_package() -> None:
    wheel = _root_metadata()["tool"]["hatch"]["build"]["targets"]["wheel"]
    included = wheel["only-include"]

    assert included == ["src/agentflow_runtime", "packaging/src_shim/src"]
    assert not any("opslab" in entry for entry in included), (
        "agentflow_opslab is an unreleased benchmark skeleton; it must not reach "
        "a published runtime artifact"
    )


def test_opslab_is_its_own_distribution_not_a_subpackage() -> None:
    metadata = tomllib.loads((OPSLAB_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert metadata["project"]["name"] == "agentflow-opslab"
    assert metadata["build-system"]["build-backend"] == "hatchling.build"
    assert metadata["project"]["name"] != _root_metadata()["project"]["name"]


def test_the_directory_explains_itself_and_is_reachable_from_the_root() -> None:
    assert OPSLAB_README.is_file(), "opslab/ must say what it is and whether it is live"
    assert "opslab/" in ROOT_README.read_text(encoding="utf-8"), (
        "the root README must name opslab/, or the directory is undiscoverable again"
    )


def test_the_readme_is_honest_about_opslab_being_outside_the_root_gates() -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    readme = OPSLAB_README.read_text(encoding="utf-8")

    # The page tells the reader the boundary tests never run in CI. That claim
    # stops being true the moment a CI command mentions opslab, and the page
    # must be rewritten in the same change.
    if "opslab" in workflow:
        assert "never execute in CI" not in readme, (
            "ci.yml now reaches opslab/; update opslab/README.md, which still says its "
            "tests never run in CI"
        )
    else:
        assert "never execute in CI" in readme, (
            "no CI command reaches opslab/; opslab/README.md must keep saying so rather "
            "than leaving the reader to assume it is gated"
        )
