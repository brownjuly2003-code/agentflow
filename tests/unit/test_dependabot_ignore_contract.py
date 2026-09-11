"""Dependabot `ignore` conditions in the pip ecosystems must state version ranges.

`update-types: ["version-update:semver-major"]` reads like a major-version gate
and is not one here. Dependabot derives the update type from the *current*
version, and neither pip ecosystem in this repository has one: every
requirement is a range (`mcp>=1.0,<2`) and there is no pip lockfile for the
updater to resolve it against. With nothing to compare against, the condition
matches nothing.

The root pip run 34213488343 (2026-09-08) shows it end to end: the job
definition carried all six ignore conditions, the log printed ``Checking if mcp
 needs updating`` with an empty current version, then ``Ignored versions:`` with
an empty list, then ``Updating mcp from  to 2.1.1`` -- and PR #254 re-proposed
the widening that #244 had already been closed for, hours after the mcp ignore
landed.

An explicit ``versions`` range is evaluated against the candidate version, so it
needs no current version. These tests keep every pip ignore on that mechanism
and keep each ceiling equal to the upper bound the corresponding pyproject
actually declares -- widening a pin without moving its ignore (or the reverse)
fails here rather than by re-opening the same Dependabot PR every week.

The docker and github-actions ecosystems deliberately keep `update-types`: an
image tag and an action ref *are* pinned current versions, so the mechanism
works there.
"""

import tomllib
from pathlib import Path

import pytest
import yaml
from packaging.requirements import Requirement

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEPENDABOT_PATH = PROJECT_ROOT / ".github" / "dependabot.yml"

# Dependabot `directory` -> the manifest whose upper bounds the ignores mirror.
PIP_MANIFESTS = {
    "/": PROJECT_ROOT / "pyproject.toml",
    "/integrations": PROJECT_ROOT / "integrations" / "pyproject.toml",
}


def _load_dependabot() -> dict:
    return yaml.safe_load(DEPENDABOT_PATH.read_text(encoding="utf-8"))


def _pip_updates_with_ignores() -> list[dict]:
    return [
        update
        for update in _load_dependabot()["updates"]
        if update["package-ecosystem"] == "pip" and update.get("ignore")
    ]


def _declared_requirements(manifest_path: Path) -> dict[str, Requirement]:
    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    project = manifest["project"]

    raw: list[str] = list(project.get("dependencies", []))
    for extra in project.get("optional-dependencies", {}).values():
        raw.extend(extra)

    requirements: dict[str, Requirement] = {}
    for entry in raw:
        requirement = Requirement(entry)
        # A name declared in several extras must declare the same bound in each,
        # otherwise "the" ceiling this ignore mirrors is ambiguous.
        previous = requirements.get(requirement.name)
        assert previous is None or str(previous.specifier) == str(requirement.specifier), (
            f"{requirement.name} is declared with conflicting specifiers in "
            f"{manifest_path.name}: {previous} vs {requirement}"
        )
        requirements[requirement.name] = requirement

    return requirements


def _exclusive_upper_bound(requirement: Requirement) -> str:
    uppers = [spec.version for spec in requirement.specifier if spec.operator == "<"]
    assert len(uppers) == 1, (
        f"{requirement.name} must declare exactly one `<` upper bound for its "
        f"Dependabot ignore to mirror; found {uppers or 'none'}"
    )
    return uppers[0]


def test_pip_ecosystems_have_ignore_conditions() -> None:
    """A vacuous suite would pass if the ignore blocks were dropped wholesale."""
    directories = {update["directory"] for update in _pip_updates_with_ignores()}
    assert directories == set(PIP_MANIFESTS), (
        "expected pip ignore conditions in exactly the root and integrations "
        f"ecosystems, found {sorted(directories)}"
    )


@pytest.mark.parametrize("update", _pip_updates_with_ignores(), ids=lambda u: u["directory"])
def test_pip_ignore_conditions_state_a_version_range(update: dict) -> None:
    for condition in update["ignore"]:
        name = condition["dependency-name"]
        assert "update-types" not in condition, (
            f"{name} ({update['directory']}) gates on update-types; without a "
            "resolved current version Dependabot cannot classify the update and "
            "the condition is inert (root pip run 34213488343). Use `versions`."
        )
        versions = condition.get("versions")
        assert versions, f"{name} ({update['directory']}) has no `versions` range"
        assert all(str(entry).startswith(">=") for entry in versions), (
            f"{name} ({update['directory']}) must ignore everything at or above "
            f"its declared ceiling, got {versions}"
        )


@pytest.mark.parametrize("update", _pip_updates_with_ignores(), ids=lambda u: u["directory"])
def test_pip_ignore_ceilings_mirror_the_declared_upper_bound(update: dict) -> None:
    requirements = _declared_requirements(PIP_MANIFESTS[update["directory"]])

    for condition in update["ignore"]:
        name = condition["dependency-name"]
        requirement = requirements.get(name)
        assert requirement is not None, (
            f"{name} is ignored for {update['directory']} but that manifest no "
            "longer declares it; drop the ignore or restore the dependency"
        )
        ceiling = _exclusive_upper_bound(requirement)
        assert condition["versions"] == [f">={ceiling}"], (
            f"{name} ({update['directory']}) declares `<{ceiling}` but ignores "
            f"{condition['versions']}. Moving the pin without moving the ignore "
            "leaves Dependabot proposing the widening the pin exists to refuse."
        )


def test_mcp_ignore_is_mirrored_across_both_pip_ecosystems() -> None:
    """The pin has two halves; ignoring one directory just reopens the PR from the other."""
    ceilings = {
        update["directory"]: condition["versions"]
        for update in _pip_updates_with_ignores()
        for condition in update["ignore"]
        if condition["dependency-name"] == "mcp"
    }
    assert set(ceilings) == set(PIP_MANIFESTS), (
        f"mcp must be ignored in both pip ecosystems, found {sorted(ceilings)}"
    )
    assert len(set(map(tuple, ceilings.values()))) == 1, (
        f"the two halves of the mcp pin disagree: {ceilings}"
    )
