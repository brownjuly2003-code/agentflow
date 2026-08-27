from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from scripts.check_docs_root_placement import load_tracked_paths

ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / "docs" / "operations" / "README.md"

CURRENT_PROCEDURES = {
    "docs/operations/api-duckdb-non-target-scratch-rehearsal-e26-runbook.md",
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
    "docs/operations/api-duckdb-non-target-scratch-rehearsal-e24-runbook.md",
    "docs/operations/api-duckdb-non-target-scratch-rehearsal-runbook.md",
    "docs/operations/external-pentest-evidence-blocker-2026-08-01.md",
    "docs/operations/npm-environment-approval-2026-08-03.md",
    "docs/operations/npm-environment-approval-blocker-2026-08-01.md",
}

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
