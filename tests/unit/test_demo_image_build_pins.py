"""Contract: the API and demo images build from pinned inputs (audit FB-13).

Docker does not run on the Windows development host, so these read Dockerfile
text rather than building an image. What they hold is the property a build
cannot assert about itself: the wheel-build toolchain is pinned to the versions
this repository resolves in `uv.lock`, those pins are the ones that actually
run, and the public Hugging Face demo builds a named ref instead of whatever a
moving branch holds at build time.
"""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
API_DOCKERFILE = PROJECT_ROOT / "Dockerfile.api"
HF_DOCKERFILE = PROJECT_ROOT / "deploy" / "hf-space" / "Dockerfile"
HF_RUNBOOKS = (
    PROJECT_ROOT / "deploy" / "hf-space" / "DEPLOY.md",
    PROJECT_ROOT / "deploy" / "hf-space" / "three-node" / "DEPLOY.md",
)
UV_LOCK = PROJECT_ROOT / "uv.lock"

# `build` runs the PEP 517 hooks; `hatchling` is the backend named by
# pyproject's [build-system]. Together they decide what the wheel contains.
WHEEL_BUILD_TOOLS = ("build", "hatchling")
MOVING_REFS = frozenset({"main", "master", "HEAD", "latest", "dev"})
NAMED_REF = re.compile(r"\A(v\d+\.\d+\.\d+[0-9A-Za-z.\-]*|[0-9a-f]{40})\Z")
ARG_REF = re.compile(r"^ARG AGENTFLOW_REF=(\S+)$", re.MULTILINE)


def _locked_version(name: str) -> str:
    """Return the version `uv.lock` resolves for `name`."""
    text = UV_LOCK.read_text(encoding="utf-8")
    match = re.search(
        rf'^\[\[package\]\]\nname = "{re.escape(name)}"\nversion = "([^"]+)"$',
        text,
        re.MULTILINE,
    )
    assert match is not None, f"{name} is not resolved in uv.lock"
    return match.group(1)


def _dockerfiles() -> dict[str, str]:
    return {
        "Dockerfile.api": API_DOCKERFILE.read_text(encoding="utf-8"),
        "deploy/hf-space/Dockerfile": HF_DOCKERFILE.read_text(encoding="utf-8"),
    }


def _hf_default_ref() -> str:
    matches = ARG_REF.findall(HF_DOCKERFILE.read_text(encoding="utf-8"))
    assert len(matches) == 1, "expected exactly one `ARG AGENTFLOW_REF=` default"
    return matches[0]


def test_wheel_build_toolchain_is_pinned_to_the_locked_versions() -> None:
    for name in WHEEL_BUILD_TOOLS:
        version = _locked_version(name)
        for label, text in _dockerfiles().items():
            assert f"{name}=={version}" in text, (
                f"{label} must install {name}=={version}, the version uv.lock resolves; "
                "move the Dockerfile pin whenever the lock moves"
            )


def test_no_dockerfile_installs_the_build_toolchain_unpinned() -> None:
    for label, text in _dockerfiles().items():
        for line in text.splitlines():
            if "pip install" not in line or line.lstrip().startswith("#"):
                continue
            tokens = line.replace("\\", " ").split()
            for name in WHEEL_BUILD_TOOLS:
                assert name not in tokens, (
                    f"{label}: `pip install ... {name}` takes whatever PyPI serves that "
                    f"minute; pin it as {name}==<the uv.lock version>"
                )


def test_wheel_builds_run_the_pinned_backend() -> None:
    for label, text in _dockerfiles().items():
        invocations = [
            line.strip()
            for line in text.splitlines()
            if "python -m build" in line and not line.lstrip().startswith("#")
        ]
        assert invocations, f"{label} must build the project wheel"
        for line in invocations:
            assert "--no-isolation" in line, (
                f"{label}: `python -m build` defaults to an isolated environment that "
                "installs the backend from PyPI at build time, so the pinned hatchling "
                "would never run -- pass --no-isolation"
            )


def test_hf_demo_image_defaults_to_a_named_ref() -> None:
    default = _hf_default_ref()

    assert default not in MOVING_REFS, (
        f"the public demo must not build a moving branch by default (got {default!r}); "
        "a Factory rebuild would then ship whatever that branch held at that minute"
    )
    assert NAMED_REF.match(default), (
        f"AGENTFLOW_REF default {default!r} must be a vX.Y.Z tag or a 40-character commit sha"
    )
    assert '--branch "${AGENTFLOW_REF}"' in HF_DOCKERFILE.read_text(encoding="utf-8"), (
        "the clone must honour AGENTFLOW_REF, otherwise the default is decorative"
    )


def test_hf_runbooks_document_the_ref_the_dockerfile_builds() -> None:
    default = _hf_default_ref()
    for runbook in HF_RUNBOOKS:
        text = runbook.read_text(encoding="utf-8")
        assert default in text, (
            f"{runbook.relative_to(PROJECT_ROOT)} must name {default}, the ref the shared "
            "Dockerfile actually builds"
        )
        assert "tracks `main`" not in text, (
            f"{runbook.relative_to(PROJECT_ROOT)} still claims the Space tracks `main`; "
            "the default is a named ref now"
        )
