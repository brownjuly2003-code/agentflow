"""Schema context for the generation pipeline — built from the DataCatalog.

ADR 0008 hybrid: the portfolio NL_SQL engine retrieves schema chunks and
few-shot pairs from a **ChromaDB** index (Mistral embeddings). AgentFlow's demo
warehouse is five tables — small enough that retrieval is trivial: every table
fits the prompt. So instead of vendoring ChromaDB / onnxruntime / embeddings,
this module builds the ``ContextBundle`` **directly from the ``DataCatalog``**
(all demo tables) and renders it into the same schema-block / few-shot-block
strings the generation prompt expects.

The ``exclude_fields`` seam is where ADR 0008 step 3 (bounded PII) plugs in:
pass the non-PII allowlist's complement (the PII columns) and the model is never
shown a PII column to select — the allowlist lives *at generation*, with the
deny-gate behind it as defense-in-depth.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.serving.semantic_layer.catalog import DataCatalog


@dataclass(frozen=True, slots=True)
class FewShot:
    """A single Q -> SQL grounding example."""

    question: str
    sql: str


@dataclass(frozen=True, slots=True)
class ContextBundle:
    """Schema + few-shot context handed to the generation prompt.

    Trimmed from the portfolio engine's ChromaDB-backed bundle: instead of
    ranked ``SchemaQueryHit`` chunks, it carries a single pre-rendered
    ``schema_block`` string (all demo tables) plus few-shot pairs. ``tables``
    is kept for tracing/observability parity with the portfolio bundle's
    ``all_tables``.
    """

    question: str
    schema_block: str
    fewshots: tuple[FewShot, ...] = ()
    tables: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)


def render_schema_block(context: ContextBundle | None) -> str:
    """Return the schema block for the prompt (already rendered at build time)."""
    if context is None or not context.schema_block.strip():
        return "(no schema context)"
    return context.schema_block


def render_fewshot_block(context: ContextBundle | None) -> str:
    if context is None or not context.fewshots:
        return "(none)"
    lines: list[str] = []
    for ex in context.fewshots:
        lines.append(f"Q: {ex.question}")
        lines.append(f"SQL: {ex.sql}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _render_table_card(
    *,
    table: str,
    entity_name: str,
    description: str,
    primary_key: str,
    fields: Mapping[str, str],
    exclude: frozenset[str],
) -> str | None:
    """Render one table as a schema card. Returns None if every column is
    excluded (a fully-PII table the model must not see)."""
    columns = [f"  - {name} ({desc})" for name, desc in fields.items() if name not in exclude]
    if not columns:
        return None
    header = f"# Table {table} (entity: {entity_name}) — {description}"
    pk_line = f"  primary key: {primary_key}" if primary_key not in exclude else ""
    body = "\n".join(line for line in [header, pk_line, *columns] if line)
    return body


def build_context_from_catalog(
    catalog: DataCatalog,
    question: str,
    *,
    exclude_fields: Mapping[str, Iterable[str]] | None = None,
    include_metric_fewshots: bool = True,
    fewshot_window: str = "1 hour",
) -> ContextBundle:
    """Build a ``ContextBundle`` for ``question`` from the whole catalog.

    All demo tables are rendered — no retrieval, no ranking. ``exclude_fields``
    maps ``table_name -> columns to omit`` (the ADR 0008 step-3 PII seam); a
    table whose columns are all excluded is dropped from the schema block
    entirely, so the model cannot reference it.

    ``include_metric_fewshots``: derive Q -> SQL few-shot pairs from the
    catalog's metric definitions (their canonical ``sql_template``), which
    grounds the model in the demo's exact table/column/filter conventions.
    """
    exclude_map: dict[str, frozenset[str]] = {
        table: frozenset(cols) for table, cols in (exclude_fields or {}).items()
    }

    cards: list[str] = []
    tables: list[str] = []
    notes: list[str] = []
    for entity_name, entity in catalog.entities.items():
        exclude = exclude_map.get(entity.table, frozenset())
        card = _render_table_card(
            table=entity.table,
            entity_name=entity_name,
            description=entity.description,
            primary_key=entity.primary_key,
            fields=entity.fields,
            exclude=exclude,
        )
        if card is None:
            notes.append(f"table {entity.table!r} fully excluded (all columns filtered)")
            continue
        cards.append(card)
        tables.append(entity.table)

    schema_block = "\n\n".join(cards) if cards else "(no tables available)"

    fewshots: tuple[FewShot, ...] = ()
    if include_metric_fewshots:
        fewshots = _metric_fewshots(catalog, window=fewshot_window)

    return ContextBundle(
        question=question,
        schema_block=schema_block,
        fewshots=fewshots,
        tables=tuple(tables),
        notes=tuple(notes),
    )


def _metric_fewshots(catalog: DataCatalog, *, window: str) -> tuple[FewShot, ...]:
    """Derive Q -> SQL few-shot pairs from the catalog's metric definitions.

    Each metric's canonical ``sql_template`` (with ``{window}`` filled) is a
    correct, in-domain SELECT — exactly the kind of grounding that keeps the
    model on the demo's table/column/filter conventions.
    """
    examples: list[FewShot] = []
    for metric in catalog.metrics.values():
        try:
            sql = metric.sql_template.format(window=window)
        except (KeyError, IndexError):
            sql = metric.sql_template
        examples.append(FewShot(question=f"What is the {metric.description.lower()}?", sql=sql))
    return tuple(examples)
