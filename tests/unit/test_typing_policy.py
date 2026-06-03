import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# The PyFlink-gated jobs are the sole strict relaxation: PyFlink ships no
# PEP-561 stubs and the hot-path Flink jobs are gated on upstream PR #23, so
# they cannot be fully annotated yet without import-untyped/no-Any noise.
FLINK_RELAXATION = "src.processing.flink_jobs.*"


def _mypy_config() -> dict:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return pyproject["tool"]["mypy"]


def test_strict_untyped_defs_is_the_global_default() -> None:
    # Strict typing is enforced by default across all of src/. The earlier
    # per-module opt-in slices were inverted into this single global default
    # once the whole tree (except the flink_jobs relaxation below) was
    # annotated, so a new untyped def in any unlisted module now fails mypy
    # instead of silently slipping through a module nobody pinned.
    assert _mypy_config()["disallow_untyped_defs"] is True


def test_only_flink_jobs_relaxes_untyped_defs() -> None:
    # Any module other than the PyFlink-gated jobs relaxing
    # disallow_untyped_defs would be a strict-typing regression.
    overrides = _mypy_config().get("overrides", [])
    relaxed = {
        module
        for override in overrides
        if override.get("disallow_untyped_defs") is False
        for module in (
            override["module"] if isinstance(override["module"], list) else [override["module"]]
        )
    }
    assert relaxed == {FLINK_RELAXATION}


def test_no_redundant_per_module_strict_overrides() -> None:
    # With strict as the global default, a per-module disallow_untyped_defs=true
    # override is pure redundancy. Fail if one creeps back in so the codebase
    # does not drift back to the pre-inversion 30-override maintenance surface.
    overrides = _mypy_config().get("overrides", [])
    redundant = [
        override["module"]
        for override in overrides
        if override.get("disallow_untyped_defs") is True
    ]
    assert redundant == []
