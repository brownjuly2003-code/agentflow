"""LangGraph nodes for the generation loop: generate_sql, validate, repair_once.

Vendored from the NL_SQL portfolio engine (``nl_sql.agent.nodes.*``) for
AgentFlow ADR 0008, adapted to the trimmed generation-only state
(``GuardOutcome`` instead of ``ExecutionOutcome``) and the DataCatalog-backed
lightweight context (no ChromaDB ``SchemaQueryHit`` / M-Schema machinery).

The ``execute`` node is deliberately absent — AgentFlow runs the generated SQL
through its own DuckDB + PII deny-gate path (ADR 0008 §"Execution half").
"""

from __future__ import annotations

from collections.abc import Callable

from src.serving.semantic_layer.nl_sql_engine.context import (
    render_fewshot_block,
    render_schema_block,
)
from src.serving.semantic_layer.nl_sql_engine.guards import (
    Dialect,
    ValidationReport,
    validate_sql,
)
from src.serving.semantic_layer.nl_sql_engine.parsing import parse_generate_sql_output
from src.serving.semantic_layer.nl_sql_engine.prompts import load_prompt
from src.serving.semantic_layer.nl_sql_engine.provider import GenerateRequest, LLMProvider
from src.serving.semantic_layer.nl_sql_engine.state import (
    GenerationErrorKind,
    GuardOutcome,
    PipelineState,
)


def make_generate_sql_node(
    provider: LLMProvider,
    *,
    max_tokens: int = 1024,
    temperature: float = 0.0,
) -> Callable[[PipelineState], PipelineState]:
    """Node: ask the provider (GraceKelly Sonnet 5) for SQL given the schema."""

    def node(state: PipelineState) -> PipelineState:
        question = state.get("question", "")
        dialect: Dialect = state.get("dialect", "duckdb")
        context = state.get("context")
        prompt = load_prompt(
            "generate_sql",
            dialect=dialect,
            schema_block=render_schema_block(context),
            fewshot_block=render_fewshot_block(context),
            question=question,
        )
        response = provider.generate(
            GenerateRequest(prompt=prompt, max_tokens=max_tokens, temperature=temperature)
        )
        parsed = parse_generate_sql_output(response.text)
        trace = list(state.get("trace") or [])
        trace.append(
            {
                "node": "generate_sql",
                "model": response.model,
                "confidence": parsed.confidence,
                "tables_used": list(parsed.tables_used),
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
            }
        )
        # Reset any stale outcome / error from a previous repair iteration.
        return {
            "generated": parsed,
            "outcome": None,
            "last_error": "",
            "trace": trace,
        }

    return node


def make_validate_node() -> Callable[[PipelineState], PipelineState]:
    """Node: run the static guard on the current candidate.

    Sets ``outcome`` with INVALID_SQL if the guard rejects, otherwise leaves the
    outcome ``ok`` so the graph routes to END (AgentFlow executes it). Failure
    routes to ``repair_once`` if no repair has been tried yet, else to END with
    the validation error attached.
    """

    def node(state: PipelineState) -> PipelineState:
        generated = state.get("generated")
        dialect: Dialect = state.get("dialect", "duckdb")
        trace = list(state.get("trace") or [])

        if generated is None or not generated.sql:
            report = ValidationReport(sql="", dialect=dialect)
            report.add("no_sql", "generate_sql produced no SQL")
            outcome = GuardOutcome(
                sql="",
                validation=report,
                error_kind=GenerationErrorKind.INVALID_SQL,
                error_message="generate_sql produced no SQL",
            )
            trace.append({"node": "validate", "ok": False, "reason": "no_sql"})
            return {
                "outcome": outcome,
                "last_error": outcome.error_message,
                "error_kind": GenerationErrorKind.INVALID_SQL,
                "error_message": outcome.error_message,
                "trace": trace,
            }

        report = validate_sql(generated.sql, dialect=dialect)
        if report.ok:
            trace.append({"node": "validate", "ok": True})
            return {
                "outcome": GuardOutcome(sql=generated.sql, validation=report),
                "trace": trace,
            }

        joined = "; ".join(v.message for v in report.violations)
        outcome = GuardOutcome(
            sql=generated.sql,
            validation=report,
            error_kind=GenerationErrorKind.INVALID_SQL,
            error_message=joined,
        )
        trace.append(
            {
                "node": "validate",
                "ok": False,
                "violations": [v.code for v in report.violations],
            }
        )
        return {
            "outcome": outcome,
            "last_error": joined,
            "error_kind": GenerationErrorKind.INVALID_SQL,
            "error_message": joined,
            "trace": trace,
        }

    return node


def make_repair_once_node(
    provider: LLMProvider,
    *,
    max_tokens: int = 1024,
    temperature: float = 0.0,
) -> Callable[[PipelineState], PipelineState]:
    """Node: re-ask the LLM for SQL given the previous failure context.

    Exactly one repair pass per question. The graph guards this by checking
    ``state["repair_attempted"]`` before routing here; this node sets the flag
    itself so a second routing attempt would be a programming error.
    """

    def node(state: PipelineState) -> PipelineState:
        generated = state.get("generated")
        previous_sql = generated.sql if generated else ""
        error_context = state.get("last_error") or "(no error context — likely a programming bug)"
        question = state.get("question", "")
        dialect: Dialect = state.get("dialect", "duckdb")
        context = state.get("context")

        prompt = load_prompt(
            "repair_sql",
            dialect=dialect,
            schema_block=render_schema_block(context),
            question=question,
            previous_sql=previous_sql,
            error_context=error_context,
        )
        response = provider.generate(
            GenerateRequest(prompt=prompt, max_tokens=max_tokens, temperature=temperature)
        )
        parsed = parse_generate_sql_output(response.text)

        trace = list(state.get("trace") or [])
        trace.append(
            {
                "node": "repair_once",
                "model": response.model,
                "confidence": parsed.confidence,
                "previous_error": error_context,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
            }
        )
        return {
            "generated": parsed,
            "outcome": None,
            "repair_attempted": True,
            "last_error": "",
            "error_kind": None,
            "error_message": "",
            "trace": trace,
        }

    return node
