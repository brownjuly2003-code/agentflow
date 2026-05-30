import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_quality_validators_are_a_strict_mypy_slice() -> None:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    mypy_config = pyproject["tool"]["mypy"]
    overrides = mypy_config.get("overrides", [])

    strict_modules = {
        module
        for override in overrides
        if override.get("disallow_untyped_defs") is True
        for module in (
            override["module"] if isinstance(override["module"], list) else [override["module"]]
        )
    }

    assert mypy_config["disallow_untyped_defs"] is False
    assert "src.quality.validators.*" in strict_modules


def _strict_modules() -> set[str]:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    overrides = pyproject["tool"]["mypy"].get("overrides", [])
    return {
        module
        for override in overrides
        if override.get("disallow_untyped_defs") is True
        for module in (
            override["module"] if isinstance(override["module"], list) else [override["module"]]
        )
    }


def test_auth_package_is_a_strict_mypy_slice() -> None:
    # Auth is security-critical: every def in src/serving/api/auth must carry
    # full annotations so the key / rate-limit / audit paths stay type-checked.
    assert "src.serving.api.auth.*" in _strict_modules()
