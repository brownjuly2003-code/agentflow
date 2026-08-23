"""Deprecated ``src`` namespace shim (audit F-09 / P2-6).

Since 2.1.0 the AgentFlow runtime installs as ``agentflow_runtime``; the
generic ``src`` top-level package this file provides exists only so that
consumers written against ``src.serving...`` / ``src.processing...`` keep
working for one deprecation window. Every ``src.X`` import is aliased onto
the *same module object* as ``agentflow_runtime.X`` (no double import), and
the first ``import src`` emits a :class:`DeprecationWarning` unless
``AGENTFLOW_SRC_SHIM_SILENT=1`` is set.

This shim ships only inside built distributions (hatch ``force-include``);
the repository's ``src/`` directory is a plain container without an
``__init__.py``. The shim and the ``src`` top-level package are removed in
the next major release — import ``agentflow_runtime`` instead.
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import os
import sys
from types import ModuleType

_TARGET = "agentflow_runtime"

if not os.environ.get("AGENTFLOW_SRC_SHIM_SILENT"):
    import warnings

    warnings.warn(
        "Importing the AgentFlow runtime through the 'src' namespace is "
        "deprecated since agentflow-runtime 2.1.0 and will stop working in "
        "the next major release; import 'agentflow_runtime' instead "
        "(set AGENTFLOW_SRC_SHIM_SILENT=1 to silence this warning).",
        DeprecationWarning,
        stacklevel=2,
    )


class _AliasLoader(importlib.abc.Loader):
    """Return the already-imported real module as the aliased one.

    ``module_from_spec`` stamps the *alias* name/spec onto whatever
    ``create_module`` returns, so the real module's identity attributes are
    captured here and restored in ``exec_module`` — ``agentflow_runtime.X``
    keeps its own ``__name__`` while ``sys.modules['src.X']`` points at it.
    """

    def __init__(self, real_name: str) -> None:
        self._real_name = real_name
        self._identity: dict[str, object] = {}

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> ModuleType:
        module = importlib.import_module(self._real_name)
        for attr in ("__name__", "__spec__", "__loader__", "__package__"):
            if hasattr(module, attr):
                self._identity[attr] = getattr(module, attr)
        return module

    def exec_module(self, module: ModuleType) -> None:
        for attr, value in self._identity.items():
            setattr(module, attr, value)


class _SrcAliasFinder(importlib.abc.MetaPathFinder):
    """Resolve ``src.X`` to the module object of ``agentflow_runtime.X``."""

    def find_spec(
        self,
        fullname: str,
        path: object = None,
        target: ModuleType | None = None,
    ) -> importlib.machinery.ModuleSpec | None:
        if not fullname.startswith("src."):
            return None
        real_name = _TARGET + fullname[len("src") :]
        try:
            real_spec = importlib.util.find_spec(real_name)
        except ModuleNotFoundError:
            return None
        if real_spec is None:
            return None
        spec = importlib.machinery.ModuleSpec(
            fullname,
            _AliasLoader(real_name),
            origin=real_spec.origin,
            is_package=real_spec.submodule_search_locations is not None,
        )
        if real_spec.submodule_search_locations is not None:
            spec.submodule_search_locations = list(real_spec.submodule_search_locations)
        return spec


if not any(isinstance(finder, _SrcAliasFinder) for finder in sys.meta_path):
    sys.meta_path.insert(0, _SrcAliasFinder())


def __getattr__(name: str) -> ModuleType:
    """Support ``import src; src.serving`` attribute-style access lazily."""
    if name.startswith("_"):
        raise AttributeError(name)
    return importlib.import_module(f"src.{name}")
