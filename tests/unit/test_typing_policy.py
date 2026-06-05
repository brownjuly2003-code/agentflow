import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _mypy_config() -> dict:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return pyproject["tool"]["mypy"]


def test_strict_untyped_defs_is_the_global_default() -> None:
    # Strict typing is enforced by default across all of src/. The earlier
    # per-module opt-in slices were inverted into this single global default
    # once the whole tree was annotated, so a new untyped def in any module
    # now fails mypy instead of silently slipping through a module nobody
    # pinned.
    assert _mypy_config()["disallow_untyped_defs"] is True


def test_no_module_relaxes_untyped_defs() -> None:
    # 2026-06-05: the last relaxation (src.processing.flink_jobs.*, formerly
    # PyFlink-stub-gated) was removed after the package was annotated by hand
    # (PyFlink symbols resolve to Any under ignore_missing_imports, which is
    # exactly what stubless annotations need). Any override that relaxes
    # disallow_untyped_defs again is a strict-typing regression.
    overrides = _mypy_config().get("overrides", [])
    relaxed = {
        module
        for override in overrides
        if override.get("disallow_untyped_defs") is False
        for module in (
            override["module"] if isinstance(override["module"], list) else [override["module"]]
        )
    }
    assert relaxed == set()


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
