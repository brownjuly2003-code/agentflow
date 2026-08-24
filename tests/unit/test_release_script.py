from __future__ import annotations

import json
import tomllib
from pathlib import Path

from scripts import release


def _write_release_files(root: Path, version: str) -> None:
    (root / "sdk" / "agentflow").mkdir(parents=True)
    (root / "sdk-ts").mkdir()
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "agentflow-runtime"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    (root / "sdk" / "pyproject.toml").write_text(
        f'[project]\nname = "agentflow-client"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    (root / "sdk" / "agentflow" / "__init__.py").write_text(
        f'__version__ = "{version}"\n',
        encoding="utf-8",
    )
    package = {"name": "@yuliaedomskikh/agentflow-client", "version": version}
    (root / "sdk-ts" / "package.json").write_text(
        json.dumps(package, indent=2) + "\n",
        encoding="utf-8",
    )
    package_lock = {
        "name": package["name"],
        "version": version,
        "lockfileVersion": 3,
        "packages": {"": package},
    }
    (root / "sdk-ts" / "package-lock.json").write_text(
        json.dumps(package_lock, indent=2) + "\n",
        encoding="utf-8",
    )


def _redirect_release_paths(monkeypatch, root: Path) -> None:
    monkeypatch.setattr(release, "ROOT_PYPROJECT_PATH", root / "pyproject.toml")
    monkeypatch.setattr(release, "SDK_PYPROJECT_PATH", root / "sdk" / "pyproject.toml")
    monkeypatch.setattr(release, "PACKAGE_JSON_PATH", root / "sdk-ts" / "package.json")
    monkeypatch.setattr(release, "PACKAGE_LOCK_PATH", root / "sdk-ts" / "package-lock.json")
    monkeypatch.setattr(release, "INIT_PATH", root / "sdk" / "agentflow" / "__init__.py")


def test_release_versions_are_lockstep_in_repository() -> None:
    versions = release.read_versions()

    assert set(versions) == {
        "pyproject.toml",
        "sdk/pyproject.toml",
        "sdk/agentflow/__init__.py",
        "sdk-ts/package.json",
        "sdk-ts/package-lock.json",
        'sdk-ts/package-lock.json#packages[""]',
    }
    assert release.ensure_versions_match(versions) == "2.1.0"


def test_release_script_updates_every_lockstep_manifest(monkeypatch, tmp_path: Path) -> None:
    _write_release_files(tmp_path, "2.1.0")
    _redirect_release_paths(monkeypatch, tmp_path)

    release.update_release_versions("2.2.0")

    versions = release.read_versions()
    assert set(versions.values()) == {"2.2.0"}
    assert (
        tomllib.loads((tmp_path / "pyproject.toml").read_text(encoding="utf-8"))["project"][
            "version"
        ]
        == "2.2.0"
    )
    package_lock = json.loads(
        (tmp_path / "sdk-ts" / "package-lock.json").read_text(encoding="utf-8")
    )
    assert package_lock["version"] == "2.2.0"
    assert package_lock["packages"][""]["version"] == "2.2.0"
