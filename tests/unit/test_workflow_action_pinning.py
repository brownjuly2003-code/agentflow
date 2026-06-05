"""Policy: every workflow action is pinned to a full commit SHA.

OpenSSF Scorecard's Pinned-Dependencies check (the repo's $0 posture channel,
docs/operations/openssf-security-posture.md) flags mutable `uses:` refs —
a moved tag silently changes the code that runs in CI with the repository's
token. Convention enforced here:

    uses: owner/repo[/subpath]@<40-hex-commit-sha> # <human-readable version>

The trailing comment is load-bearing: YAML parsing drops it, but Dependabot
reads it to map the SHA back to a release, so `github-actions` ecosystem
updates keep working against SHA pins. Local actions (`./...`) are exempt —
they ride the checked-out commit already.
"""

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = PROJECT_ROOT / ".github" / "workflows"

_USES_LINE = re.compile(r"^\s*(?:-\s+)?uses:\s*(?P<ref>\S+)(?P<rest>.*)$")
_SHA_PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
_VERSION_COMMENT = re.compile(r"^\s+#\s*\S+")


def _uses_lines() -> list[tuple[str, int, str, str]]:
    found = []
    for workflow in sorted(WORKFLOWS_DIR.glob("*.yml")):
        for lineno, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), start=1):
            match = _USES_LINE.match(line)
            if match:
                found.append((workflow.name, lineno, match.group("ref"), match.group("rest")))
    return found


def test_workflows_exist_and_reference_actions() -> None:
    # Guard the policy test itself: if globbing breaks, fail loudly instead
    # of green-on-empty.
    assert _uses_lines(), "no uses: lines found under .github/workflows"


def test_every_action_is_pinned_to_a_full_commit_sha() -> None:
    offenders = [
        f"{name}:{lineno}: {ref}"
        for name, lineno, ref, _ in _uses_lines()
        if not ref.startswith("./") and not _SHA_PINNED.fullmatch(ref)
    ]
    assert not offenders, "actions not pinned to a 40-hex commit SHA:\n" + "\n".join(offenders)


def test_every_sha_pin_carries_a_version_comment() -> None:
    offenders = [
        f"{name}:{lineno}: {ref}"
        for name, lineno, ref, rest in _uses_lines()
        if not ref.startswith("./") and not _VERSION_COMMENT.match(rest)
    ]
    assert not offenders, (
        "SHA-pinned actions missing the trailing '# <version>' comment "
        "(Dependabot needs it to track releases):\n" + "\n".join(offenders)
    )
