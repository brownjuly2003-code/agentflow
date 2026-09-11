"""Unit tests for the local mutation driver's own logic.

Everything that costs minutes -- the mutmut engine and a full mutation run --
is stubbed here. `run_mutant` is exercised against a one-test file so the
`--basetemp` parent is a real pytest mkdir, not a stub. A real mutation run
belongs on the command line (`python scripts/mutation_local.py --module ...`),
not in the unit suite.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.mutation_local as mutation_local
import scripts.mutation_report as mutation_report

TARGET = mutation_report.ModuleTarget(threshold=0.90, tests=("tests/unit/test_thing.py",))
MODULE_PATH = Path("pkg/thing.py")
PRISTINE = "VALUE = 1\nOTHER = 2\n"
MUTATED = "VALUE = 2\nOTHER = 3\n"


@pytest.mark.parametrize(
    ("exit_code", "expected"),
    [
        (0, "survived"),
        (1, "killed"),
        (2, "errored"),
        (3, "errored"),
        (5, "errored"),
        (-9, "errored"),
        (None, "errored"),
    ],
)
def test_classify_exit_code_treats_only_zero_and_one_as_verdicts(exit_code, expected):
    assert mutation_local.classify_exit_code(exit_code) == expected


def test_dotted_module_name_matches_the_top_level_import_path():
    assert mutation_local.dotted_module(Path("agentflow/retry.py")) == "agentflow.retry"
    assert (
        mutation_local.dotted_module(Path("serving/semantic_layer/query/sql_builder.py"))
        == "serving.semantic_layer.query.sql_builder"
    )


def test_write_source_does_not_translate_newlines(tmp_path: Path):
    path = tmp_path / "module.py"

    mutation_local.write_source(path, "first\nsecond\n")

    assert path.read_bytes() == b"first\nsecond\n"


SHIM_CHECK = """
import sys

import mutmut
from mutmut.mutation.trampoline import wrap_in_trampoline

stub = sys.modules["mutmut.__main__"]
assert type(stub).__name__ == "module", type(stub)
# The real submodule would have been read off disk -- and on Windows would have
# called sys.exit(1) on the way.
assert getattr(stub, "__file__", None) is None, stub.__file__
assert issubclass(stub.MutmutProgrammaticFailException, Exception)
assert stub.mangled_name_from_mutant_name("x__mutmut_3") == "x"
assert stub.record_trampoline_hit("x__mutmut_3") is None
assert callable(wrap_in_trampoline)
"""


def test_write_sitecustomize_lets_a_child_import_the_trampoline(tmp_path: Path):
    """The shim is only worth anything if a child interpreter can actually use it.

    Asserting on its source text would pass while every mutant died during
    collection -- and a mutant that dies in collection exits 1 and scores
    "killed", so the driver would report a silent, meaningless 100%. This runs
    the thing: `mutmut.mutation.trampoline` imports three names from
    `mutmut.__main__`, whose import is exactly what `sys.exit(1)`s on native
    Windows, so a child that gets through this import and finds the stub in
    `sys.modules` is the whole mechanism working end to end.
    """
    shim_dir = mutation_local.write_sitecustomize(tmp_path / "shim")

    assert b"\r\n" not in (shim_dir / "sitecustomize.py").read_bytes()
    result = subprocess.run(
        [sys.executable, "-c", SHIM_CHECK],
        env=mutation_local.child_env(shim_dir),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr[-2000:]


def test_child_env_prepends_the_shim_and_carries_the_mutant(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("PYTHONPATH", "existing-entry")

    env = mutation_local.child_env(tmp_path, "pkg.thing.x__mutmut_1")

    assert env["PYTHONPATH"].split(os.pathsep)[0] == str(tmp_path)
    assert env["PYTHONPATH"].split(os.pathsep)[1] == "existing-entry"
    assert env["MUTANT_UNDER_TEST"] == "pkg.thing.x__mutmut_1"


def test_child_env_clears_an_inherited_mutant_selection(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MUTANT_UNDER_TEST", "leftover")

    assert "MUTANT_UNDER_TEST" not in mutation_local.child_env(tmp_path)


def _checkout(tmp_path: Path, source: str = PRISTINE) -> Path:
    """A checkout holding the module under test; also `mutation_report.ROOT`."""
    real_package = tmp_path / "repo" / "pkg"
    real_package.mkdir(parents=True, exist_ok=True)
    (real_package / "__init__.py").write_bytes(b"")
    (real_package / "thing.py").write_bytes(source.encode("utf-8"))
    return real_package


def _symlink_package(workspace: Path, real_package: Path) -> None:
    try:
        os.symlink(real_package, workspace / "pkg", target_is_directory=True)
    except OSError as exc:  # pragma: no cover - unprivileged Windows shells
        pytest.skip(f"symlinks not available here: {exc}")


class _Workspace:
    """An unbuilt workspace plus the checkout and the `prepare_workspace` stub.

    `measure_module` builds it itself: the real `prepare_workspace` copies the
    whole repository, so it is replaced by a stub that lays down only what the
    driver looks at -- a `pyproject.toml` and the top-level package symlinked
    at the real sources, exactly the shape CI's workspace has.
    """

    def __init__(self, monkeypatch, tmp_path: Path, source: str = PRISTINE):
        self.root = tmp_path / "repo"
        self.real_package = _checkout(tmp_path, source)
        self.path = tmp_path / "workspace"
        self.prepared: list[Path] = []
        monkeypatch.setattr(mutation_report, "ROOT", self.root)
        monkeypatch.setattr(mutation_report, "prepare_workspace", self._prepare)

    def _prepare(self, workspace: Path, module_path: Path, target) -> None:
        self.prepared.append(Path(workspace))
        (workspace / "pyproject.toml").write_text("[tool.mutmut]\n", encoding="utf-8")
        _symlink_package(Path(workspace), self.real_package)

    def module_source(self) -> bytes:
        return (self.real_package / "thing.py").read_bytes()

    def stamp(self) -> dict:
        return json.loads((self.path / mutation_local.STAMP_FILENAME).read_text(encoding="utf-8"))


def test_materialize_package_replaces_the_symlink_with_a_real_copy(tmp_path: Path):
    real_package = _checkout(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _symlink_package(workspace, real_package)

    assert mutation_local.materialize_package(workspace, MODULE_PATH) is True

    assert not (workspace / "pkg").is_symlink()
    assert (workspace / "pkg" / "thing.py").read_bytes() == PRISTINE.encode("utf-8")
    # A second call on the materialized copy is a no-op.
    assert mutation_local.materialize_package(workspace, MODULE_PATH) is False


TIMED_OUT = "timeout"


def _stub_engine(
    monkeypatch,
    exit_codes: list[int | None | str],
    *,
    mutants: int | None = None,
) -> list[dict]:
    """Stub coverage measurement, the mutmut engine and the pytest subprocess.

    `exit_codes` is consumed in call order, so a retry of the Nth mutant reads
    the entry after the parallel pass's last one. The sentinel TIMED_OUT raises
    `subprocess.TimeoutExpired` the way a real hung mutant does.
    """
    calls: list[dict] = []
    monkeypatch.setattr(
        mutation_local,
        "measure_covered_lines",
        lambda *args, **kwargs: {1, 2},
    )
    generated = len(exit_codes) if mutants is None else mutants
    monkeypatch.setattr(
        mutation_local,
        "generate_mutants",
        lambda module_path, source, covered: SimpleNamespace(
            code=MUTATED,
            mutant_names=[f"x__mutmut_{index + 1}" for index in range(generated)],
        ),
    )

    def fake_run(command, **kwargs):
        index = len(calls)
        calls.append(
            {
                "command": command,
                "env": kwargs["env"],
                "cwd": kwargs["cwd"],
                "timeout": kwargs.get("timeout"),
                "mutant": kwargs["env"].get("MUTANT_UNDER_TEST"),
                "module_on_disk": (Path(kwargs["cwd"]) / MODULE_PATH).read_bytes(),
            }
        )
        outcome = exit_codes[index]
        if outcome == TIMED_OUT:
            raise subprocess.TimeoutExpired(command, kwargs.get("timeout"))
        return SimpleNamespace(returncode=outcome, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def test_measure_module_materializes_the_package_before_it_mutates_the_module(
    monkeypatch,
    tmp_path: Path,
):
    workspace = _Workspace(monkeypatch, tmp_path)
    real_package = workspace.real_package
    calls = _stub_engine(monkeypatch, [1, 0])

    run = mutation_local.measure_module(
        MODULE_PATH,
        TARGET,
        workspace.path,
        tmp_path / "shim",
        python="python",
        jobs=1,
        timeout=5.0,
    )

    # The mutated source reached the workspace copy...
    assert [call["module_on_disk"] for call in calls] == [MUTATED.encode("utf-8")] * 2
    # ...and never the real sources behind the symlink.
    assert (real_package / "thing.py").read_bytes() == PRISTINE.encode("utf-8")
    # The workspace is handed back unmutated, byte for byte.
    assert (workspace.path / "pkg" / "thing.py").read_bytes() == PRISTINE.encode("utf-8")
    assert run.generated == 2


def _basetemps(calls: list[dict]) -> list[str]:
    return [
        argument
        for call in calls
        for argument in call["command"]
        if argument.startswith("--basetemp=")
    ]


def test_measure_module_gives_every_mutant_its_own_basetemp(monkeypatch, tmp_path: Path):
    workspace = _Workspace(monkeypatch, tmp_path)
    calls = _stub_engine(monkeypatch, [1, 1, 1])

    mutation_local.measure_module(
        MODULE_PATH,
        TARGET,
        workspace.path,
        tmp_path / "shim",
        python="python",
        jobs=3,
        timeout=5.0,
    )

    basetemps = _basetemps(calls)
    assert len(basetemps) == 3
    assert len(set(basetemps)) == 3


def test_two_invocations_sharing_a_workspace_get_separate_basetemps(
    monkeypatch,
    tmp_path: Path,
):
    """The same command run twice lands on the same workspace by design.

    A matching stamp is what makes sharing it safe, and nothing serialises the
    two -- the second terminal reuses the workspace rather than rebuilding it.
    pytest wipes and recreates its `--basetemp` at startup, so a scratch path
    keyed only on the mutant's index would let two pools abort each other. That
    is never a wrong score (only exits 0 and 1 are verdicts), but it is a run
    thrown away, so the scratch is namespaced per invocation.
    """
    workspace = _Workspace(monkeypatch, tmp_path)

    first = _stub_engine(monkeypatch, [1, 1])
    mutation_local.measure_module(
        MODULE_PATH,
        TARGET,
        workspace.path,
        tmp_path / "shim",
        python="python",
        jobs=2,
        timeout=5.0,
    )
    second = _stub_engine(monkeypatch, [1, 1])
    mutation_local.measure_module(
        MODULE_PATH,
        TARGET,
        workspace.path,
        tmp_path / "shim",
        python="python",
        jobs=2,
        timeout=5.0,
    )

    assert workspace.prepared == [workspace.path]  # the second run reused it
    assert len(_basetemps(first)) == len(_basetemps(second)) == 2
    assert not set(_basetemps(first)) & set(_basetemps(second))


def _run_mutant_against_tmp_path_test(tmp_path: Path, body: str) -> tuple[str, int | None]:
    """Call `run_mutant` the way `measure_module` does: the basetemp parent is missing."""
    test_file = tmp_path / "test_tmp_path_probe.py"
    test_file.write_text(
        f"from pathlib import Path\n\ndef test_uses_tmp_path(tmp_path):\n{body}",
        encoding="utf-8",
    )
    basetemp = tmp_path / "scratch" / "run-missing" / "mutant0"
    assert not basetemp.parent.exists()
    return mutation_local.run_mutant(
        tmp_path,
        (test_file.name,),
        "pkg.thing.x__mutmut_1",
        python=sys.executable,
        shim_dir=tmp_path / "shim",
        basetemp=basetemp,
        timeout=20.0,
    )


def test_run_mutant_survives_a_passing_tmp_path_test_when_the_basetemp_parent_is_missing(
    tmp_path: Path,
):
    """pytest mkdir()s --basetemp without parents; a missing parent is not a kill."""
    name, exit_code = _run_mutant_against_tmp_path_test(
        tmp_path,
        "    (tmp_path / 'marker').write_text('ok')\n",
    )

    assert name == "pkg.thing.x__mutmut_1"
    assert exit_code == 0
    assert mutation_local.classify_exit_code(exit_code) == "survived"


def test_run_mutant_still_kills_a_failing_tmp_path_test_when_the_basetemp_parent_is_missing(
    tmp_path: Path,
):
    """Creating the parent must not turn a real failure into a survival."""
    name, exit_code = _run_mutant_against_tmp_path_test(
        tmp_path,
        "    Path('ran').write_text('yes')\n"
        "    (tmp_path / 'marker').write_text('ok')\n"
        "    assert False\n",
    )

    assert name == "pkg.thing.x__mutmut_1"
    assert (tmp_path / "ran").read_text(encoding="utf-8") == "yes"
    assert exit_code == 1
    assert mutation_local.classify_exit_code(exit_code) == "killed"


def test_measure_module_scores_verdicts_and_never_counts_an_error_as_a_kill(
    monkeypatch,
    tmp_path: Path,
):
    workspace = _Workspace(monkeypatch, tmp_path)
    # The fourth mutant exits 2 twice: once in parallel, once on its retry.
    _stub_engine(monkeypatch, [1, 1, 0, 2, 2], mutants=4)

    run = mutation_local.measure_module(
        MODULE_PATH,
        TARGET,
        workspace.path,
        tmp_path / "shim",
        python="python",
        jobs=1,
        timeout=5.0,
    )

    assert sorted(run.killed) == ["pkg.thing.x__mutmut_1", "pkg.thing.x__mutmut_2"]
    assert run.survived == ["pkg.thing.x__mutmut_3"]
    assert run.errored == [("pkg.thing.x__mutmut_4", 2)]
    assert run.scored == 3
    assert run.score == pytest.approx(2 / 3)
    # Below threshold anyway, but an unexplained exit code alone fails the gate.
    assert run.passed is False


def test_measure_module_selects_only_the_requested_mutants(monkeypatch, tmp_path: Path):
    workspace = _Workspace(monkeypatch, tmp_path)
    calls = _stub_engine(monkeypatch, [1, 1, 1])

    run = mutation_local.measure_module(
        MODULE_PATH,
        TARGET,
        workspace.path,
        tmp_path / "shim",
        python="python",
        jobs=1,
        timeout=5.0,
        only={"x__mutmut_2", "x__mutmut_404"},
    )

    assert len(calls) == 1
    assert calls[0]["env"]["MUTANT_UNDER_TEST"] == "pkg.thing.x__mutmut_2"
    assert run.generated == 3
    assert run.killed == ["pkg.thing.x__mutmut_2"]


def test_measure_module_accepts_a_survivor_name_the_way_it_prints_it(
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    """`--only` has to take the names the tool's own report hands back.

    Everything printed carries the dotted module in front
    (`pkg.thing.x__mutmut_2`), while the engine names mutants bare, so an
    unstripped prefix would select nothing and score zero.
    """
    workspace = _Workspace(monkeypatch, tmp_path)
    calls = _stub_engine(monkeypatch, [1, 1, 1])

    run = mutation_local.measure_module(
        MODULE_PATH,
        TARGET,
        workspace.path,
        tmp_path / "shim",
        python="python",
        jobs=1,
        timeout=5.0,
        only={"pkg.thing.x__mutmut_2", "pkg.thing.x__mutmut_404"},
    )

    assert len(calls) == 1
    assert calls[0]["env"]["MUTANT_UNDER_TEST"] == "pkg.thing.x__mutmut_2"
    assert run.killed == ["pkg.thing.x__mutmut_2"]
    assert run.scored == 1
    # A name that is not in the population is still reported, dotted like the rest.
    assert "pkg.thing.x__mutmut_404" in capsys.readouterr().out


def test_source_module_file_maps_a_gate_target_back_to_the_checkout(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(mutation_report, "ROOT", tmp_path)

    assert (
        mutation_local.source_module_file(Path("agentflow/retry.py"))
        == tmp_path / "sdk" / "agentflow" / "retry.py"
    )
    assert (
        mutation_local.source_module_file(Path("serving/api/rate_limiter.py"))
        == tmp_path / "src" / "agentflow_runtime" / "serving" / "api" / "rate_limiter.py"
    )


def test_every_gate_target_resolves_to_a_file_in_this_checkout():
    """The mapping is only useful while it still matches `prepare_workspace`."""
    for module_path in mutation_report.MODULE_TARGETS:
        assert mutation_local.source_module_file(module_path).is_file(), module_path


def test_clear_workspace_removes_links_without_following_them(tmp_path: Path):
    real_package = _checkout(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _symlink_package(workspace, real_package)
    (workspace / "pyproject.toml").write_text("[tool.mutmut]\n", encoding="utf-8")
    (workspace / mutation_local.MARKER_FILENAME).write_text("", encoding="utf-8")
    (workspace / ".mutation-local-tmp" / "mutant0").mkdir(parents=True)

    mutation_local.clear_workspace(workspace)

    assert list(workspace.iterdir()) == []
    # The checkout the link pointed at is untouched.
    assert (real_package / "thing.py").read_bytes() == PRISTINE.encode("utf-8")


def test_clear_workspace_refuses_a_directory_it_did_not_build(tmp_path: Path):
    """`--workspace` is typed by hand, and a rebuild deletes everything in it."""
    somewhere_else = tmp_path / "notes"
    somewhere_else.mkdir()
    (somewhere_else / "important.txt").write_text("keep me", encoding="utf-8")

    with pytest.raises(SystemExit, match="refusing to rebuild"):
        mutation_local.clear_workspace(somewhere_else)

    assert (somewhere_else / "important.txt").read_text(encoding="utf-8") == "keep me"


def test_clear_workspace_refuses_a_python_project_it_did_not_build(tmp_path: Path):
    """A `pyproject.toml` marks Python projects generally, not a workspace.

    The likeliest wrong `--workspace` is a project root, and accepting that
    marker would empty it: sources, virtualenv and all.
    """
    project = tmp_path / "some-project"
    (project / "src" / "pkg").mkdir(parents=True)
    (project / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
    (project / "src" / "pkg" / "code.py").write_text("VALUE = 1\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="refusing to rebuild"):
        mutation_local.clear_workspace(project)

    assert (project / "src" / "pkg" / "code.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert sorted(path.name for path in project.iterdir()) == ["pyproject.toml", "src"]


def test_clear_workspace_refuses_a_checkout_carrying_a_git_directory(tmp_path: Path):
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    # Even a marked directory: a `.git` means someone typed the wrong path.
    (checkout / mutation_local.MARKER_FILENAME).write_text("", encoding="utf-8")

    with pytest.raises(SystemExit, match="holds a [.]git"):
        mutation_local.clear_workspace(checkout)

    assert (checkout / ".git").is_dir()


def test_clear_workspace_refuses_a_path_inside_the_checkout(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(mutation_report, "ROOT", tmp_path / "repo")
    inside = tmp_path / "repo" / "workspace"
    inside.mkdir(parents=True)
    (inside / mutation_local.MARKER_FILENAME).write_text("", encoding="utf-8")

    with pytest.raises(SystemExit, match="lives inside it"):
        mutation_local.clear_workspace(inside)

    assert inside.is_dir()


def test_clear_workspace_refuses_this_repository_root():
    """`--workspace .` typed here is the mistake the guard exists for."""
    with pytest.raises(SystemExit, match="refusing to use"):
        mutation_local.clear_workspace(mutation_local.ROOT)

    assert (mutation_local.ROOT / ".git").exists()


def test_measure_module_stamps_the_workspace_with_what_it_was_built_from(
    monkeypatch,
    tmp_path: Path,
):
    workspace = _Workspace(monkeypatch, tmp_path)
    _stub_engine(monkeypatch, [1])

    mutation_local.measure_module(
        MODULE_PATH,
        TARGET,
        workspace.path,
        tmp_path / "shim",
        python="python",
        jobs=1,
        timeout=5.0,
    )

    assert workspace.prepared == [workspace.path]
    stamp = workspace.stamp()
    assert stamp["root"] == workspace.root.as_posix()
    assert stamp["module"] == "pkg/thing.py"
    assert stamp["source_sha256"] == hashlib.sha256(workspace.module_source()).hexdigest()
    # The workspace copies the whole package and (without symlinks) the tests,
    # so both are digested too.
    assert stamp["package_sha256"] == mutation_local.tree_sha256(workspace.real_package)
    assert set(stamp) == {
        "root",
        "module",
        "source_sha256",
        "package_sha256",
        "tests_sha256",
        "pyproject_sha256",
    }


def test_measure_module_reuses_a_workspace_whose_stamp_matches(monkeypatch, tmp_path: Path):
    workspace = _Workspace(monkeypatch, tmp_path)
    _stub_engine(monkeypatch, [1, 1], mutants=1)

    for _ in range(2):
        mutation_local.measure_module(
            MODULE_PATH,
            TARGET,
            workspace.path,
            tmp_path / "shim",
            python="python",
            jobs=1,
            timeout=5.0,
        )

    # Same root, same module, same source: built once, measured twice.
    assert workspace.prepared == [workspace.path]


def test_measure_module_rebuilds_when_the_module_source_changed(monkeypatch, tmp_path: Path):
    workspace = _Workspace(monkeypatch, tmp_path)
    _stub_engine(monkeypatch, [1, 1], mutants=1)

    mutation_local.measure_module(
        MODULE_PATH,
        TARGET,
        workspace.path,
        tmp_path / "shim",
        python="python",
        jobs=1,
        timeout=5.0,
    )
    # The edit this tool exists to be run after.
    (workspace.real_package / "thing.py").write_bytes(b"VALUE = 41\nOTHER = 2\n")

    mutation_local.measure_module(
        MODULE_PATH,
        TARGET,
        workspace.path,
        tmp_path / "shim",
        python="python",
        jobs=1,
        timeout=5.0,
    )

    assert workspace.prepared == [workspace.path, workspace.path]
    assert (
        workspace.stamp()["source_sha256"] == hashlib.sha256(workspace.module_source()).hexdigest()
    )
    # The pristine copy was re-taken with the workspace, so the mutants are
    # generated from the edited source rather than the previous run's.
    backup = workspace.path / f"{MODULE_PATH.stem}{mutation_local.BACKUP_SUFFIX}"
    assert backup.read_bytes() == b"VALUE = 41\nOTHER = 2\n"


def test_measure_module_rebuilds_when_a_sibling_in_the_package_changed(
    monkeypatch,
    tmp_path: Path,
):
    """The workspace holds a real copy of the whole package, not just the module.

    `materialize_package` is a no-op once that copy exists, so a stamp keyed on
    the target module alone would measure the first run's copy of every sibling
    -- a confident score about a tree that is half stale.
    """
    workspace = _Workspace(monkeypatch, tmp_path)
    sibling = workspace.real_package / "sibling.py"
    sibling.write_bytes(b"SIBLING = 'first-run'\n")
    _stub_engine(monkeypatch, [1, 1], mutants=1)

    mutation_local.measure_module(
        MODULE_PATH,
        TARGET,
        workspace.path,
        tmp_path / "shim",
        python="python",
        jobs=1,
        timeout=5.0,
    )
    sibling.write_bytes(b"SIBLING = 'second-run'\n")

    mutation_local.measure_module(
        MODULE_PATH,
        TARGET,
        workspace.path,
        tmp_path / "shim",
        python="python",
        jobs=1,
        timeout=5.0,
    )

    assert workspace.prepared == [workspace.path, workspace.path]
    assert (workspace.path / "pkg" / "sibling.py").read_bytes() == b"SIBLING = 'second-run'\n"


def test_measure_module_rebuilds_when_the_targets_tests_changed(monkeypatch, tmp_path: Path):
    """Where symlinks are unavailable the tests are copied too, and go stale."""
    workspace = _Workspace(monkeypatch, tmp_path)
    test_file = workspace.root / TARGET.tests[0]
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_bytes(b"def test_value():\n    assert VALUE == 1\n")
    _stub_engine(monkeypatch, [1, 1], mutants=1)

    mutation_local.measure_module(
        MODULE_PATH,
        TARGET,
        workspace.path,
        tmp_path / "shim",
        python="python",
        jobs=1,
        timeout=5.0,
    )
    test_file.write_bytes(b"def test_value():\n    assert VALUE == 1\n    assert OTHER == 2\n")

    mutation_local.measure_module(
        MODULE_PATH,
        TARGET,
        workspace.path,
        tmp_path / "shim",
        python="python",
        jobs=1,
        timeout=5.0,
    )

    assert workspace.prepared == [workspace.path, workspace.path]


def test_measure_module_rebuilds_when_the_checkouts_pyproject_changed(monkeypatch, tmp_path: Path):
    """`prepare_workspace` renders the workspace's pyproject from the checkout's.

    It is written as a real file, never a symlink, and it carries pytest's
    addopts, filterwarnings and plugin toggles plus `[tool.mutmut]` -- i.e. it
    changes what the mutant runs do. Left out of the stamp, an edit to it would
    be measured under the previous run's pytest configuration.
    """
    workspace = _Workspace(monkeypatch, tmp_path)
    pyproject = workspace.root / "pyproject.toml"
    pyproject.write_bytes(b'[tool.pytest.ini_options]\naddopts = "-q"\n')
    _stub_engine(monkeypatch, [1, 1], mutants=1)

    mutation_local.measure_module(
        MODULE_PATH,
        TARGET,
        workspace.path,
        tmp_path / "shim",
        python="python",
        jobs=1,
        timeout=5.0,
    )
    assert (
        workspace.stamp()["pyproject_sha256"] == hashlib.sha256(pyproject.read_bytes()).hexdigest()
    )
    pyproject.write_bytes(b'[tool.pytest.ini_options]\naddopts = "-q -p no:randomly"\n')

    mutation_local.measure_module(
        MODULE_PATH,
        TARGET,
        workspace.path,
        tmp_path / "shim",
        python="python",
        jobs=1,
        timeout=5.0,
    )

    assert workspace.prepared == [workspace.path, workspace.path]
    assert (
        workspace.stamp()["pyproject_sha256"] == hashlib.sha256(pyproject.read_bytes()).hexdigest()
    )


def test_measure_module_never_reuses_another_checkouts_workspace(monkeypatch, tmp_path: Path):
    """`--root` must not be silently ignored, even when the sources are identical."""
    workspace = _Workspace(monkeypatch, tmp_path)
    _stub_engine(monkeypatch, [1, 1], mutants=1)

    mutation_local.measure_module(
        MODULE_PATH,
        TARGET,
        workspace.path,
        tmp_path / "shim",
        python="python",
        jobs=1,
        timeout=5.0,
    )
    other = _checkout(tmp_path / "elsewhere")
    monkeypatch.setattr(mutation_report, "ROOT", other.parent)

    mutation_local.measure_module(
        MODULE_PATH,
        TARGET,
        workspace.path,
        tmp_path / "shim",
        python="python",
        jobs=1,
        timeout=5.0,
    )

    assert workspace.prepared == [workspace.path, workspace.path]
    assert workspace.stamp()["root"] == other.parent.as_posix()


def test_measure_module_rebuilds_when_the_pristine_copy_is_missing(monkeypatch, tmp_path: Path):
    """An interrupted first run must not leave a workspace the next one believes."""
    workspace = _Workspace(monkeypatch, tmp_path)
    _stub_engine(monkeypatch, [1, 1], mutants=1)

    mutation_local.measure_module(
        MODULE_PATH,
        TARGET,
        workspace.path,
        tmp_path / "shim",
        python="python",
        jobs=1,
        timeout=5.0,
    )
    (workspace.path / f"{MODULE_PATH.stem}{mutation_local.BACKUP_SUFFIX}").unlink()

    mutation_local.measure_module(
        MODULE_PATH,
        TARGET,
        workspace.path,
        tmp_path / "shim",
        python="python",
        jobs=1,
        timeout=5.0,
    )

    assert workspace.prepared == [workspace.path, workspace.path]


def test_measure_module_retries_a_mutant_without_a_verdict_serially(monkeypatch, tmp_path: Path):
    workspace = _Workspace(monkeypatch, tmp_path)
    calls = _stub_engine(monkeypatch, [1, TIMED_OUT, 1], mutants=2)

    run = mutation_local.measure_module(
        MODULE_PATH,
        TARGET,
        workspace.path,
        tmp_path / "shim",
        python="python",
        jobs=1,
        timeout=5.0,
        retry_timeout=30.0,
    )

    # Retried exactly once, uncontended, with a longer timeout than the pass
    # that timed it out -- and killed on the strength of the retry's verdict.
    assert [call["mutant"] for call in calls] == [
        "pkg.thing.x__mutmut_1",
        "pkg.thing.x__mutmut_2",
        "pkg.thing.x__mutmut_2",
    ]
    assert [call["timeout"] for call in calls] == [5.0, 5.0, 30.0]
    assert run.retried == ["pkg.thing.x__mutmut_2"]
    assert sorted(run.killed) == ["pkg.thing.x__mutmut_1", "pkg.thing.x__mutmut_2"]
    assert run.errored == []


def test_measure_module_keeps_a_mutant_errored_when_the_retry_has_no_verdict_either(
    monkeypatch,
    tmp_path: Path,
):
    workspace = _Workspace(monkeypatch, tmp_path)
    calls = _stub_engine(monkeypatch, [TIMED_OUT, TIMED_OUT], mutants=1)

    run = mutation_local.measure_module(
        MODULE_PATH,
        TARGET,
        workspace.path,
        tmp_path / "shim",
        python="python",
        jobs=1,
        timeout=5.0,
    )

    # Never promoted to a kill, and the default retry gets three times as long.
    assert [call["timeout"] for call in calls] == [5.0, 15.0]
    assert run.retried == ["pkg.thing.x__mutmut_1"]
    assert run.killed == []
    assert run.errored == [("pkg.thing.x__mutmut_1", None)]
    assert run.passed is False


def test_measure_module_does_not_retry_when_every_mutant_has_a_verdict(monkeypatch, tmp_path: Path):
    workspace = _Workspace(monkeypatch, tmp_path)
    calls = _stub_engine(monkeypatch, [1, 0])

    run = mutation_local.measure_module(
        MODULE_PATH,
        TARGET,
        workspace.path,
        tmp_path / "shim",
        python="python",
        jobs=1,
        timeout=5.0,
    )

    assert len(calls) == 2
    assert run.retried == []


def test_module_run_passes_only_at_or_above_its_threshold():
    at_threshold = mutation_local.ModuleRun(
        module_path=MODULE_PATH,
        threshold=0.90,
        generated=10,
        killed=[f"m{index}" for index in range(9)],
        survived=["m9"],
    )
    below = mutation_local.ModuleRun(
        module_path=MODULE_PATH,
        threshold=0.90,
        generated=10,
        killed=[f"m{index}" for index in range(8)],
        survived=["m8", "m9"],
    )
    nothing_scored = mutation_local.ModuleRun(module_path=MODULE_PATH, threshold=0.90, generated=0)

    assert at_threshold.passed is True
    assert below.passed is False
    assert nothing_scored.passed is False


def test_module_run_fails_on_a_mutant_without_a_verdict_even_at_a_passing_score():
    """A harness failure is never a green, however good the scored mutants look.

    Scored on its own the run is at threshold; one mutant that came back with an
    unexplained exit code means the population was not fully measured, so the
    number is not the gate's number and must not be reported as a pass.
    """
    errored_at_threshold = mutation_local.ModuleRun(
        module_path=MODULE_PATH,
        threshold=0.90,
        generated=11,
        killed=[f"m{index}" for index in range(9)],
        survived=["m9"],
        errored=[("m10", 2)],
    )

    assert errored_at_threshold.score == pytest.approx(0.9)
    assert errored_at_threshold.score >= errored_at_threshold.threshold
    assert errored_at_threshold.passed is False


def test_main_rejects_a_module_outside_the_gate(capsys):
    assert mutation_local.main(["--module", "serving/not_a_target.py"]) == 2
    assert "unknown module" in capsys.readouterr().err


def test_main_resolves_a_relative_workspace_before_anything_uses_it(monkeypatch, tmp_path: Path):
    """A relative `--workspace` would reach coverage as a relative `--include=`.

    coverage matches that pattern against the absolute paths it records, so it
    measures nothing and the module dies with "coverage recorded no lines",
    naming the wrong problem; the stamp, backup and report inherit the same
    relativeness.
    """
    seen: list[Path] = []

    def fake_measure(module_path, target, workspace, shim_dir, **kwargs):
        seen.append(workspace)
        return mutation_local.ModuleRun(
            module_path=module_path,
            threshold=target.threshold,
            generated=1,
            killed=["m0"],
        )

    monkeypatch.setattr(mutation_local, "measure_module", fake_measure)
    monkeypatch.chdir(tmp_path)
    module = next(iter(mutation_report.MODULE_TARGETS)).as_posix()

    exit_code = mutation_local.main(
        ["--module", module, "--workspace", "ws", "--json", str(tmp_path / "report.json")]
    )

    assert exit_code == 0
    assert seen == [(tmp_path / "ws").resolve()]
    assert seen[0].is_absolute()


def test_main_list_modules_prints_the_gate_definition(capsys):
    assert mutation_local.main(["--list-modules"]) == 0

    printed = capsys.readouterr().out
    for module_path in mutation_report.MODULE_TARGETS:
        assert module_path.as_posix() in printed
