from __future__ import annotations

import hashlib
import re
import tomllib
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = ROOT / "docs" / "evidence"
INDEX = EVIDENCE_DIR / "INDEX.md"
STATUS = ROOT / "docs" / "STATUS.md"
CLAIMS = ROOT / "config" / "project_claims.toml"

SECURITY_DEPENDENCY_HEADING = "## Security and dependency records"
ACCEPTANCE_HEADING = "## Golden topology acceptance records"
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
GOLDEN_ACCEPTANCE_DIGESTS = {
    "docs/perf/golden-flink-submission-2026-07-30.md": (
        "f1494f0f7664816e8be01151af2406e82bcab9a4348af30839dcead039112f21"
    ),
    "docs/perf/golden-operator-acceptance-2026-07-30.md": (
        "31ba968526adab529b93b55440aab3d5e0037c60f83d44ebb5bebfbeeedaa861"
    ),
    "docs/perf/live-iceberg-materialization-2026-08-01.md": (
        "a155f2f10b57acd00d5d74f80c36afdd04a3a501513e3e3dcb806a4c65b0ecc2"
    ),
    "docs/perf/full-lake-to-serving-e2e-2026-08-01.md": (
        "0ffa18a977c4ee3ac96f02a0b57046c26197b9c3796cc88ba672b477e204312b"
    ),
}
GOLDEN_ACCEPTANCE_DATE = "2026-07-30"
LAKE_TO_SERVING_DATE = "2026-08-01"
SUBMISSION_RECORD = "docs/perf/golden-flink-submission-2026-07-30.md"
OPERATOR_RECORD = "docs/perf/golden-operator-acceptance-2026-07-30.md"
ICEBERG_RECORD = "docs/perf/live-iceberg-materialization-2026-08-01.md"
LAKE_TO_SERVING_RECORD = "docs/perf/full-lake-to-serving-e2e-2026-08-01.md"
SUBMISSION_COMMIT = "ca82be5a84a58ae37dd71ef80e785deb8e70dcad"
OPERATOR_COMMIT = "36ed1ecc250ac6c82ccc6f27de1b76a301b17a41"
ICEBERG_RUNTIME = "ed03fc47"
OPERATOR_STAND = "36ed1ec"
GOLDEN_ACCEPTANCE_DATES = {
    SUBMISSION_RECORD: GOLDEN_ACCEPTANCE_DATE,
    OPERATOR_RECORD: GOLDEN_ACCEPTANCE_DATE,
    ICEBERG_RECORD: LAKE_TO_SERVING_DATE,
    LAKE_TO_SERVING_RECORD: LAKE_TO_SERVING_DATE,
}
UNCLAIMED_BOUNDARIES = (
    "full lake-to-serving production e2e",
    "restore/replay",
    "fresh 4h soak plus rollback after traffic",
    "external penetration test",
    "production acceptance",
)
ICEBERG_UNCLAIMED_BOUNDARIES = (
    "kafka source",
    "clickhouse/api",
    "restore/replay",
    "fresh soak or rollback",
    "external penetration test",
    "npm approval",
    "operator acceptance of ed03fc47",
    "production acceptance",
)
LAKE_TO_SERVING_UNCLAIMED_BOUNDARIES = (
    "same-sha operator acceptance",
    "multi-tenant acceptance",
    "restore/replay",
    "fresh soak or rollback",
    "external penetration test",
    "npm approval",
    "production acceptance",
)
CHECKPOINT_READINESS_HEADING = "## Checkpoint and readiness acceptance records"
CHECKPOINT_RECORD = "docs/perf/checkpoint-restore-replay-2026-08-02.md"
READINESS_RECORD = "docs/perf/ready-baselined-checkpoint-hold-2026-08-03.md"
CHECKPOINT_BLOCKER_RECORD = "docs/perf/checkpoint-restore-replay-capacity-blocker-2026-08-01.md"
CANARY_TRAFFIC_RECORD = "docs/perf/golden-4h-soak-canary-failure-2026-08-02.md"
CHECKPOINT_DATE = "2026-08-02"
READINESS_DATE = "2026-08-03"
CHECKPOINT_RUNTIME = "ed03fc47"
CHECKPOINT_TTL_SECONDS = "565"
READINESS_HOLD_SECONDS = "930"
READINESS_COMPLETED_FROM = "7675"
READINESS_COMPLETED_TO = "8614"
STARTUP_FAILURE_CAUSE = "NOT_ALL_REQUIRED_TASKS_RUNNING"
CHECKPOINT_READINESS_DATES = {
    CHECKPOINT_RECORD: CHECKPOINT_DATE,
    READINESS_RECORD: READINESS_DATE,
}
CHECKPOINT_READINESS_DIGESTS = {
    CHECKPOINT_RECORD: ("310e71a056393b6f174d2138438b47a69ea7421ee69c41076da23ee64ef65161"),
    READINESS_RECORD: ("183d001e511a6e333edde00d5d738785d8f35a4d33aa5c602195116275659952"),
}
CHECKPOINT_BLOCKER_DIGEST = "b1288e175d29909f2599d1802a24968098e196851168ff9c032cd21697e0a944"
CHECKPOINT_UNCLAIMED_BOUNDARIES = (
    "four-hour soak",
    "helm rollback",
    "same-sha",
    "external penetration",
    "npm",
    "production acceptance",
)
READINESS_UNCLAIMED_BOUNDARIES = (
    "canary2",
    "four-hour soak",
    "rollback",
    "external penetration",
    "production acceptance",
)
F10_HEADING = "## F-10 rollback and soak-capacity records (2026-08-23)"
ROLLBACK_RECORD = "corrected-rollback-pair-runtime-20260823-01.md"
SOAK_CAPACITY_RECORD = "ci-soak-f02-capacity-decision-20260823-01.md"
PROJECT_CLOSURE = ROOT / "docs" / "PROJECT_CLOSURE.md"
F10_DATE = "2026-08-23"
F10_DATES = {
    ROLLBACK_RECORD: F10_DATE,
    SOAK_CAPACITY_RECORD: F10_DATE,
}
F10_DIGESTS = {
    ROLLBACK_RECORD: ("fc963bd0062a5b41ca13edfd640df0f497fcde8d8030ff1d23387980c6e84fae"),
    SOAK_CAPACITY_RECORD: ("f6e3f906f449816d4fb7a583a4b64ac724c56be794203837608ddbd6f43d3fe9"),
}
F10_SHARED_UNCLAIMED_BOUNDARIES = (
    "fresh four-hour soak plus rollback after traffic",
    "production acceptance",
    "deploy",
    "publication",
)

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

    assert raw_rows, "section has no Markdown table"
    headers = [_normalize_field(cell) for cell in raw_rows[0]]
    body = raw_rows[1:]
    if body and all(SEPARATOR_CELL_RE.fullmatch(cell.replace(" ", "")) for cell in body[0]):
        body = body[1:]
    return headers, body


def _rows_for_heading(heading: str) -> list[dict[str, str]]:
    section = _section(INDEX.read_text(encoding="utf-8"), heading)
    headers, body = _markdown_table(section)
    rows: list[dict[str, str]] = []
    for cells in body:
        assert len(cells) == len(headers), (
            f"expected {len(headers)} columns, got {len(cells)}: {cells!r}"
        )
        rows.append(dict(zip(headers, cells, strict=True)))
    assert rows, f"{heading} table has no data rows"
    return rows


def _security_dependency_rows() -> list[dict[str, str]]:
    return _rows_for_heading(SECURITY_DEPENDENCY_HEADING)


def _acceptance_rows() -> list[dict[str, str]]:
    return _rows_for_heading(ACCEPTANCE_HEADING)


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


def _acceptance_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _acceptance_rows()]


def _checkpoint_readiness_rows() -> list[dict[str, str]]:
    return _rows_for_heading(CHECKPOINT_READINESS_HEADING)


def _checkpoint_readiness_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _checkpoint_readiness_rows()]


def _f10_rows() -> list[dict[str, str]]:
    return _rows_for_heading(F10_HEADING)


def _f10_record_paths() -> list[str]:
    return [_identity_path(row.get("identity", "")) for row in _f10_rows()]


def _project_closure_record_links() -> set[str]:
    found: set[str] = set()
    for target in LINK_RE.findall(PROJECT_CLOSURE.read_text(encoding="utf-8")):
        resolved = (PROJECT_CLOSURE.parent / target).resolve()
        try:
            found.add(resolved.relative_to(ROOT).as_posix())
        except ValueError:
            continue
    return found


def _status_record_links() -> set[str]:
    found: set[str] = set()
    for target in LINK_RE.findall(STATUS.read_text(encoding="utf-8")):
        resolved = (STATUS.parent / target).resolve()
        try:
            found.add(resolved.relative_to(ROOT).as_posix())
        except ValueError:
            continue
    return found


def _row_text(row: dict[str, str]) -> str:
    return f"{row.get('result', '')} {row.get('claim boundary', '')}".lower()


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


def test_golden_acceptance_index_lists_the_bounded_pair_once() -> None:
    indexed = _acceptance_record_paths()
    expected = (
        SUBMISSION_RECORD,
        OPERATOR_RECORD,
        ICEBERG_RECORD,
        LAKE_TO_SERVING_RECORD,
    )

    assert set(indexed) == set(expected)
    assert Counter(indexed) == Counter(expected)
    assert len(indexed) == 4
    for relative in indexed:
        assert (ROOT / relative).is_file(), f"indexed identity is missing: {relative}"
    assert indexed[:2] == [SUBMISSION_RECORD, OPERATOR_RECORD]


def test_golden_acceptance_index_exposes_required_nonempty_fields() -> None:
    rows = _acceptance_rows()
    headers = list(rows[0])

    assert headers == list(REQUIRED_FIELDS)
    assert len(rows) == 4
    for row in rows:
        for field in REQUIRED_FIELDS:
            assert row[field].strip(), f"{field} is empty in {row!r}"
        assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
        identity = _identity_path(row["identity"])
        assert row["date"] == GOLDEN_ACCEPTANCE_DATES[identity]


def test_golden_acceptance_supersession_is_none() -> None:
    for row in _acceptance_rows():
        assert row.get("supersedes", "") == "None"
        assert row.get("superseded by", "") == "None"
        _assert_supersession_cell(row.get("supersedes", ""))
        _assert_supersession_cell(row.get("superseded by", ""))


def test_golden_acceptance_records_keep_published_digests() -> None:
    indexed = set(_acceptance_record_paths())

    assert indexed == set(GOLDEN_ACCEPTANCE_DIGESTS)
    for relative, expected in GOLDEN_ACCEPTANCE_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected


def test_golden_acceptance_claim_links_match_indexed_records() -> None:
    indexed = set(_acceptance_record_paths())
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))
    production = manifest["production"]
    status_links = _status_record_links()

    assert indexed == {
        SUBMISSION_RECORD,
        OPERATOR_RECORD,
        ICEBERG_RECORD,
        LAKE_TO_SERVING_RECORD,
    }
    assert production.get("verified_submission_smoke") == SUBMISSION_RECORD
    assert production.get("verified_operator_acceptance") == OPERATOR_RECORD
    assert production.get("verified_iceberg_materialization") == ICEBERG_RECORD
    assert production.get("verified_full_lake_to_serving_smoke") == LAKE_TO_SERVING_RECORD
    assert production.get("status") == "candidate"
    assert SUBMISSION_RECORD in manifest["required_evidence"]
    assert OPERATOR_RECORD in manifest["required_evidence"]
    assert ICEBERG_RECORD in manifest["required_evidence"]
    assert LAKE_TO_SERVING_RECORD in manifest["required_evidence"]
    assert SUBMISSION_RECORD in status_links
    assert OPERATOR_RECORD in status_links
    assert ICEBERG_RECORD in status_links
    assert LAKE_TO_SERVING_RECORD in status_links


def test_golden_acceptance_boundaries_remain_conservative() -> None:
    rows = {_identity_path(row["identity"]): row for row in _acceptance_rows()}
    submission = _row_text(rows[SUBMISSION_RECORD])
    operator = _row_text(rows[OPERATOR_RECORD])
    iceberg = _row_text(rows[ICEBERG_RECORD])
    lake_to_serving = _row_text(rows[LAKE_TO_SERVING_RECORD])

    assert "pass" in rows[SUBMISSION_RECORD]["result"].lower()
    assert "clean-checkout" in submission
    assert "oci" in submission
    assert "submission" in submission
    assert "running" in submission
    assert SUBMISSION_COMMIT in submission
    assert "pass" in rows[OPERATOR_RECORD]["result"].lower()
    assert "kind" in operator
    assert "operator" in operator
    assert "helm" in operator
    assert "hold" in operator
    assert OPERATOR_COMMIT in operator
    assert "pass" in rows[ICEBERG_RECORD]["result"].lower()
    assert "events.validated" in iceberg
    assert ICEBERG_RUNTIME in iceberg
    assert "lake materializer" in iceberg
    assert "iceberg" in iceberg
    assert "match_count=1" in iceberg
    assert OPERATOR_STAND in iceberg
    assert "pass" in rows[LAKE_TO_SERVING_RECORD]["result"].lower()
    assert "mixed-sha" in lake_to_serving
    assert "orders.raw" in lake_to_serving
    assert OPERATOR_STAND in lake_to_serving
    assert "pyflink" in lake_to_serving
    assert "events.validated" in lake_to_serving
    assert "iceberg" in lake_to_serving
    assert "bridge" in lake_to_serving
    assert "clickhouse" in lake_to_serving
    assert "task api" in lake_to_serving
    assert ICEBERG_RUNTIME in lake_to_serving
    for text in (submission, operator, iceberg, lake_to_serving):
        assert "does not claim" in text
        assert "candidate" in text
    for text in (submission, operator):
        for phrase in UNCLAIMED_BOUNDARIES:
            assert phrase in text
    for phrase in ICEBERG_UNCLAIMED_BOUNDARIES:
        assert phrase in iceberg
    for phrase in LAKE_TO_SERVING_UNCLAIMED_BOUNDARIES:
        assert phrase in lake_to_serving


def test_checkpoint_readiness_section_follows_golden_acceptance() -> None:
    text = INDEX.read_text(encoding="utf-8")
    golden_at = text.index(ACCEPTANCE_HEADING)
    checkpoint_at = text.index(CHECKPOINT_READINESS_HEADING)
    following_at = text.index("## F-10 rollback and soak-capacity records")

    assert golden_at < checkpoint_at < following_at


def test_checkpoint_readiness_index_lists_the_bounded_pair_once() -> None:
    indexed = _checkpoint_readiness_record_paths()
    expected = (CHECKPOINT_RECORD, READINESS_RECORD)

    assert set(indexed) == set(expected)
    assert Counter(indexed) == Counter(expected)
    assert len(indexed) == 2
    for relative in indexed:
        assert (ROOT / relative).is_file(), f"indexed identity is missing: {relative}"
    assert indexed == [CHECKPOINT_RECORD, READINESS_RECORD]
    for row in _checkpoint_readiness_rows():
        targets = LINK_RE.findall(row["identity"])
        assert targets[0].startswith("../perf/"), row["identity"]


def test_checkpoint_readiness_index_exposes_required_nonempty_fields() -> None:
    rows = _checkpoint_readiness_rows()
    headers = list(rows[0])

    assert headers == list(REQUIRED_FIELDS)
    assert len(rows) == 2
    for row in rows:
        for field in REQUIRED_FIELDS:
            assert row[field].strip(), f"{field} is empty in {row!r}"
        assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
        identity = _identity_path(row["identity"])
        assert row["date"] == CHECKPOINT_READINESS_DATES[identity]


def test_checkpoint_readiness_supersession_direction() -> None:
    rows = {_identity_path(row["identity"]): row for row in _checkpoint_readiness_rows()}
    checkpoint = rows[CHECKPOINT_RECORD]
    readiness = rows[READINESS_RECORD]
    supersedes_targets = LINK_RE.findall(checkpoint["supersedes"])

    assert [_resolve_index_link(target) for target in supersedes_targets] == [
        CHECKPOINT_BLOCKER_RECORD
    ]
    assert supersedes_targets[0].startswith("../perf/")
    assert checkpoint["superseded by"] == "None"
    assert readiness["supersedes"] == "None"
    assert readiness["superseded by"] == "None"
    _assert_supersession_cell(checkpoint["supersedes"])
    _assert_supersession_cell(checkpoint["superseded by"])
    _assert_supersession_cell(readiness["supersedes"])
    _assert_supersession_cell(readiness["superseded by"])
    for cell in (readiness["supersedes"], readiness["superseded by"]):
        resolved = [_resolve_index_link(target) for target in LINK_RE.findall(cell)]
        assert CHECKPOINT_RECORD not in resolved
        assert CHECKPOINT_BLOCKER_RECORD not in resolved
        assert CANARY_TRAFFIC_RECORD not in resolved


def test_checkpoint_readiness_records_keep_published_digests() -> None:
    indexed = set(_checkpoint_readiness_record_paths())

    assert indexed == set(CHECKPOINT_READINESS_DIGESTS)
    for relative, expected in CHECKPOINT_READINESS_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    blocker_digest = hashlib.sha256((ROOT / CHECKPOINT_BLOCKER_RECORD).read_bytes()).hexdigest()
    assert blocker_digest == CHECKPOINT_BLOCKER_DIGEST
    for relative, expected in PROTECTED_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    for relative, expected in GOLDEN_ACCEPTANCE_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected


def test_checkpoint_readiness_claim_links_match_indexed_records() -> None:
    indexed = set(_checkpoint_readiness_record_paths())
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))
    production = manifest["production"]
    status_links = _status_record_links()

    assert indexed == {CHECKPOINT_RECORD, READINESS_RECORD}
    assert production.get("verified_checkpoint_restore_replay") == CHECKPOINT_RECORD
    assert production.get("verified_ready_baselined_checkpoint_hold") == (READINESS_RECORD)
    assert production.get("latest_soak_recovery_evidence") == READINESS_RECORD
    assert production.get("status") == "candidate"
    assert CHECKPOINT_RECORD in manifest["required_evidence"]
    assert READINESS_RECORD in manifest["required_evidence"]
    assert CHECKPOINT_RECORD in status_links
    assert READINESS_RECORD in status_links


def test_checkpoint_readiness_boundaries_remain_conservative() -> None:
    rows = {_identity_path(row["identity"]): row for row in _checkpoint_readiness_rows()}
    checkpoint = _row_text(rows[CHECKPOINT_RECORD])
    readiness = _row_text(rows[READINESS_RECORD])

    assert "pass" in rows[CHECKPOINT_RECORD]["result"].lower()
    assert "isolated" in checkpoint
    assert "checkpoint" in checkpoint
    assert "savepoint" in checkpoint
    assert "restore" in checkpoint
    assert CHECKPOINT_RUNTIME in checkpoint
    assert "byte-identical" in checkpoint
    assert "e1" in checkpoint
    assert "e2" in checkpoint
    assert "kafka validated" in checkpoint
    assert "iceberg" in checkpoint
    assert "clickhouse" in checkpoint
    assert "api" in checkpoint
    assert "dlq" in checkpoint
    assert "lag" in checkpoint
    assert CHECKPOINT_TTL_SECONDS in checkpoint
    assert "runtime_hold_pass" in rows[READINESS_RECORD]["result"].lower()
    assert READINESS_HOLD_SECONDS in readiness
    assert "readiness-baselined" in readiness
    assert "read-only" in readiness
    assert "no-traffic" in readiness
    assert "already-running" in readiness
    assert READINESS_COMPLETED_FROM in readiness
    assert READINESS_COMPLETED_TO in readiness
    assert "failed checkpoints 1 to 1" in readiness
    assert STARTUP_FAILURE_CAUSE.lower() in readiness
    assert "does not claim" in checkpoint
    assert "does not prove" in readiness
    assert "candidate" in checkpoint
    assert "candidate" in readiness
    assert "canary" in readiness
    assert "latest traffic" in readiness
    for phrase in CHECKPOINT_UNCLAIMED_BOUNDARIES:
        assert phrase in checkpoint
    for phrase in READINESS_UNCLAIMED_BOUNDARIES:
        assert phrase in readiness


def test_f10_section_follows_checkpoint_readiness() -> None:
    text = INDEX.read_text(encoding="utf-8")
    checkpoint_at = text.index(CHECKPOINT_READINESS_HEADING)
    f10_at = text.index(F10_HEADING)

    assert checkpoint_at < f10_at


def test_f10_section_keeps_root_path_stability() -> None:
    section = _section(INDEX.read_text(encoding="utf-8"), F10_HEADING)

    assert "`docs/STATUS.md`" in section
    assert "`docs/PROJECT_CLOSURE.md`" in section
    assert "`config/project_claims.toml`" in section
    assert "root-path stability" in section
    assert "not new evidence under `docs/evidence/`" in section


def test_f10_index_lists_the_bounded_pair_once() -> None:
    indexed = _f10_record_paths()
    expected = (ROLLBACK_RECORD, SOAK_CAPACITY_RECORD)

    assert set(indexed) == set(expected)
    assert Counter(indexed) == Counter(expected)
    assert len(indexed) == 2
    for relative in indexed:
        assert (ROOT / relative).is_file(), f"indexed identity is missing: {relative}"
    assert indexed == [ROLLBACK_RECORD, SOAK_CAPACITY_RECORD]
    for row in _f10_rows():
        targets = LINK_RE.findall(row["identity"])
        assert targets[0].startswith("../../"), row["identity"]


def test_f10_index_exposes_required_nonempty_fields() -> None:
    rows = _f10_rows()
    headers = list(rows[0])

    assert headers == list(REQUIRED_FIELDS)
    assert len(rows) == 2
    for row in rows:
        for field in REQUIRED_FIELDS:
            assert row[field].strip(), f"{field} is empty in {row!r}"
        assert ISO_DATE_RE.fullmatch(row["date"]), row["date"]
        identity = _identity_path(row["identity"])
        assert row["date"] == F10_DATES[identity]


def test_f10_supersession_is_none() -> None:
    rows = {_identity_path(row["identity"]): row for row in _f10_rows()}
    rollback = rows[ROLLBACK_RECORD]
    soak = rows[SOAK_CAPACITY_RECORD]

    assert rollback["supersedes"] == "None"
    assert rollback["superseded by"] == "None"
    assert soak["supersedes"] == "None"
    assert soak["superseded by"] == "None"
    for row in (rollback, soak):
        _assert_supersession_cell(row["supersedes"])
        _assert_supersession_cell(row["superseded by"])
        resolved_supersedes = [
            _resolve_index_link(target) for target in LINK_RE.findall(row["supersedes"])
        ]
        resolved_superseded_by = [
            _resolve_index_link(target) for target in LINK_RE.findall(row["superseded by"])
        ]
        assert ROLLBACK_RECORD not in resolved_supersedes
        assert SOAK_CAPACITY_RECORD not in resolved_supersedes
        assert ROLLBACK_RECORD not in resolved_superseded_by
        assert SOAK_CAPACITY_RECORD not in resolved_superseded_by


def test_f10_records_keep_published_digests() -> None:
    indexed = set(_f10_record_paths())

    assert indexed == set(F10_DIGESTS)
    for relative, expected in F10_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    for relative, expected in PROTECTED_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    for relative, expected in GOLDEN_ACCEPTANCE_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    for relative, expected in CHECKPOINT_READINESS_DIGESTS.items():
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected
    blocker_digest = hashlib.sha256((ROOT / CHECKPOINT_BLOCKER_RECORD).read_bytes()).hexdigest()
    assert blocker_digest == CHECKPOINT_BLOCKER_DIGEST


def test_f10_claim_links_match_indexed_records() -> None:
    indexed = set(_f10_record_paths())
    manifest = tomllib.loads(CLAIMS.read_text(encoding="utf-8"))
    production = manifest["production"]
    status_links = _status_record_links()
    closure_links = _project_closure_record_links()

    assert indexed == {ROLLBACK_RECORD, SOAK_CAPACITY_RECORD}
    assert production.get("rollback_mechanics_evidence") == ROLLBACK_RECORD
    assert production.get("rollback_mechanics") == "PASS"
    assert production.get("full_soak_plus_rollback_after_traffic_evidence") == (
        SOAK_CAPACITY_RECORD
    )
    assert production.get("full_soak_plus_rollback_after_traffic") == ("BLOCKED_HOST_CAPACITY")
    assert production.get("status") == "candidate"
    assert ROLLBACK_RECORD in manifest["required_evidence"]
    assert SOAK_CAPACITY_RECORD in manifest["required_evidence"]
    assert ROLLBACK_RECORD in status_links
    assert SOAK_CAPACITY_RECORD in status_links
    assert ROLLBACK_RECORD in closure_links
    assert SOAK_CAPACITY_RECORD in closure_links


def test_f10_boundaries_remain_conservative() -> None:
    rows = {_identity_path(row["identity"]): row for row in _f10_rows()}
    rollback = _row_text(rows[ROLLBACK_RECORD])
    soak = _row_text(rows[SOAK_CAPACITY_RECORD])

    assert "pass" in rows[ROLLBACK_RECORD]["result"].lower()
    assert "rev5" in rollback
    assert "rev6" in rollback
    assert "byte-identical" in rollback
    assert "rev3" in rollback
    assert "no traffic" in rollback
    assert "blocked_host_capacity" in rows[SOAK_CAPACITY_RECORD]["result"].lower()
    assert "f-02" in soak
    assert "r17" in soak
    assert "pass" not in rows[SOAK_CAPACITY_RECORD]["result"].lower()
    assert "does not claim" in rollback
    assert "does not claim" in soak
    assert "candidate" in rollback
    assert "candidate" in soak
    for phrase in F10_SHARED_UNCLAIMED_BOUNDARIES:
        assert phrase in rollback
        assert phrase in soak
