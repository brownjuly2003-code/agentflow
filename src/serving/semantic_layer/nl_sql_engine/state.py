"""Pipeline state shared across the generation nodes.

Vendored (and trimmed to the *generation* half) from the NL_SQL portfolio
engine (``nl_sql.agent.state``) for AgentFlow ADR 0008. The portfolio state
also carries execution results and output-format fields; AgentFlow executes the
generated SQL through its own DuckDB + PII deny-gate path, so those are dropped
here. What remains is everything the ``generate_sql -> validate -> repair_once``
loop needs.

LangGraph's ``StateGraph`` merges per-node return dicts back into this state.
Optional fields default to absent (``total=False``) so partial dicts merge
cleanly and node code can ``state.get`` to reason about presence vs. absence.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypedDict

from src.serving.semantic_layer.nl_sql_engine.context import ContextBundle
from src.serving.semantic_layer.nl_sql_engine.guards import Dialect, ValidationReport


class GenerationErrorKind(StrEnum):
    """Terminal error categories for the generation loop.

    Trimmed from the portfolio engine's ``ExecutionErrorKind``: the execution
    categories (timeout / execution_failed / empty_result) belong to
    AgentFlow's executor, not the generator. Only the two the guard loop can
    reach remain.
    """

    INVALID_SQL = "invalid_sql"  # AST guard rejected the candidate
    REPAIR_FAILED = "repair_failed"  # second-pass candidate also rejected


@dataclass(frozen=True, slots=True)
class GenerateSQLOutput:
    """Structured output of the ``generate_sql`` / ``repair_once`` nodes.

    The model returns ``sql + rationale + tables_used + confidence``.
    ``raw_text`` keeps the original response for tracing when JSON parsing
    degraded or the model hallucinated keys.
    """

    sql: str
    rationale: str = ""
    tables_used: tuple[str, ...] = ()
    confidence: float = 0.0
    raw_text: str = ""


@dataclass(slots=True)
class GuardOutcome:
    """Result of running the static guard on a candidate.

    Replaces the portfolio engine's ``ExecutionOutcome`` (which also carried
    query rows). Here it only records the validation report and, on rejection,
    the error taxonomy — execution happens later, in AgentFlow's own path.
    """

    sql: str
    validation: ValidationReport
    error_kind: GenerationErrorKind | None = None
    error_message: str = ""

    @property
    def ok(self) -> bool:
        return self.error_kind is None


class PipelineState(TypedDict, total=False):
    """Per-question generation state. ``total=False`` so partial dicts merge."""

    # --- input ----------------------------------------------------------
    question: str
    dialect: Dialect
    context: ContextBundle | None

    # --- after generate_sql / repair_once ------------------------------
    generated: GenerateSQLOutput | None

    # --- after validate -------------------------------------------------
    outcome: GuardOutcome | None

    # --- repair bookkeeping --------------------------------------------
    repair_attempted: bool
    last_error: str  # error context fed into the repair prompt

    # --- terminal status ------------------------------------------------
    error_kind: GenerationErrorKind | None
    error_message: str

    # --- diagnostic / observability -------------------------------------
    trace: list[dict[str, Any]]
