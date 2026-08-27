from __future__ import annotations

from pathlib import Path

from scripts import check_docs_links as checker_module
from scripts.check_docs_links import (
    check_docs_links,
    is_historical_evidence,
    iter_living_docs,
    load_tracked_paths,
    main,
)

ROOT = Path(__file__).resolve().parents[2]


def test_living_docs_links_and_source_paths_resolve() -> None:
    assert check_docs_links(ROOT) == []


def test_exclusion_rules_skip_immutable_evidence_only(tmp_path: Path) -> None:
    (tmp_path / "docs" / "perf").mkdir(parents=True)
    (tmp_path / "docs" / "evidence").mkdir(parents=True)
    (tmp_path / "docs" / "STATUS.md").write_text(
        "See [missing](nope.md) and `src/does_not_exist.py`.\n",
        encoding="utf-8",
    )
    (tmp_path / "docs" / "clone.md").write_text(
        "See [missing](gone.md) and `src/gone.py`.\n",
        encoding="utf-8",
    )
    (tmp_path / "docs" / "note-2026-08-01.md").write_text(
        "See [missing](gone.md).\n",
        encoding="utf-8",
    )
    (tmp_path / "docs" / "perf" / "old.md").write_text(
        "See [missing](gone.md) and `src/gone.py`.\n",
        encoding="utf-8",
    )
    # The evidence index is a living catalogue, while its sibling records are
    # immutable and may name source paths fixed at their original commits.
    (tmp_path / "docs" / "evidence" / "INDEX.md").write_text(
        "See [missing](gone.md).\n",
        encoding="utf-8",
    )
    (tmp_path / "docs" / "evidence" / "security-record-2026-08-01.md").write_text(
        "See [missing](gone.md) and `src/gone.py`.\n",
        encoding="utf-8",
    )

    problems = check_docs_links(tmp_path)
    report = "\n".join(problems)

    assert "docs/STATUS.md:1: missing link target 'nope.md'" in problems
    assert "docs/STATUS.md:1: missing source path 'src/does_not_exist.py'" in problems
    assert "docs/clone.md:1: missing link target 'gone.md'" in problems
    # A date in the filename is not evidence of anything: still checked.
    assert "docs/note-2026-08-01.md:1: missing link target 'gone.md'" in problems
    assert "docs/evidence/INDEX.md:1: missing link target 'gone.md'" in problems
    assert "docs/perf/old.md" not in report
    assert "docs/evidence/security-record-2026-08-01.md" not in report

    assert is_historical_evidence("docs/perf/golden-4h-soak-05-failure-2026-08-08.md")
    # A dated validation record pins paths to blob hashes at its own commit.
    assert is_historical_evidence("docs/evidence/security-runtime-image-trivy-2026-07-30.md")
    assert not is_historical_evidence("docs/security-runtime-image-trivy-2026-07-30.md")
    assert not is_historical_evidence("docs/STATUS.md")
    assert not is_historical_evidence("SECURITY.md")
    assert not is_historical_evidence("docs/evidence/INDEX.md")
    assert not is_historical_evidence("docs/operations/aws-oidc-setup.md")
    assert not is_historical_evidence("docs/operations/ci-soak-next-session-runbook.md")
    assert not is_historical_evidence("docs/runbooks/api-5xx-spike.md")
    assert not is_historical_evidence("docs/security-audit.md")
    assert not is_historical_evidence("docs/decisions/0013-golden-production-topology.md")


def test_archive_body_marker_skips_only_the_preserved_body(tmp_path: Path) -> None:
    (tmp_path / "docs" / "archive").mkdir(parents=True)
    (tmp_path / "docs" / "archive" / "record.md").write_text(
        "See [missing header](missing-header.md) and `src/missing_header.py`.\n"
        "<!-- ARCHIVE BODY START -->\n"
        "See [missing body](missing-body.md) and `src/missing_body.py`.\n",
        encoding="utf-8",
    )

    problems = check_docs_links(tmp_path)
    report = "\n".join(problems)

    assert "docs/archive/record.md:1: missing link target 'missing-header.md'" in problems
    assert "docs/archive/record.md:1: missing source path 'src/missing_header.py'" in problems
    assert "missing-body.md" not in report
    assert "src/missing_body.py" not in report


def test_archive_body_marker_outside_archive_does_not_hide_problems(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "current.md").write_text(
        "<!-- ARCHIVE BODY START -->\n"
        "See [missing](missing-current.md) and `src/missing_current.py`.\n",
        encoding="utf-8",
    )

    problems = check_docs_links(tmp_path)

    assert "docs/current.md:2: missing link target 'missing-current.md'" in problems
    assert "docs/current.md:2: missing source path 'src/missing_current.py'" in problems


def test_archive_without_body_marker_is_checked_completely(tmp_path: Path) -> None:
    (tmp_path / "docs" / "archive").mkdir(parents=True)
    (tmp_path / "docs" / "archive" / "unmarked.md").write_text(
        "See [missing](missing-archive.md) and `src/missing_archive.py`.\n",
        encoding="utf-8",
    )

    problems = check_docs_links(tmp_path)

    assert "docs/archive/unmarked.md:1: missing link target 'missing-archive.md'" in problems
    assert "docs/archive/unmarked.md:1: missing source path 'src/missing_archive.py'" in problems


def test_iter_living_docs_covers_live_directories() -> None:
    living = {path.relative_to(ROOT).as_posix() for path in iter_living_docs(ROOT)}
    assert any(path.startswith("docs/operations/") for path in living)
    assert any(path.startswith("docs/runbooks/") for path in living)
    assert any(path.startswith("docs/decisions/") for path in living)
    assert "docs/decisions/0013-golden-production-topology.md" in living
    assert "docs/evidence/INDEX.md" in living
    assert "docs/operations/ci-soak-next-session-runbook.md" in living
    assert not any(path.startswith("docs/perf/") for path in living)
    assert "docs/evidence/security-runtime-image-trivy-2026-07-30.md" not in living


def test_enumeration_follows_the_tracked_set(tmp_path: Path) -> None:
    """An untracked doc on disk must not change the verdict a clean CI sees."""

    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "STATUS.md").write_text("ok\n", encoding="utf-8")
    (tmp_path / "docs" / "local_only.md").write_text(
        "See [missing](gone.md).\n",
        encoding="utf-8",
    )

    tracked = {"docs/STATUS.md"}
    assert check_docs_links(tmp_path, tracked_paths=tracked) == []

    enumerated = {
        path.relative_to(tmp_path).as_posix() for path in iter_living_docs(tmp_path, tracked)
    }
    assert enumerated == {"docs/STATUS.md"}

    # Without a tracked set the filesystem fallback does see it.
    assert "docs/local_only.md:1: missing link target 'gone.md'" in check_docs_links(tmp_path)


def test_pytest_node_id_checks_file_part_only(tmp_path: Path) -> None:
    (tmp_path / "tests" / "e2e").mkdir(parents=True)
    (tmp_path / "tests" / "e2e" / "test_smoke.py").write_text("pass\n", encoding="utf-8")
    (tmp_path / "docs" / "runbooks").mkdir(parents=True)
    (tmp_path / "docs" / "runbooks" / "auth.md").write_text(
        "See `tests/e2e/test_smoke.py::test_auth_rejects_request_without_api_key` "
        "and `tests/e2e/missing.py::test_gone`.\n",
        encoding="utf-8",
    )

    problems = check_docs_links(tmp_path)
    report = "\n".join(problems)

    assert "test_smoke.py" not in report
    assert "docs/runbooks/auth.md:1: missing source path 'tests/e2e/missing.py'" in problems


def test_wrap_truncated_fragments_are_not_path_claims(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "note.md").write_text(
        "See `docs/security-` and `helm/agentflow/values-` "
        "and `warehouse/agentflow/dv2/business_vault/bv_customer_mdm__` "
        "and `docs/security-*.md` and `helm/agentflow/values-<env>.yaml`.\n",
        encoding="utf-8",
    )

    assert check_docs_links(tmp_path) == []


def test_known_absent_paths_skip_only_the_listed_ones(tmp_path: Path) -> None:
    (tmp_path / "docs" / "operations").mkdir(parents=True)
    (tmp_path / "docs" / "operations" / "aws.md").write_text(
        "Use `infrastructure/terraform/environments/staging.tfvars` "
        "and `infrastructure/terraform/environments/prod.tfvars` "
        "but not `infrastructure/terraform/environments/missing.tfvars`.\n",
        encoding="utf-8",
    )
    (tmp_path / "docs" / "release.md").write_text(
        "Clear `sdk/dist/` and `dist/` before rebuilding, unlike `sdk/build/`.\n",
        encoding="utf-8",
    )

    problems = check_docs_links(tmp_path)
    report = "\n".join(problems)

    assert "staging.tfvars" not in report
    assert "prod.tfvars" not in report
    assert "sdk/dist" not in report
    assert (
        "docs/operations/aws.md:1: missing source path "
        "'infrastructure/terraform/environments/missing.tfvars'"
    ) in problems
    assert "docs/release.md:1: missing source path 'sdk/build'" in problems


def test_tracked_set_not_filesystem_decides_existence(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "ghost.py").write_text("missing from git\n", encoding="utf-8")
    (tmp_path / "src" / "real.py").write_text("tracked\n", encoding="utf-8")
    (tmp_path / "docs" / "note.md").write_text(
        "See `src/ghost.py` and `src/real.py`.\n",
        encoding="utf-8",
    )

    problems = check_docs_links(
        tmp_path,
        tracked_paths={"docs/note.md", "src/real.py"},
    )
    report = "\n".join(problems)

    assert "docs/note.md:1: missing source path 'src/ghost.py'" in problems
    assert "src/real.py" not in report


def test_dot_directory_paths_keep_their_leading_dot(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "note.md").write_text(
        "See `.github/workflows/ci.yml` and `.codex-grok-tasks/x.md`.\n",
        encoding="utf-8",
    )

    problems = check_docs_links(
        tmp_path,
        tracked_paths={"docs/note.md", ".github/workflows/ci.yml"},
    )

    assert problems == []


def test_known_untracked_references_are_skipped(tmp_path: Path) -> None:
    (tmp_path / "docs" / "operations").mkdir(parents=True)
    (tmp_path / "docs" / "operations" / "note.md").write_text(
        "See [pack](../../.codex-grok-tasks/pack/result.json) and `docs/nope.md` "
        "and [handoff](../SESSION_HANDOFF.md).\n",
        encoding="utf-8",
    )

    problems = check_docs_links(
        tmp_path,
        tracked_paths={"docs/operations/note.md"},
    )
    report = "\n".join(problems)

    assert "codex-grok-tasks" not in report
    assert "SESSION_HANDOFF" not in report
    assert "docs/operations/note.md:1: missing source path 'docs/nope.md'" in problems


def test_directory_claims_use_tracked_set(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "src" / "present_dir").mkdir(parents=True)
    (tmp_path / "src" / "present_dir" / "mod.py").write_text("ok\n", encoding="utf-8")
    (tmp_path / "src" / "missing_dir").mkdir()
    (tmp_path / "docs" / "note.md").write_text(
        "See `src/missing_dir/` and `src/present_dir/`.\n",
        encoding="utf-8",
    )

    problems = check_docs_links(
        tmp_path,
        tracked_paths={"docs/note.md", "src/present_dir/mod.py"},
    )
    report = "\n".join(problems)

    assert "docs/note.md:1: missing source path 'src/missing_dir'" in problems
    assert "present_dir" not in report


def test_glob_fragment_is_not_a_truncated_path_claim(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "note.md").write_text(
        "Generator writes `config/contracts/metric.*.v1.yaml`.\n",
        encoding="utf-8",
    )

    assert check_docs_links(tmp_path) == []


def test_filesystem_fallback_is_announced(tmp_path: Path, capsys) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "STATUS.md").write_text("ok\n", encoding="utf-8")

    assert main(["--root", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "filesystem fallback (git ls-files unavailable)" in output
    assert "docs link check: OK" in output


def test_load_tracked_paths_reads_this_repo() -> None:
    tracked = load_tracked_paths(ROOT)
    assert tracked is not None
    assert "README.md" in tracked
    assert "docs/STATUS.md" in tracked
    assert "AGENT_STATE.md" not in tracked


def test_load_tracked_paths_caches_per_root(tmp_path: Path, monkeypatch) -> None:
    """The git call happens once per root: 200+ docs must not fork 200 processes."""

    calls: list[Path] = []

    def counting_read(root: Path) -> set[str]:
        calls.append(root)
        return {"docs/STATUS.md"}

    monkeypatch.setattr(checker_module, "_read_git_tracked_paths", counting_read)
    monkeypatch.setitem(
        checker_module.__dict__,
        "_TRACKED_PATHS_CACHE",
        {},
    )

    first = load_tracked_paths(tmp_path)
    second = load_tracked_paths(tmp_path)

    assert first == second == {"docs/STATUS.md"}
    assert len(calls) == 1
