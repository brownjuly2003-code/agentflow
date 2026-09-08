from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_docs_orphans import (
    check_docs_orphans,
    is_living_page,
    load_tracked_paths,
    main,
    outbound_targets,
)

ROOT = Path(__file__).resolve().parents[2]

ORPHAN_PROBLEM = "docs/orphan.md: no inbound link from any tracked Markdown page or mkdocs nav"


def _write(root: Path, relative: str, body: str) -> None:
    path = root.joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8", newline="\n")


def test_real_docs_tree_has_no_orphans() -> None:
    assert check_docs_orphans(ROOT) == []
    tracked = load_tracked_paths(ROOT)
    assert tracked is not None
    living = [path for path in tracked if is_living_page(path)]
    assert len(living) >= 55


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("docs/architecture.md", True),
        ("docs/README.md", False),
        ("docs/index.md", False),
        ("docs/perf/x.md", False),
        ("docs/dv2-multi-branch/architecture.md", False),
        ("README.md", False),
        ("docs/x.txt", False),
    ],
)
def test_is_living_page_truth_table(path: str, expected: bool) -> None:
    assert is_living_page(path) is expected


def test_outbound_targets_resolves_relative_strips_anchors_and_skips_urls() -> None:
    source = "docs/plans/example.md"
    text = (
        "See [migration](../clickhouse-migration.md#cutover) and "
        "[remote](https://example.com/x.md) plus [mail](mailto:ops@example.com).\n"
        "Also [named][guide].\n"
        "\n"
        "[guide]: ../glossary.md\n"
    )
    assert outbound_targets(source, text) == {
        "docs/clickhouse-migration.md",
        "docs/glossary.md",
    }


def test_orphan_is_reported_with_exact_string(tmp_path: Path) -> None:
    _write(tmp_path, "docs/README.md", "# Hub\n")
    _write(tmp_path, "docs/orphan.md", "# Orphan\n")
    assert check_docs_orphans(tmp_path, tracked_paths={"docs/README.md", "docs/orphan.md"}) == [
        ORPHAN_PROBLEM
    ]


def test_page_linked_from_a_root_record_passes(tmp_path: Path) -> None:
    _write(tmp_path, "CHANGELOG.md", "See [living](docs/living.md).\n")
    _write(tmp_path, "docs/README.md", "# Hub\n")
    _write(tmp_path, "docs/living.md", "# Living\n")
    tracked = {"CHANGELOG.md", "docs/README.md", "docs/living.md"}
    assert check_docs_orphans(tmp_path, tracked_paths=tracked) == []


def test_page_linked_only_via_mkdocs_nav_passes(tmp_path: Path) -> None:
    _write(tmp_path, "docs/README.md", "# Hub\n")
    _write(tmp_path, "docs/living.md", "# Living\n")
    _write(tmp_path, "mkdocs.yml", "nav:\n  - Living: living.md\n")
    tracked = {"docs/README.md", "docs/living.md"}
    assert check_docs_orphans(tmp_path, tracked_paths=tracked) == []


def test_entrypoint_without_inbound_passes(tmp_path: Path) -> None:
    _write(tmp_path, "docs/README.md", "# Hub\n")
    _write(tmp_path, "docs/index.md", "# Index\n")
    tracked = {"docs/README.md", "docs/index.md"}
    assert check_docs_orphans(tmp_path, tracked_paths=tracked) == []


def test_historical_page_without_inbound_is_not_reported(tmp_path: Path) -> None:
    _write(tmp_path, "docs/README.md", "# Hub\n")
    _write(tmp_path, "docs/perf/snap.md", "# Snapshot\n")
    _write(tmp_path, "docs/dv2-multi-branch/architecture.md", "# Experiment\n")
    tracked = {
        "docs/README.md",
        "docs/perf/snap.md",
        "docs/dv2-multi-branch/architecture.md",
    }
    assert check_docs_orphans(tmp_path, tracked_paths=tracked) == []


def test_self_link_does_not_count_as_inbound(tmp_path: Path) -> None:
    _write(tmp_path, "docs/README.md", "# Hub\n")
    _write(tmp_path, "docs/orphan.md", "See [self](orphan.md).\n")
    assert check_docs_orphans(tmp_path, tracked_paths={"docs/README.md", "docs/orphan.md"}) == [
        ORPHAN_PROBLEM
    ]


def test_main_passing_fixture_prints_ok(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(tmp_path, "docs/README.md", "[living](living.md)\n")
    _write(tmp_path, "docs/living.md", "# Living\n")
    monkeypatch.setattr(
        "scripts.check_docs_orphans.load_tracked_paths",
        lambda root: {"docs/README.md", "docs/living.md"},
    )
    assert main(["--root", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "docs orphans: OK (1 living pages)\n"


def test_main_failing_fixture_returns_1(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(tmp_path, "docs/README.md", "# Hub\n")
    _write(tmp_path, "docs/orphan.md", "# Orphan\n")
    monkeypatch.setattr(
        "scripts.check_docs_orphans.load_tracked_paths",
        lambda root: {"docs/README.md", "docs/orphan.md"},
    )
    assert main(["--root", str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert ORPHAN_PROBLEM in output
    assert "docs orphans: OK" not in output


def test_main_empty_tree_returns_1(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(tmp_path, "docs/README.md", "# Hub\n")
    monkeypatch.setattr(
        "scripts.check_docs_orphans.load_tracked_paths",
        lambda root: {"docs/README.md"},
    )
    assert main(["--root", str(tmp_path)]) == 1
    assert "docs orphans: OK" not in capsys.readouterr().out
