from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from scripts import export_sdk_capabilities

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_GENERATED_ARTIFACTS = ("docs/sdk-capabilities.md",)


def test_generated_artifact_inventory_matches_the_exporter_output() -> None:
    manifest = tomllib.loads((ROOT / "config" / "project_claims.toml").read_text(encoding="utf-8"))

    assert (
        tuple(path.as_posix() for path in export_sdk_capabilities.GENERATED_ARTIFACT_PATHS)
        == EXPECTED_GENERATED_ARTIFACTS
    )
    artifacts = export_sdk_capabilities._build_artifacts(ROOT, manifest)
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

    assert export_sdk_capabilities.main(["--root", str(tmp_path), "--check"]) == 1
    assert "SDK capability drift detected" in capsys.readouterr().err

    assert export_sdk_capabilities.main(["--root", str(tmp_path)]) == 0
    generated = tmp_path / "docs" / "sdk-capabilities.md"
    assert generated.read_bytes() == (ROOT / "docs" / "sdk-capabilities.md").read_bytes()
    assert b"\r\n" not in generated.read_bytes()
    assert export_sdk_capabilities.main(["--root", str(tmp_path), "--check"]) == 0


def test_sdk_generated_reference_docs_name_owner_commands_and_lifecycle() -> None:
    docs_hub = " ".join((ROOT / "docs" / "README.md").read_text(encoding="utf-8").split())
    contributing = " ".join((ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8").split())
    generated = " ".join(
        (ROOT / "docs" / "sdk-capabilities.md").read_text(encoding="utf-8").split()
    )
    plan = " ".join((ROOT / "plan_26_08_2026.md").read_text(encoding="utf-8").split())

    assert "| SDK capabilities | `docs/sdk-capabilities.md`" in docs_hub
    assert "`python scripts/export_sdk_capabilities.py`" in docs_hub
    assert "`python scripts/export_sdk_capabilities.py --check`" in docs_hub
    assert "config/project_claims.toml" in docs_hub
    assert "python scripts/export_sdk_capabilities.py" in contributing
    assert "python scripts/export_sdk_capabilities.py --check" in contributing
    assert "python scripts/export_sdk_capabilities.py" in generated
    assert "SDK capability generated-reference owner/drift sub-slice" in plan
    assert "Пункт 6 остаётся открыт" in plan
