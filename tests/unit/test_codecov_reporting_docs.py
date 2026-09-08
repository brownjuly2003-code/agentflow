"""Contract: pages describing Codecov agree with the workflows (audit FB-16).

Audit F-06 deleted the Codecov upload step and the README badge, and
`tests/unit/test_repository_coverage_artifact.py` holds that workflow side. The
documentation side drifted anyway: `docs/operations/codecov-setup.md` went on
naming a `ci.yml` step, an action version and an input that are not in any
workflow, and `docs/PROJECT_CLOSURE.md` described that upload as non-blocking
reporting. A page that describes a pipeline step nobody can find is worse than
no page. These tests hold the two sides against the same fact.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = PROJECT_ROOT / ".github" / "workflows"
SETUP_PAGE = PROJECT_ROOT / "docs" / "operations" / "codecov-setup.md"
CLAIMS_VALIDATOR = PROJECT_ROOT / "scripts" / "validate_project_claims.py"
CODECOV_CONFIG = PROJECT_ROOT / "codecov.yml"

PAGES_THAT_MENTION_CODECOV = (
    SETUP_PAGE,
    PROJECT_ROOT / "docs" / "PROJECT_CLOSURE.md",
    PROJECT_ROOT / "docs" / "release-readiness.md",
)

NO_UPLOAD_LINE = (
    "**Upload status:** no workflow uploads coverage to Codecov (audit F-06 removed it)."
)

# Sentences that can only be true while a workflow uploads. Each was on a page
# for the five weeks after F-06 removed the step they describe.
UPLOAD_CLAIMS = (
    "calls pinned `codecov/codecov-action`",
    "its upload is non-blocking",
    "coverage badge in `README.md`",
    "`Upload coverage`",
)


def _uncommented(text: str) -> str:
    """Drop YAML comments so ci.yml's record of the F-06 removal is not a mention."""

    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def _workflows_mentioning_codecov() -> list[str]:
    return sorted(
        path.name
        for path in WORKFLOWS_DIR.glob("*.yml")
        if "codecov" in _uncommented(path.read_text(encoding="utf-8")).lower()
    )


def test_no_workflow_step_mentions_codecov() -> None:
    # The action-level check lives in test_repository_coverage_artifact.py; this
    # is the wider premise the documentation below is written against: no step
    # uses, invokes, or configures Codecov. ci.yml's comment explaining why the
    # step is gone is exactly the mention that should not count.
    assert _workflows_mentioning_codecov() == []
    assert "Codecov" in (WORKFLOWS_DIR / "ci.yml").read_text(encoding="utf-8"), (
        "ci.yml must keep the comment recording why the upload was removed"
    )


def test_setup_page_states_the_upload_status_the_workflows_show() -> None:
    text = SETUP_PAGE.read_text(encoding="utf-8")
    uploading = _workflows_mentioning_codecov()

    if uploading:
        assert NO_UPLOAD_LINE not in text, (
            f"{', '.join(uploading)} mention Codecov, so the page must not say no workflow "
            "uploads coverage"
        )
    else:
        assert NO_UPLOAD_LINE in text, (
            "codecov-setup.md must carry the exact upload-status line while no workflow "
            f"uploads coverage: {NO_UPLOAD_LINE!r}"
        )


def test_no_page_claims_an_upload_that_no_workflow_performs() -> None:
    if _workflows_mentioning_codecov():
        return
    for page in PAGES_THAT_MENTION_CODECOV:
        text = page.read_text(encoding="utf-8")
        for claim in UPLOAD_CLAIMS:
            assert claim not in text, (
                f"{page.relative_to(PROJECT_ROOT)} claims {claim!r}, but no workflow uploads "
                "coverage to Codecov"
            )


def test_readme_carries_no_coverage_badge_while_nothing_uploads() -> None:
    if _workflows_mentioning_codecov():
        return
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8").lower()
    assert "codecov" not in readme, "audit F-06 removed the badge; it cannot resolve"


def test_retained_codecov_config_has_a_documented_reason_to_exist() -> None:
    assert CODECOV_CONFIG.is_file()
    # The file is not dead weight: the required `lint` job reads it.
    assert "codecov.yml" in CLAIMS_VALIDATOR.read_text(encoding="utf-8")
    page = SETUP_PAGE.read_text(encoding="utf-8")
    assert "scripts/validate_project_claims.py" in page, (
        "the page must say why an unused-looking config file is still tracked"
    )
