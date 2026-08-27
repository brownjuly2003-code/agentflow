from __future__ import annotations

import hashlib
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = ROOT / "docs" / "evidence"
INDEX = EVIDENCE_DIR / "INDEX.md"
STATUS = ROOT / "docs" / "STATUS.md"

SECURITY_DEPENDENCY_HEADING = "## Security and dependency records"
REQUIRED_FIELDS = (
    "identity",
    "date",
    "result",
    "supersedes",
    "superseded by",
    "claim boundary",
)
PROTECTED_DIGESTS = {
    "docs/evidence/security-s12-2026-07-09.md": (
        "4b2223a35e5817214171aedf988b814e2bed97a08bfaa2f817c17d5e05e9108a"
    ),
    "docs/evidence/security-runtime-image-trivy-2026-07-30.md": (
        "6bbb2ebb5ff7f98db11e4f1ceb1af099116ccba806edac2ffc1221db60238d28"
    ),
    "docs/evidence/dependency-compatibility-2026-07-30.md": (
        "79618c9eea6aa31c18a7d17558c995bd424abf620f4e901b2542d1cc3031635f"
    ),
}

LINK_RE = re.compile(r"\[[^]]+\]\(([^)#?]+\.md)\)")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SEPARATOR_CELL_RE = re.compile(r":?-{3,}:?")


def _section(text: str, heading: str) -> str:
    start = text.index(heading) + len(heading)
    end = text.find("\n## ", start)
    return text[start:] if end == -1 else text[start:end]


def _normalize_field(cell: str) -> str:
    return re.sub(r"[\s_-]+", " ", cell.strip().lower())


def _markdown_table(section: str) -> tuple[list[str], list[list[str]]]:
    raw_rows: list[list[str]] = []
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        raw_rows.append(cells)

    assert raw_rows, "security/dependency section has no Markdown table"
    headers = [_normalize_field(cell) for cell in raw_rows[0]]
    body = raw_rows[1:]
    if body and all(SEPARATOR_CELL_RE.fullmatch(cell.replace(" ", "")) for cell in body[0]):
        body = body[1:]
    return headers, body


def _security_dependency_rows() -> list[dict[str, str]]:
    section = _section(INDEX.read_text(encoding="utf-8"), SECURITY_DEPENDENCY_HEADING)
    headers, body = _markdown_table(section)
    rows: list[dict[str, str]] = []
    for cells in body:
        assert len(cells) == len(headers), (
            f"expected {len(headers)} columns, got {len(cells)}: {cells!r}"
        )
        rows.append(dict(zip(headers, cells, strict=True)))
    assert rows, "security/dependency table has no data rows"
    return rows


def _on_disk_evidence_records() -> set[str]:
    return {
        path.relative_to(ROOT).as_posix()
        for path in EVIDENCE_DIR.glob("*.md")
        if path.name != "INDEX.md"
    }


def _resolve_index_link(target: str) -> str:
    return (INDEX.parent / target).resolve().relative_to(ROOT).as_posix()


def _identity_path(cell: str) -> str:
    matches = LINK_RE.findall(cell)
    assert matches, f"identity cell has no markdown path: {cell!r}"
    assert len(matches) == 1, f"identity cell must name one record: {cell!r}"
    return _resolve_index_link(matches[0])


def _indexed_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _security_dependency_rows()]


def _status_evidence_links() -> set[str]:
    found: set[str] = set()
    for target in LINK_RE.findall(STATUS.read_text(encoding="utf-8")):
        resolved = (STATUS.parent / target).resolve()
        try:
            relative = resolved.relative_to(ROOT).as_posix()
        except ValueError:
            continue
        if Path(relative).parent.as_posix() != "docs/evidence":
            continue
        if Path(relative).name == "INDEX.md":
            continue
        found.add(relative)
    return found


def _assert_supersession_cell(cell: str) -> None:
    if cell == "None":
        return
    targets = LINK_RE.findall(cell)
    remainder = LINK_RE.sub("", cell).strip()
    assert targets, f"supersession cell invents an unnamed target: {cell!r}"
    assert remainder == "", f"supersession cell has unnamed leftover text: {cell!r}"
    for target in targets:
        path = ROOT / _resolve_index_link(target)
        assert path.is_file(), f"supersession target does not exist: {target!r}"


def test_security_dependency_index_lists_each_evidence_record_once() -> None:
    indexed = _indexed_record_paths()
    on_disk = _on_disk_evidence_records()

    assert set(indexed) == on_disk
    assert Counter(indexed) == Counter(on_disk)


def test_security_dependency_index_exposes_required_nonempty_fields() -> None:
    rows = _security_dependency_rows()
    headers = list(rows[0])

    assert headers == list(REQUIRED_FIELDS)
    for row in rows:
        for field in REQUIRED_FIELDS:
            assert row[field].strip(), f"{field} is empty in {row!r}"
        assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]


def test_status_evidence_links_match_indexed_records() -> None:
    indexed = set(_indexed_record_paths())

    assert indexed == _status_evidence_links()
    assert indexed == _on_disk_evidence_records()


def test_protected_evidence_records_keep_published_digests() -> None:
    for relative, expected in PROTECTED_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected


def test_supersession_fields_are_none_or_existing_paths() -> None:
    for row in _security_dependency_rows():
        _assert_supersession_cell(row.get("supersedes", ""))
        _assert_supersession_cell(row.get("superseded by", ""))
