"""LangGraph StateGraph wiring for the generation loop + a run wrapper.

Vendored and trimmed from the NL_SQL portfolio engine (``nl_sql.agent.graph``)
for AgentFlow ADR 0008. The portfolio graph runs
``context_builder -> generate_sql -> validate -> execute -> format ->
explain_trace``; AgentFlow keeps only the **generation** half and hands the
validated SQL back to its own DuckDB + PII deny-gate executor.

Topology::

    START
      │
      ▼
    generate_sql ◄────────────┐
      │                       │
      ▼                       │
    validate ──fail──► repair_once  (fired exactly once,
      │                              guarded by repair_attempted)
      ▼ ok
     END

Failure fall-through: when validation fails AND a repair was already attempted,
we route straight to END with the error attached, so the caller always gets a
structured result (best-effort SQL + error_kind) instead of an exception.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.serving.semantic_layer.nl_sql_engine.context import ContextBundle
from src.serving.semantic_layer.nl_sql_engine.guards import Dialect
from src.serving.semantic_layer.nl_sql_engine.nodes import (
    make_generate_sql_node,
    make_repair_once_node,
    make_validate_node,
)
from src.serving.semantic_layer.nl_sql_engine.provider import LLMProvider
from src.serving.semantic_layer.nl_sql_engine.state import (
    GenerateSQLOutput,
    GenerationErrorKind,
    GuardOutcome,
    PipelineState,
)


@dataclass(slots=True)
class GenerationConfig:
    """Runtime dependencies for the generation graph. Tests inject fakes here."""

    sql_provider: LLMProvider
    max_tokens: int = 1024
    temperature: float = 0.0


@dataclass(slots=True)
class GenerationResult:
    """Flat snapshot of the terminal state — what the caller needs."""

    question: str
    sql: str
    rationale: str
    confidence: float
    outcome: GuardOutcome | None
    error_kind: GenerationErrorKind | None
    error_message: str
    repair_attempted: bool
    trace: list[dict[str, object]]

    @property
    def ok(self) -> bool:
        return self.outcome is not None and self.outcome.ok and self.error_kind is None


def build_generation_pipeline(config: GenerationConfig) -> CompiledStateGraph[Any, Any, Any, Any]:
    graph: StateGraph[PipelineState, None, PipelineState, PipelineState] = StateGraph(PipelineState)

    # Node actions are held as Any before add_node — langgraph's add_node
    # overloads don't line up with a plain Callable[[PipelineState], PipelineState]
    # signature (mirrors the portfolio engine's `nodes: dict[str, Any]` pattern).
    nodes: dict[str, Any] = {
        "generate_sql": make_generate_sql_node(
            config.sql_provider,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
        ),
        "validate": make_validate_node(),
        "repair_once": make_repair_once_node(
            config.sql_provider,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
        ),
    }
    for name, action in nodes.items():
        graph.add_node(name, action)

    graph.add_edge(START, "generate_sql")
    graph.add_edge("generate_sql", "validate")
    graph.add_conditional_edges("validate", _route_after_validate)
    graph.add_edge("repair_once", "validate")

    return graph.compile()


def _route_after_validate(state: PipelineState) -> str:
    """Return the next node name, or ``END`` to terminate.

    Terminates (``END``) when the candidate passed the guard, or when it failed
    but the single repair pass was already burned. Otherwise routes to
    ``repair_once`` for one corrective pass.
    """
    outcome = state.get("outcome")
    if outcome is not None and outcome.error_kind is None:
        return str(END)
    if not state.get("repair_attempted"):
        return "repair_once"
    return str(END)


def run_generation(
    pipeline: CompiledStateGraph[Any, Any, Any, Any],
    *,
    question: str,
    context: ContextBundle | None,
    dialect: Dialect = "duckdb",
    disable_repair: bool = False,
) -> GenerationResult:
    """Invoke the compiled generation graph and flatten the result.

    ``disable_repair`` (default False): when True, pre-sets ``repair_attempted``
    so a first validation failure falls straight through to END — used to
    measure the no-repair baseline.
    """
    initial: PipelineState = {
        "question": question,
        "dialect": dialect,
        "context": context,
        "repair_attempted": disable_repair,
        "trace": [],
    }
    final = cast(PipelineState, pipeline.invoke(initial))
    generated = final.get("generated") or GenerateSQLOutput(sql="")
    outcome = final.get("outcome")
    trace = list(final.get("trace") or [])
    # If a repair pass actually ran (not merely disable_repair pre-setting the
    # flag) and the second candidate still failed the guard, that's a
    # REPAIR_FAILED, not a plain INVALID_SQL. Detect the repair by its trace
    # entry so disable_repair=True keeps the honest INVALID_SQL classification.
    repair_ran = any(entry.get("node") == "repair_once" for entry in trace)
    error_kind = final.get("error_kind")
    if (
        outcome is not None
        and not outcome.ok
        and repair_ran
        and error_kind == GenerationErrorKind.INVALID_SQL
    ):
        error_kind = GenerationErrorKind.REPAIR_FAILED
    return GenerationResult(
        question=final.get("question", question),
        sql=generated.sql,
        rationale=generated.rationale,
        confidence=generated.confidence,
        outcome=outcome,
        error_kind=error_kind,
        error_message=final.get("error_message", ""),
        repair_attempted=bool(final.get("repair_attempted")),
        trace=trace,
    )


__all__ = [
    "GenerationConfig",
    "GenerationResult",
    "build_generation_pipeline",
    "run_generation",
]
