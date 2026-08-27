from __future__ import annotations

import hashlib
import re
from collections import Counter
from pathlib import Path

from scripts.check_docs_root_placement import load_tracked_paths

ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / "docs" / "operations" / "README.md"

CURRENT_PROCEDURES = {
    "docs/operations/api-duckdb-non-target-scratch-rehearsal-runbook.md",
    "docs/operations/aws-oidc-setup.md",
    "docs/operations/cdc-production-onboarding.md",
    "docs/operations/chaos-runbook.md",
    "docs/operations/ci-soak-next-session-runbook.md",
    "docs/operations/codecov-setup.md",
    "docs/operations/disaster-recovery.md",
    "docs/operations/external-dependency-recovery-gate.md",
    "docs/operations/flink-operators.md",
    "docs/operations/helm-deployment.md",
    "docs/operations/publication-checklist.md",
    "docs/operations/testing-control-plane.md",
    "docs/operations/third-party-pen-test-intake.md",
}

ACTIVE_REFERENCES = {
    "docs/operations/api-duckdb-persistence-recovery-design.md",
    "docs/operations/ci-soak-compose-foundation.md",
    "docs/operations/openssf-security-posture.md",
}

CONSUMED_OR_DATED_RECORDS = {
    "docs/operations/external-pentest-evidence-blocker-2026-08-01.md",
    "docs/operations/npm-environment-approval-2026-08-03.md",
    "docs/operations/npm-environment-approval-blocker-2026-08-01.md",
}

ARCHIVED_SCRATCH_VARIANTS = {
    "docs/archive/operations/api-duckdb-non-target-scratch-rehearsal-e22-2026-08-11.md": (
        "docs/operations/api-duckdb-non-target-scratch-rehearsal-runbook.md",
        "253cfc2d097a53c17fb5072248f3fbaaf4541f83cba86305225b222ead960e74",
    ),
    "docs/archive/operations/api-duckdb-non-target-scratch-rehearsal-e24-2026-08-11.md": (
        "docs/operations/api-duckdb-non-target-scratch-rehearsal-e24-runbook.md",
        "06b4712d26fa603b55f8b0b8c135b965019f3985251208f261e7324def8ad31f",
    ),
    "docs/archive/operations/api-duckdb-non-target-scratch-rehearsal-e26-2026-08-11.md": (
        "docs/operations/api-duckdb-non-target-scratch-rehearsal-e26-runbook.md",
        "cccb106e2da9f38d59a917386b9ab8c57a71f9a603870b4c4c6a4670b27488d9",
    ),
}

ARCHIVE_BODY_MARKER = b"<!-- ARCHIVE BODY START -->\n\n"

LINK_RE = re.compile(r"\[[^]]+\]\(([^)#?]+\.md)\)")


def _section(text: str, heading: str) -> str:
    start = text.index(heading) + len(heading)
    end = text.find("\n## ", start)
    return text[start:] if end == -1 else text[start:end]


def _operation_links(section: str) -> list[str]:
    paths: list[str] = []
    for target in LINK_RE.findall(section):
        resolved = (INDEX.parent / target).resolve().relative_to(ROOT).as_posix()
        if resolved.startswith("docs/operations/"):
            paths.append(resolved)
    return paths


def test_operations_index_partitions_every_tracked_document_once() -> None:
    tracked = load_tracked_paths(ROOT)

    assert tracked is not None
    tracked_operations = {
        path for path in tracked if path.startswith("docs/operations/") and path.endswith(".md")
    }
    assert tracked_operations == (
        CURRENT_PROCEDURES
        | ACTIVE_REFERENCES
        | CONSUMED_OR_DATED_RECORDS
        | {"docs/operations/README.md"}
    )

    text = INDEX.read_text(encoding="utf-8")
    sections = {
        "## Current procedures and controlled gates": CURRENT_PROCEDURES,
        "## Active designs and reference material": ACTIVE_REFERENCES,
        "## Consumed and dated records": CONSUMED_OR_DATED_RECORDS,
    }

    listed: list[str] = []
    for heading, expected in sections.items():
        section_links = _operation_links(_section(text, heading))
        assert set(section_links) == expected
        listed.extend(section_links)

    assert Counter(listed) == Counter(tracked_operations - {"docs/operations/README.md"})


def test_operations_index_has_current_truth_and_navigation_boundaries() -> None:
    text = INDEX.read_text(encoding="utf-8")
    hub = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")

    assert "[Operations index](operations/README.md)" in hub
    assert "[documentation hub](../README.md)" in text
    assert "[engineering status](../STATUS.md)" in text
    assert "[operational runbook](../runbook.md)" in text
    assert "[on-call runbooks](../runbooks/README.md)" in text
    records_section = re.sub(r"\s+", " ", _section(text, "## Consumed and dated records"))
    assert "not current instructions" in records_section


def test_consumed_scratch_variants_are_archived_without_body_changes() -> None:
    tracked = load_tracked_paths(ROOT)

    assert tracked is not None
    for archived_path, (original_path, expected_digest) in ARCHIVED_SCRATCH_VARIANTS.items():
        assert archived_path in tracked
        archive_bytes = (ROOT / archived_path).read_bytes()
        header, marker, body = archive_bytes.partition(ARCHIVE_BODY_MARKER)

        assert marker == ARCHIVE_BODY_MARKER
        assert hashlib.sha256(body).hexdigest() == expected_digest
        header_text = header.decode("utf-8")
        assert f"Original path: *{original_path}*" in header_text
        assert "Archived: 2026-08-27" in header_text
        assert "../../operations/api-duckdb-non-target-scratch-rehearsal-runbook.md" in header_text


def test_current_scratch_guide_is_identity_neutral_and_links_archived_evidence() -> None:
    guide = (
        ROOT / "docs" / "operations" / "api-duckdb-non-target-scratch-rehearsal-runbook.md"
    ).read_text(encoding="utf-8")

    assert "**Status:** `READY_NOT_AUTHORIZED`" in guide
    assert "--run-id $runId" in guide
    assert "--scratch-root $scratchRoot" in guide
    assert "NON_TARGET_SCRATCH_REHEARSAL_ONLY" in guide
    assert "A prepared identity is not authorization" in guide
    for consumed_id in (
        "api-duckdb-scratch-e22-20260811-01",
        "api-duckdb-scratch-e24-20260811-01",
        "api-duckdb-scratch-e26-20260811-01",
    ):
        assert consumed_id not in guide

    operations_index = (ROOT / "docs" / "operations" / "README.md").read_text(encoding="utf-8")
    recovery_design = (
        ROOT / "docs" / "operations" / "api-duckdb-persistence-recovery-design.md"
    ).read_text(encoding="utf-8")
    archive_index = (ROOT / "docs" / "archive" / "operations" / "README.md").read_text(
        encoding="utf-8"
    )
    archive_root = (ROOT / "docs" / "archive" / "README.md").read_text(encoding="utf-8")

    assert "[Current non-target scratch rehearsal]" in operations_index
    assert "[current non-target scratch rehearsal]" in archive_index
    assert "[`operations/`](operations/README.md)" in archive_root
    for archived_path in ARCHIVED_SCRATCH_VARIANTS:
        archive_name = Path(archived_path).name
        relative_link = f"../archive/operations/{archive_name}"
        assert relative_link in operations_index
        assert relative_link in recovery_design
