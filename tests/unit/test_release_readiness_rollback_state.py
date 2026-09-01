"""AF-08: the release-readiness page must not report a stale rollback state.

`docs/release-readiness.md` used to say, in two places, that the corrected
Helm rollback "was not started". That is true only of the 2026-08-08 soak-05
attempt. Since then the corrected rollback *mechanics* PASSed on 2026-08-23
without traffic, while rollback *after* sustained soak traffic is still
`BLOCKED_HOST_CAPACITY`, so the combined soak/rollback acceptance gate stays
open. `docs/STATUS.md` already carries that split; this suite pins the page to
it so the historical sentence can never read as the current state again.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PAGE = ROOT / "docs" / "release-readiness.md"
STATUS = ROOT / "docs" / "STATUS.md"

MECHANICS_LINK = "../corrected-rollback-pair-runtime-20260823-01.md"
CAPACITY_LINK = "../ci-soak-f02-capacity-decision-20260823-01.md"

# Every site that keeps the historical "not started" clause must also carry
# the date it belongs to and the current, contradicting truth.
# The date must be scoped in prose, not merely present in an evidence link
# filename (perf/golden-4h-soak-05-failure-2026-08-08.md), or the pin is vacuous.
SCOPED_DATE = "in that 2026-08-08 attempt"

REQUIRED_IN_PARAGRAPH = (
    SCOPED_DATE,
    "byte-identical to revision 3",
    "BLOCKED_HOST_CAPACITY",
    "does not close this gate",
)


def _page_text() -> str:
    return PAGE.read_text(encoding="utf-8")


def _paragraphs(text: str) -> list[str]:
    return text.split("\n\n")


def _not_started_paragraphs(text: str) -> list[str]:
    return [paragraph for paragraph in _paragraphs(text) if "not started" in paragraph]


def test_not_started_sites_carry_their_date_and_the_current_state() -> None:
    text = _page_text()
    selected = _not_started_paragraphs(text)
    assert len(selected) == 2, (
        f"expected exactly two 'not started' paragraphs, found {len(selected)}"
    )
    for paragraph in selected:
        for phrase in REQUIRED_IN_PARAGRAPH:
            assert phrase in paragraph, f"missing {phrase!r} beside 'not started' in: {paragraph}"


def test_both_sites_link_the_two_root_rollback_records() -> None:
    text = _page_text()
    assert text.count(MECHANICS_LINK) >= 2, f"{MECHANICS_LINK} cited {text.count(MECHANICS_LINK)}x"
    assert text.count(CAPACITY_LINK) >= 2, f"{CAPACITY_LINK} cited {text.count(CAPACITY_LINK)}x"
    for link in (MECHANICS_LINK, CAPACITY_LINK):
        target = ROOT / link.removeprefix("../")
        assert target.is_file(), f"cited record missing on disk: {target}"


def test_no_undated_not_started_rollback_claim_remains() -> None:
    text = _page_text()
    undated = [
        paragraph
        for paragraph in _paragraphs(text)
        if "rollback" in paragraph and "not started" in paragraph and SCOPED_DATE not in paragraph
    ]
    assert undated == [], f"undated 'rollback ... not started' claim: {undated}"


def test_status_page_still_carries_the_state_being_aligned_to() -> None:
    status = STATUS.read_text(encoding="utf-8")
    assert "BLOCKED_HOST_CAPACITY" in status
    assert MECHANICS_LINK in status
