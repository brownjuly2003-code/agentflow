"""High-level NL->SQL generation entrypoint for AgentFlow's serving layer.

Ties the vendored generation pipeline together: build a schema context from the
``DataCatalog``, run ``generate_sql -> validate -> (repair_once)`` on **Claude
Sonnet 5 via GraceKelly**, and return the validated SQL string. AgentFlow's
serving layer then executes that SQL through its own DuckDB path + PII deny-gate
(ADR 0008 §"Execution half").

This is the surface ``nl_engine.translate_nl_to_sql`` routes to when the LLM
path is enabled (ADR 0008 step 3, wired separately).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING

from src.serving.semantic_layer.nl_sql_engine.context import build_context_from_catalog
from src.serving.semantic_layer.nl_sql_engine.graph import (
    GenerationConfig,
    GenerationResult,
    build_generation_pipeline,
    run_generation,
)
from src.serving.semantic_layer.nl_sql_engine.guards import Dialect
from src.serving.semantic_layer.nl_sql_engine.provider import GraceKellyProvider, LLMProvider

if TYPE_CHECKING:
    from src.serving.semantic_layer.catalog import DataCatalog


def generate_sql(
    question: str,
    catalog: DataCatalog,
    *,
    provider: LLMProvider | None = None,
    dialect: Dialect = "duckdb",
    exclude_fields: Mapping[str, Iterable[str]] | None = None,
    disable_repair: bool = False,
) -> GenerationResult:
    """Generate validated SQL for ``question`` grounded in ``catalog``.

    ``provider`` defaults to a ``GraceKellyProvider`` (Sonnet 5). Pass a fake
    provider in tests to exercise the graph without a live GraceKelly. Returns a
    ``GenerationResult`` — ``result.ok`` is True when the SQL passed the static
    guard; ``result.sql`` is the (best-effort) statement either way.

    ``exclude_fields`` maps ``table -> columns to hide from the model`` — the
    ADR 0008 step-3 bounded-PII seam (allowlist at generation).
    """
    active_provider = (
        provider if provider is not None else GraceKellyProvider(model="claude-sonnet-5")
    )
    context = build_context_from_catalog(catalog, question, exclude_fields=exclude_fields)
    pipeline = build_generation_pipeline(GenerationConfig(sql_provider=active_provider))
    return run_generation(
        pipeline,
        question=question,
        context=context,
        dialect=dialect,
        disable_repair=disable_repair,
    )


def generate_sql_text(
    question: str,
    catalog: DataCatalog,
    *,
    provider: LLMProvider | None = None,
    dialect: Dialect = "duckdb",
    exclude_fields: Mapping[str, Iterable[str]] | None = None,
) -> str | None:
    """Convenience wrapper returning just the SQL string, or None if the guard
    rejected the final candidate. Matches the ``str | None`` contract of
    ``nl_engine.translate_nl_to_sql``."""
    result = generate_sql(
        question,
        catalog,
        provider=provider,
        dialect=dialect,
        exclude_fields=exclude_fields,
    )
    if not result.ok or not result.sql:
        return None
    return result.sql
