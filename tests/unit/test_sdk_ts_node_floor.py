"""The SDK's declared Node floor, the Node versions CI pins, and the lockfile
must agree (audit F-11, second occurrence).

`sdk-ts/package.json` publishes an `engines.node` floor, and three things drift
away from it independently. Each already has:

* the Node version the required `sdk-ts` job installs. It stayed on 20 while
  Vitest 5 declared ``^22.12.0 || ^24.0.0 || >=26.0.0``; npm printed
  ``npm warn EBADENGINE`` and PR #252 went green on a toolchain the runner's
  Node did not support.
* the lockfile's own copy of ``engines``. Commit 0988a0d raised package.json to
  ``>=20`` without regenerating `sdk-ts/package-lock.json`, so the lock kept
  claiming ``>=18`` until a Dependabot bump happened to rewrite it.
* the other lanes that run ``npm ci`` from `sdk-ts/` -- security.yml's
  `npm-audit` and publish-npm.yml -- which carry their own `node-version` pins
  and were never part of the floor decision.

`sdk-ts/.npmrc` (``engine-strict=true``) catches a mismatch between the Node
that is actually installed and any `engines.node` range, ours or a
dependency's, at install time. This test covers what npm cannot see: that the
versions the workflows *pin* are the ones the package claims, checked before a
runner is ever provisioned.

Deliberately out of scope: whether a Node line is still supported upstream.
That is a dated judgement -- recorded in `sdk-ts/CHANGELOG.md` when the floor
moves -- not something a unit test can keep true offline.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SDK_TS = PROJECT_ROOT / "sdk-ts"
WORKFLOWS = PROJECT_ROOT / ".github" / "workflows"

# Every step that installs the SDK's dependencies runs from this directory, so
# it is also the directory whose .npmrc npm reads.
SDK_TS_WORKDIR = "sdk-ts"

# The only setup-node expression the sdk-ts lanes use; anything else has to be
# taught to this guard rather than silently skipped.
MATRIX_NODE_VERSION = "${{ matrix.node-version }}"


def _package_json() -> dict:
    return json.loads((SDK_TS / "package.json").read_text(encoding="utf-8"))


def _package_lock() -> dict:
    return json.loads((SDK_TS / "package-lock.json").read_text(encoding="utf-8"))


def _floor_major() -> int:
    """The declared floor, as a major version.

    The floor is required to be a bare ``>=N``: anything richer (a range, an
    upper bound, an ``||``) would need real semver logic to compare against a
    workflow pin, and this file exists to avoid re-implementing that.
    """
    declared = _package_json()["engines"]["node"]
    match = re.fullmatch(r">=(\d+)", declared.strip())
    assert match is not None, (
        f"sdk-ts/package.json engines.node is {declared!r}; this guard only "
        "understands a bare '>=N' floor. Widen the guard deliberately before "
        "widening the range."
    )
    return int(match.group(1))


def _major(node_version: str) -> int:
    return int(str(node_version).split(".", 1)[0])


def _node_versions(job: dict) -> list[str]:
    """Every Node version a job's setup-node steps install, matrix resolved."""
    versions: list[str] = []
    for step in job.get("steps") or []:
        if "actions/setup-node" not in str(step.get("uses", "")):
            continue
        requested = (step.get("with") or {}).get("node-version")
        if requested is None:
            continue
        requested = str(requested).strip()
        if not requested.startswith("${{"):
            versions.append(requested)
            continue
        assert requested == MATRIX_NODE_VERSION, (
            f"unsupported node-version expression {requested!r}; this guard "
            "resolves only the matrix reference the sdk-ts lanes use."
        )
        matrix = ((job.get("strategy") or {}).get("matrix") or {}).get("node-version")
        assert matrix, "a matrix node-version reference needs strategy.matrix.node-version"
        versions.extend(str(entry) for entry in matrix)
    return versions


def _workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _npm_ci_lanes() -> dict[str, list[str]]:
    """Map ``workflow.yml:job`` to its pinned Node versions, for every lane that
    runs ``npm ci`` inside sdk-ts."""
    lanes: dict[str, list[str]] = {}
    for path in sorted(WORKFLOWS.glob("*.yml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for job_name, job in (workflow.get("jobs") or {}).items():
            job_workdir = ((job.get("defaults") or {}).get("run") or {}).get("working-directory")
            for step in job.get("steps") or []:
                workdir = step.get("working-directory", job_workdir)
                if workdir != SDK_TS_WORKDIR:
                    continue
                if re.search(r"\bnpm ci\b", str(step.get("run", ""))):
                    lanes[f"{path.name}:{job_name}"] = _node_versions(job)
                    break
    return lanes


def test_declared_floor_is_a_plain_minimum() -> None:
    assert _floor_major() >= 22, (
        "the floor may only move forward; Node 20 went end-of-life 2026-04-30 "
        "and Vitest 5 cannot run on it"
    )


def test_lockfile_root_mirrors_the_manifest() -> None:
    """The drift that actually happened: package.json moved, the lock did not."""
    manifest = _package_json()
    lock_root = _package_lock()["packages"][""]
    assert lock_root["engines"] == manifest["engines"]
    assert lock_root["devDependencies"] == manifest["devDependencies"]
    assert lock_root["version"] == manifest["version"]


def test_required_sdk_ts_job_runs_exactly_the_declared_floor() -> None:
    versions = _node_versions(_workflow("ci.yml")["jobs"]["sdk-ts"])
    assert [_major(version) for version in versions] == [_floor_major()], (
        "the required lane is what proves the floor is runnable, so it pins the "
        "floor itself and nothing else"
    )


def test_compat_lane_covers_a_release_above_the_floor() -> None:
    versions = _node_versions(_workflow("ci.yml")["jobs"]["sdk-ts-compat"])
    assert versions, "sdk-ts-compat must install at least one Node version"
    assert all(_major(version) > _floor_major() for version in versions), (
        "the compat lane exists to cover the next LTS; pinned at the floor it "
        "would duplicate the required job"
    )


def test_every_npm_ci_lane_pins_node_at_or_above_the_floor() -> None:
    lanes = _npm_ci_lanes()
    assert set(lanes) == {
        "ci.yml:sdk-ts",
        "ci.yml:sdk-ts-compat",
        "publish-npm.yml:publish",
        "security.yml:npm-audit",
    }, f"unexpected set of sdk-ts npm ci lanes: {sorted(lanes)}"
    for lane, versions in lanes.items():
        assert versions, f"{lane} runs npm ci without pinning a Node version"
        for version in versions:
            assert _major(version) >= _floor_major(), (
                f"{lane} installs Node {version}, below the declared floor >={_floor_major()}"
            )


def test_npmrc_turns_an_engine_mismatch_into_a_failed_install() -> None:
    lines = [
        line.strip()
        for line in (SDK_TS / ".npmrc").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert "engine-strict=true" in lines, (
        "without engine-strict npm downgrades EBADENGINE to a warning and the "
        "lane stays green -- exactly how PR #252 passed on Node 20"
    )
    assert not any(re.match(r"(_auth|_authToken|//)", line) for line in lines), (
        "sdk-ts/.npmrc is tracked; credentials must not be added to it"
    )
