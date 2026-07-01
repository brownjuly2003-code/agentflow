"""Vendored NL->SQL generation engine (AgentFlow ADR 0008).

The *generation* half of the ``D:\\NL_SQL`` LangGraph engine, vendored into
AgentFlow and repointed at **Claude Sonnet 5 via GraceKelly** (never Mistral,
never a direct model SDK). Hybrid split per ADR 0008:

- **Generation (here):** ``generate_sql -> validate -> repair_once`` on a
  LangGraph ``StateGraph``, schema-grounded from the ``DataCatalog`` (no
  ChromaDB — the demo's five tables fit the prompt), sqlglot shape guard.
- **Execution (NOT here):** AgentFlow runs the validated SQL through its own
  DuckDB path + ``sql_guard`` PII deny-gate.

Public surface:

- ``generate_sql`` / ``generate_sql_text`` — the serving entrypoints.
- ``GraceKellyProvider`` — the Sonnet-5 model slot.
- ``build_context_from_catalog`` — schema grounding (bounded-PII seam lives
  here via ``exclude_fields``).
"""

from __future__ import annotations

from src.serving.semantic_layer.nl_sql_engine.context import (
    ContextBundle,
    FewShot,
    build_context_from_catalog,
)
from src.serving.semantic_layer.nl_sql_engine.engine import generate_sql, generate_sql_text
from src.serving.semantic_layer.nl_sql_engine.graph import (
    GenerationConfig,
    GenerationResult,
    build_generation_pipeline,
    run_generation,
)
from src.serving.semantic_layer.nl_sql_engine.guards import Dialect, validate_sql
from src.serving.semantic_layer.nl_sql_engine.provider import (
    GenerateRequest,
    GenerateResponse,
    GraceKellyProvider,
    LLMProvider,
    ProviderError,
)
from src.serving.semantic_layer.nl_sql_engine.state import (
    GenerateSQLOutput,
    GenerationErrorKind,
    GuardOutcome,
)

__all__ = [
    "ContextBundle",
    "Dialect",
    "FewShot",
    "GenerateRequest",
    "GenerateResponse",
    "GenerateSQLOutput",
    "GenerationConfig",
    "GenerationErrorKind",
    "GenerationResult",
    "GraceKellyProvider",
    "GuardOutcome",
    "LLMProvider",
    "ProviderError",
    "build_context_from_catalog",
    "build_generation_pipeline",
    "generate_sql",
    "generate_sql_text",
    "run_generation",
    "validate_sql",
]
