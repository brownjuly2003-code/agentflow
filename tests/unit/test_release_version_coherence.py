"""The version numbers in this repository have to mean the same thing (FB-05, FB-08).

Four separate drifts were shipping at once on 2026-09-07:

* `helm/agentflow/values.yaml` defaulted to `agentflow/api:2.0.0` while
  `Chart.yaml` declared `appVersion: 2.1.0` -- and `agentflow/api` is an
  unclaimed Docker Hub namespace, so with `pullPolicy: IfNotPresent` a dev or
  staging install without a pre-loaded image would pull whatever a third party
  had pushed there (FB-08);
* `Chart.yaml version` sat at the scaffold's `0.1.0` across every app release,
  so no chart consumer could tell two charts apart;
* `integrations/pyproject.toml` read `2.0.0` next to everything else's `2.1.0`,
  with nothing saying whether that was intent or an oversight;
* `CHANGELOG.md` headed a section `## [2.1.0] - 2026-08-23` for a version that
  has no tag and was never published, which reads as a release.

These tests pin the shape rather than the numbers: whatever the versions are,
the chart must ship the app version it declares, the default image must point
at a registry this project owns, the chart version must not be frozen, the
integrations range must still admit the client the lockstep ships, and the
CHANGELOG and STATUS must agree about whether the current version is out.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml
from packaging.specifiers import SpecifierSet
from packaging.version import Version

from scripts import release

ROOT = Path(__file__).resolve().parents[2]
ROOT_PYPROJECT = ROOT / "pyproject.toml"
INTEGRATIONS_PYPROJECT = ROOT / "integrations" / "pyproject.toml"
CHART = ROOT / "helm" / "agentflow" / "Chart.yaml"
VALUES = ROOT / "helm" / "agentflow" / "values.yaml"
CHANGELOG = ROOT / "CHANGELOG.md"
STATUS = ROOT / "docs" / "STATUS.md"

# The registry the container workflow actually publishes to
# (.github/workflows/container-attestation.yml).
OWNED_REGISTRY = "ghcr.io/brownjuly2003-code/"


def _toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _app_version() -> str:
    return str(_toml(ROOT_PYPROJECT)["project"]["version"])


def _minor_line(version: str) -> tuple[int, int]:
    parsed = Version(version)
    return parsed.major, parsed.minor


def test_the_chart_ships_the_app_version_it_declares() -> None:
    """A chart whose default tag names one release and whose appVersion names
    another is lying to `kubectl describe`, which is where an operator looks."""
    chart = _yaml(CHART)
    values = _yaml(VALUES)

    assert str(chart["appVersion"]) == _app_version()
    assert str(values["image"]["tag"]) == str(chart["appVersion"])


def test_the_default_image_points_at_a_registry_the_project_owns() -> None:
    """FB-08. `pullPolicy: IfNotPresent` on an unowned Docker Hub namespace is
    a supply-chain hole with a wait: the day somebody claims the namespace, a
    fresh install pulls their image."""
    repository = str(_yaml(VALUES)["image"]["repository"])

    assert repository.startswith(OWNED_REGISTRY), (
        f"default image.repository is {repository!r}; the chart default must name a "
        "registry this project controls, so an install can never resolve to a "
        "namespace someone else can claim"
    )
    # A reference with no registry host resolves to Docker Hub. Whatever the
    # default becomes, it must not become that again.
    assert "/" in repository
    assert "." in repository.split("/", 1)[0]


def test_the_chart_version_is_not_frozen_at_the_scaffold_default() -> None:
    """`helm create` writes 0.1.0. Leaving it there through several app
    releases means `helm search repo` shows one chart for all of them."""
    chart = _yaml(CHART)
    chart_version = str(chart["version"])

    assert chart_version != "0.1.0"
    assert _minor_line(chart_version) == _minor_line(str(chart["appVersion"])), (
        f"chart version {chart_version} and appVersion {chart['appVersion']} are on "
        "different minor lines; the patch digit is the room for chart-only fixes"
    )


def test_integrations_is_outside_the_release_lockstep_on_purpose() -> None:
    """`scripts/release.py` is the lockstep contract. `agentflow-integrations`
    is not in it and is not published anywhere, so its version standing apart
    is intent -- but that only stays safe while the dependency range holds."""
    managed = set(release.read_versions())

    assert not any("integrations" in path for path in managed)
    assert INTEGRATIONS_PYPROJECT.is_file()


def test_the_integrations_range_still_admits_the_client_the_lockstep_ships() -> None:
    """This is the invariant the version number itself was standing in for. A
    client bump that escapes the range produces an uninstallable pair, and no
    test of the version *number* would have noticed."""
    integrations = _toml(INTEGRATIONS_PYPROJECT)
    requirement = next(
        item
        for item in integrations["project"]["dependencies"]
        if item.replace(" ", "").startswith("agentflow-client")
    )
    specifier = SpecifierSet(requirement.split("agentflow-client", 1)[1].strip())

    assert Version(_app_version()) in specifier, (
        f"agentflow-integrations requires agentflow-client{specifier}, which excludes the "
        f"{_app_version()} the release lockstep ships"
    )


def _changelog_heading(version: str) -> str:
    pattern = re.compile(rf"^## \[{re.escape(version)}\].*$", re.MULTILINE)
    match = pattern.search(CHANGELOG.read_text(encoding="utf-8"))
    assert match is not None, f"CHANGELOG.md has no section for {version}"
    return match.group(0)


def test_the_changelog_and_status_agree_about_whether_this_version_shipped() -> None:
    """A dated heading is a claim that the version is out. While STATUS calls
    2.1.0 unpublished, a reader of the CHANGELOG alone would conclude the
    opposite -- and the two files are read by different people."""
    version = _app_version()
    status = STATUS.read_text(encoding="utf-8")
    heading = _changelog_heading(version)

    # The claim wraps across lines inside a blockquote, so match the phrase
    # rather than one particular line break.
    unpublished = (
        re.search(
            rf"unpublished lockstep\s*(?:>\s*)?[*`]*{re.escape(version)}[*`]*",
            status,
        )
        is not None
    )
    dated = re.fullmatch(rf"## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}", heading)

    if unpublished:
        assert not dated, (
            f"docs/STATUS.md calls {version} unpublished while CHANGELOG.md heads it "
            f"{heading!r}, which reads as a release date"
        )
        assert "unreleased" in heading.lower()
    else:
        assert dated, (
            f"docs/STATUS.md no longer calls {version} unpublished, so CHANGELOG.md "
            f"should carry its release date instead of {heading!r}"
        )
