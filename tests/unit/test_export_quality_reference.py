from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path

import pytest

from scripts import export_quality_reference

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_GENERATED_ARTIFACTS = ("docs/quality.md",)
ARCHIVED_QUALITY_BLOB = "fa449a32dd6f243c92c940be9f75335e2fe39e8c"


def test_generated_artifact_inventory_matches_the_exporter_output() -> None:
    manifest = tomllib.loads((ROOT / "config" / "project_claims.toml").read_text(encoding="utf-8"))

    assert (
        tuple(path.as_posix() for path in export_quality_reference.GENERATED_ARTIFACT_PATHS)
        == EXPECTED_GENERATED_ARTIFACTS
    )
    artifacts = export_quality_reference._build_artifacts(ROOT, manifest)
    assert tuple(path.relative_to(ROOT).as_posix() for path, _text in artifacts) == (
        EXPECTED_GENERATED_ARTIFACTS
    )
    assert artifacts[0][1] == (ROOT / EXPECTED_GENERATED_ARTIFACTS[0]).read_text(encoding="utf-8")


def test_exporter_write_and_check_round_trip(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = ROOT / "config" / "project_claims.toml"
    target_source = tmp_path / "config" / "project_claims.toml"
    target_source.parent.mkdir(parents=True)
    target_source.write_bytes(source.read_bytes())

    assert export_quality_reference.main(["--root", str(tmp_path), "--check"]) == 1
    assert "Quality reference drift detected" in capsys.readouterr().err

    assert export_quality_reference.main(["--root", str(tmp_path)]) == 0
    generated = tmp_path / "docs" / "quality.md"
    assert generated.read_bytes() == (ROOT / "docs" / "quality.md").read_bytes()
    assert b"\r\n" not in generated.read_bytes()
    assert export_quality_reference.main(["--root", str(tmp_path), "--check"]) == 0


def test_quality_reference_docs_name_owners_and_snapshot_lifecycle() -> None:
    docs_hub = " ".join((ROOT / "docs" / "README.md").read_text(encoding="utf-8").split())
    contributing = " ".join((ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8").split())
    current = " ".join((ROOT / "docs" / "quality.md").read_text(encoding="utf-8").split())
    archived = " ".join(
        (ROOT / "docs" / "archive" / "quality-report-2026-07-23.md")
        .read_text(encoding="utf-8")
        .split()
    )
    archive_map = " ".join(
        (ROOT / "docs" / "archive" / "README.md").read_text(encoding="utf-8").split()
    )
    plan = " ".join((ROOT / "plan_26_08_2026.md").read_text(encoding="utf-8").split())

    assert "| Quality gates | `docs/quality.md`" in docs_hub
    assert "`python scripts/export_quality_reference.py`" in docs_hub
    assert "`python scripts/export_quality_reference.py --check`" in docs_hub
    assert "python scripts/export_quality_reference.py" in contributing
    assert "python scripts/export_quality_reference.py --check" in contributing
    assert "python scripts/export_quality_reference.py" in current
    assert ".artifacts/quality/quality-report.md" in current
    assert "archive/quality-report-2026-07-23.md" in current
    assert "Original path: *docs/quality.md*" in archived
    assert "Archived: 2026-08-29" in archived
    assert "Content type: historical generated quality snapshot" in archived
    assert "Generated: `2026-07-23T09:59:55+00:00`" in archived
    assert "quality-report-2026-07-23.md" in archive_map
    assert "Quality generated-reference owner/snapshot sub-slice" in plan
    assert "Пункт 6 остаётся открыт" in plan


def test_archived_quality_report_body_preserves_the_original_git_blob() -> None:
    archived = (ROOT / "docs" / "archive" / "quality-report-2026-07-23.md").read_bytes()
    marker = b"> The report body below is unchanged; only this provenance block was added."
    _metadata, original_tail = archived.split(marker, maxsplit=1)
    original = b"# AgentFlow Quality Report" + original_tail
    git_blob = b"blob " + str(len(original)).encode("ascii") + b"\0" + original

    assert hashlib.sha1(git_blob, usedforsecurity=False).hexdigest() == ARCHIVED_QUALITY_BLOB
