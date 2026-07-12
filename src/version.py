"""Single source of truth for the runtime version (audit P2-1).

Everything that states a version — the FastAPI app, the exported
OpenAPI artifact, release docs — must derive it from here, so the
number can only drift in one place: pyproject.toml.
"""

from __future__ import annotations

import tomllib
from functools import cache
from importlib import metadata
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


@cache
def runtime_version() -> str:
    """Return the agentflow-runtime version.

    A source checkout outranks installed distribution metadata: an
    editable install records the version at install time and goes stale
    the moment pyproject.toml is bumped. Installed wheels ship no
    pyproject.toml, so they fall through to their (correct) metadata.
    """
    if _PYPROJECT.is_file():
        pyproject = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
        version = pyproject.get("project", {}).get("version")
        if isinstance(version, str) and version:
            return version
    return metadata.version("agentflow-runtime")
