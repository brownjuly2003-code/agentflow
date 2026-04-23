from pathlib import Path

import scripts.mutation_report as mutation_report


def test_render_mutmut_section_uses_agentflow_copy_for_sdk_alias_targets():
    rendered = mutation_report.render_mutmut_section(
        Path("agentflow/retry.py"),
        ("tests/sdk/test_retry.py",),
    )

    assert '"agentflow/retry.py"' in rendered
    assert '"agentflow"' in rendered
    assert '"sdk"' not in rendered
    assert '"src"' not in rendered


def test_prepare_workspace_creates_agentflow_alias_without_sdk_shadow_tree(
    monkeypatch,
    tmp_path: Path,
):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "config").mkdir()
    (repo / "scripts").mkdir()
    (repo / "sdk" / "agentflow").mkdir(parents=True)
    (repo / "sdk" / "agentflow" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "sdk" / "agentflow" / "retry.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text(
        "[tool.mutmut]\n"
        "paths_to_mutate = []\n"
        "also_copy = []\n"
        "tests_dir = []\n"
        "mutate_only_covered_lines = true\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mutation_report, "ROOT", repo)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    mutation_report.prepare_workspace(
        workspace,
        Path("agentflow/retry.py"),
        mutation_report.ModuleTarget(
            threshold=0.75,
            tests=("tests/sdk/test_retry.py",),
        ),
    )

    assert (workspace / "agentflow" / "retry.py").exists()
    assert not (workspace / "sdk").exists()
