"""P2-1 ratchet: authoritative docs must match the shipped runtime.

The 2026-07-11 audit found the repo had lost its single source of truth:
the FastAPI/OpenAPI version froze at 1.0.0 while the package moved to
2.0.0, SECURITY.md supported a release line that no longer exists, and
authoritative pages referenced modules deleted months earlier. `mkdocs
build --strict` never sees most of these files (mkdocs.yml excludes
them), so this suite is the reference checker CI actually runs.

Point-in-time records (ADRs, dated perf/audit reports, the CHANGELOG)
are exempt from the removed-path scan: they describe the repo as it was,
not as it is.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

# Docs that make claims about the CURRENT state of the system. Dated
# reports and ADRs under docs/ stay historical on purpose.
AUTHORITATIVE_DOCS = (
    "README.md",
    "SECURITY.md",
    "docs/architecture.md",
    "docs/security-audit.md",
    "docs/release-readiness.md",
    "docs/deployment.md",
    "docs/runbook.md",
)

# Modules the runtime deleted; a current-state doc citing one as evidence
# is describing a control that no longer exists (audit P2-1).
REMOVED_PATHS = (
    "src/serving/masking.py",
    "src/serving/pii_policy.py",
    "config/pii_fields.yaml",
    "tests/unit/test_masking.py",
)

# Directories whose *.md files are point-in-time records.
HISTORICAL_DOC_DIRS = (
    "docs/decisions",
    "docs/perf",
    "docs/dv2-multi-branch",
    "docs/migration",
)


def _package_version() -> str:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return pyproject["project"]["version"]


def _current_state_docs() -> list[Path]:
    docs = [ROOT / "README.md", ROOT / "SECURITY.md"]
    for path in sorted((ROOT / "docs").rglob("*.md")):
        relative = path.relative_to(ROOT).as_posix()
        if any(relative.startswith(prefix + "/") for prefix in HISTORICAL_DOC_DIRS):
            continue
        docs.append(path)
    return docs


def test_runtime_version_helper_reports_the_package_version() -> None:
    # The source checkout outranks installed distribution metadata: an
    # editable install records the version at install time and goes stale
    # the moment pyproject.toml is bumped.
    from src.version import runtime_version

    assert runtime_version() == _package_version()


def test_fastapi_app_reports_the_package_version() -> None:
    from src.serving.api.main import app

    assert app.version == _package_version()


def test_committed_openapi_artifact_carries_the_package_version() -> None:
    spec = json.loads((ROOT / "docs" / "openapi.json").read_text(encoding="utf-8"))

    assert spec["info"]["version"] == _package_version()


def test_helm_chart_app_version_matches_the_package() -> None:
    chart = yaml.safe_load((ROOT / "helm" / "agentflow" / "Chart.yaml").read_text(encoding="utf-8"))

    assert str(chart["appVersion"]) == _package_version()


def test_security_policy_supports_the_current_major_line() -> None:
    major = _package_version().split(".")[0]
    text = (ROOT / "SECURITY.md").read_text(encoding="utf-8")

    # Exactly one "(current)" row in the supported-versions table, and it
    # names the major line the package actually ships.
    current_lines = re.findall(r"`(\d+)\.x`\s*\(current\)", text)
    assert current_lines == [major]
    assert f"`v{major}.x` line" in text or f"`{major}.x` line" in text


def test_release_readiness_tracks_the_current_release_line() -> None:
    text = (ROOT / "docs" / "release-readiness.md").read_text(encoding="utf-8")

    match = re.search(r"\*\*Release line\*\*: `v(\d+\.\d+\.\d+)`", text)
    assert match is not None, "release-readiness.md lost its release-line header"
    assert match.group(1) == _package_version()

    # The doc may not claim a required-check count that contradicts its own
    # enumerated list (the audit caught "12" against a 13-check reality).
    counts = {int(n) for n in re.findall(r"(\d+) required status checks", text)}
    listed = re.search(r"required status checks[^\n]*—([^.]+)\.", text)
    assert listed is not None, "release-readiness.md no longer enumerates the checks"
    check_names = re.findall(r"`([a-z0-9-]+)`", listed.group(1))
    assert counts == {len(check_names)}, (
        f"claimed count(s) {sorted(counts)} != enumerated {len(check_names)} checks"
    )


def test_current_state_docs_do_not_cite_removed_modules() -> None:
    offenders: list[str] = []
    for doc in _current_state_docs():
        text = doc.read_text(encoding="utf-8")
        for removed in REMOVED_PATHS:
            if removed in text:
                offenders.append(f"{doc.relative_to(ROOT).as_posix()} -> {removed}")

    assert offenders == []


def test_current_state_docs_carry_no_replacement_characters() -> None:
    # U+FFFD in a committed doc means an encoding accident already
    # happened; the next save can only make it worse.
    offenders = [
        doc.relative_to(ROOT).as_posix()
        for doc in _current_state_docs()
        if "�" in doc.read_text(encoding="utf-8")
    ]

    assert offenders == []


def test_authoritative_docs_relative_links_resolve() -> None:
    link_pattern = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
    offenders: list[str] = []
    for name in AUTHORITATIVE_DOCS:
        doc = ROOT / name
        for target in link_pattern.findall(doc.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            resolved = (doc.parent / target.split("#", 1)[0]).resolve()
            if not resolved.exists():
                offenders.append(f"{name} -> {target}")

    assert offenders == []
