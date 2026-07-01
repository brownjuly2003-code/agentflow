# ADR 0008: Adopt the NL_SQL engine for the NL→SQL path

## Status

Accepted - 2026-07-01. **Implemented (cont.37, 2026-07-01):** the generation half
is vendored at `src/serving/semantic_layer/nl_sql_engine/` (Sonnet 5 via
GraceKelly), `nl_engine._llm_translate` routes through it, and the eval harness
measured **100% EA (18/18)** on the demo set live (rule-based baseline recomputed
to 27.8% after the gold set was normalised to a consistent minimal projection).
See `docs/perf/nl-sql-eval-sonnet5-2026-07-01.md`. Shipped default stays
rule-based (`GRACEKELLY_URL` unset).

**Bounded-PII sub-goal WITHDRAWN (2026-07-01).** The "schema-grounding for
bounded PII" work below (§Decision, "Schema-grounding becomes the bounded-PII
mechanism") assumed the serving warehouse holds PII. It does not: `users_enriched`
/ `orders_v2` carry only analytics columns, and none of the fields the former
`config/pii_fields.yaml` declared exist in the catalog or the physical DDL. So the
whole serving-layer PII apparatus (the `assert_no_pii_access` deny-gate and the
entity-path `redact_entity`) guarded an empty surface and has been **removed**
(see CHANGELOG). Real contact PII lives only in the DV2 business vault; its
governance belongs engine-side there (ClickHouse row/column policies) — this is
ADR 0006 Phase 2, not an NL→SQL generation concern. The `exclude_fields` seam on
the vendored engine is retained as a generic (non-PII-specific) column-hiding
capability but has no PII caller.

## Context

AgentFlow's natural-language-to-SQL path (`src/serving/semantic_layer/nl_engine.py`)
is the weakest component in the serving tier. It has two modes:

1. **Rule-based (the shipped default).** `_rule_based_translate` is seven regex
   patterns that map a handful of question shapes to fixed SQL templates
   (revenue, AOV, top products, conversion, out-of-stock, a user/order lookup).
   Anything outside those seven shapes returns `None` ("untranslatable"). This is
   what a demo user actually hits, because the LLM path is gated off (see below).
2. **LLM (opt-in, `GRACEKELLY_URL` set).** `_llm_translate` builds a
   schema-grounded prompt from the catalog, POSTs it to GraceKelly's
   `/api/v1/orchestrate` (Sonnet 5), and accepts the returned text if it
   `startswith("SELECT")`. There is no schema retrieval, no dialect validation,
   no execution feedback, and no repair — the model's first string is trusted
   modulo one prefix check, and the PII deny-gate is the only thing standing
   between a crafted question and the warehouse.

Two structural gaps follow from this:

- **No honest accuracy number.** The engine has never been evaluated against a
  labelled benchmark, so "NL→SQL works" is an unbacked claim. The road-to-9.8
  rubric (R5) requires every capability claim to map to a runnable artifact;
  this one has none.
- **PII cannot be made bounded here.** The LLM path has no notion of which
  columns it is allowed to select — it hands the model the full catalog and
  hopes. Bounding PII downstream (the deny-gate) has proven to be whack-a-mole
  against SQL shapes (three bypasses across cont.31–33). ADR 0006 concluded that
  a bounded guarantee needs the allowlist to live **at generation** or in the
  engine, not in a dialect-pinned string parse after the fact.

Meanwhile a mature NL→SQL engine already exists in this author's portfolio,
`D:\NL_SQL` (`src/nl_sql/`):

- A **LangGraph** `StateGraph`: `context_builder → generate_sql → validate →
  (repair_once) → execute → deterministic_format → explain_trace`, with a
  guarded single repair on validation/execution failure and a fall-through that
  always returns a structured caption instead of a 500.
- **Schema-RAG** over ChromaDB (`SchemaIndex`) — retrieves the relevant tables
  and columns for a question plus FK-BFS neighbours, and few-shot Q→SQL
  examples, before generation. `context_builder` therefore *knows the column
  set it is exposing to the model*.
- **sqlglot** validation (shared with AgentFlow's `sql_guard`).
- A clean provider seam: `LLMProvider` is a `Protocol`
  (`generate(GenerateRequest) -> GenerateResponse`) chosen by
  `build_provider(name, settings)`; six providers implement it (mistral,
  github_models, groq, ollama, openrouter, perplexity).
- An **eval harness** (`src/nl_sql/eval/`, `eval/`) that runs the same graph the
  API serves against BIRD Mini-Dev and reports execution accuracy (EA).
  Measured **~94% EA on BIRD Mini-Dev** (n=200) and 100% on Chinook.

## Options considered

### 1. Keep and incrementally improve the current `nl_engine.py`

Pros:

- no new dependencies; nothing to port
- the code path is small and already integrated with `sql_guard` and the catalog

Cons:

- re-implements schema-RAG, a validate/repair loop, and an eval harness that
  already exist and are already tuned to 94% EA — months of work to reach parity
- leaves the "no honest accuracy number" gap open until that work lands
- does not move PII toward bounded (would still need schema-grounding built from
  scratch)

### 2. Adopt the `D:\NL_SQL` engine, repoint its LLM slot to GraceKelly

Pros:

- inherits a real, evaluated engine (schema-RAG + validate/repair + 94% EA)
  instead of seven regexes
- the eval harness gives AgentFlow a **real, reproducible accuracy number** —
  closes the R5 honesty gap directly
- `context_builder`'s schema retrieval is the natural home for a **non-PII column
  allowlist at generation** — the bounded-PII path ADR 0006 chases (Phase 2)
- shared sqlglot means AgentFlow's PII deny-gate plugs into the generated SQL
  unchanged, as defense-in-depth behind the generation-time allowlist
- it is a genuinely deployable engine (API-keyed provider), not a browser hack

Cons:

- adds `langgraph` + `chromadb` as serving dependencies (heavier than seven
  regexes; ChromaDB pulls onnxruntime)
- requires building and shipping a schema index for the demo warehouse
- larger integration surface than option 1

### 3. Copy only the schema-RAG piece into the current engine

Rejected: schema-RAG is the cheapest of the three assets to lift but the least
valuable in isolation. Without the validate/repair loop and the eval harness we
still have no accuracy number and no measured quality, and we would be
maintaining a hand-rolled retrieval layer instead of the tuned one. This is the
worst of both — new dependency weight, none of the confidence.

## Decision

**Adopt the `D:\NL_SQL` engine as AgentFlow's NL→SQL implementation**, replacing
the seven-regex rule-based default and the thin `_llm_translate` GraceKelly path.

Concretely:

- **Model routing goes through the GraceKelly orchestration API — not Mistral,
  and never a direct provider SDK.** The portfolio NL_SQL project stays on
  Mistral; for AgentFlow we add a `GraceKellyProvider` implementing NL_SQL's
  `LLMProvider` protocol (`generate(GenerateRequest) -> GenerateResponse`) that
  POSTs to `${GRACEKELLY_URL}/api/v1/orchestrate` with `{prompt, model}` and reads
  `output_text` — reusing the transport already built in `nl_engine._llm_translate`
  (commit `cbfb363`). It is registered as `case "gracekelly"` in `build_provider`
  and selected by settings; the default model is `claude-sonnet-5`
  (`GRACEKELLY_NL_SQL_MODEL`), which GraceKelly serves today. This keeps the
  "no direct model SDK in AgentFlow" invariant from ADR 0006 (§Decision) and the
  standing directive that any Sonnet-5 call routes through GraceKelly.
- **The eval harness is ported first** (before the full runtime swap) so we get a
  measured AgentFlow accuracy number early and cheaply. It is the highest
  value-per-effort step and closes the R5 gap on its own.
- **Schema-grounding becomes the bounded-PII mechanism.** `context_builder`
  filters the retrieved/exposed schema to a non-PII column allowlist (from
  `config/pii_fields.yaml`), so the model is never shown PII columns to select.
  This is the "allowlist at generation" ADR 0006 identified as the bounded path;
  the sqlglot deny-gate remains behind it as defense-in-depth, not the sole
  boundary. This lands with ClickHouse Phase 2.
- **Prompt dialect stays DuckDB-flavored** (consistent with ADR 0006): the
  serving backend transpiles to ClickHouse; the generator does not need to know
  the physical engine.

### Sequencing

1. **ADR (this document).**
2. **Port the eval harness** → an honest AgentFlow EA number (cheap, closes R5).
3. **Schema-grounding for bounded PII** → non-PII allowlist in `context_builder`
   (core of ClickHouse Phase 2).
4. **Full engine port** → repoint `nl_sql/llm/` to the GraceKelly Sonnet-5
   provider and route the serving NL→SQL entrypoint through the LangGraph
   pipeline.

## Consequences

### Positive

- AgentFlow gains a measured, reproducible NL→SQL accuracy number — the honesty
  gap in the R5 rubric closes with a runnable artifact.
- The bounded-PII problem gets a real mechanism (allowlist at generation) instead
  of another SQL-shape denylist.
- The engine is deployable (API-keyed provider through GraceKelly), not dependent
  on browser automation.
- Validate/repair + execution feedback replace "trust the first string that
  starts with SELECT".

### Negative

- `langgraph` and `chromadb` become serving dependencies (ChromaDB pulls
  onnxruntime; heavier image, as with the ClickHouse cutover).
- A schema index must be built and shipped for the demo warehouse; index build
  becomes part of the demo/CI setup.
- The integration surface is larger than the current file; the port is a
  multi-step program, not a single PR.

### Neutral / non-goals

- The portfolio `D:\NL_SQL` project is **not** changed by this ADR — it stays on
  Mistral. The GraceKelly routing is an AgentFlow-side branch of the engine, not
  a change to the upstream demo.
- Making the semantic layer emit ClickHouse-native SQL remains out of scope (per
  ADR 0006): the generator keeps emitting DuckDB-flavored SQL and the backend
  transpiles.

## Integration approach: vendor + hybrid execution (decided 2026-07-01)

The engine is **vendored** into AgentFlow (a copy under `src/`), not consumed as
an external package: `D:\NL_SQL` is a portfolio Streamlit app, not a published
library, so a copy keeps AgentFlow self-contained and deployable.

Two facts about the NL_SQL engine shape the port:

- Its DB layer (`nl_sql/db/connection.py`) is SQLAlchemy over **sqlite /
  postgresql only** — it has no DuckDB dialect. AgentFlow's warehouse is DuckDB.
- Its `context_builder` retrieves schema via a **ChromaDB** index with Mistral
  embeddings. AgentFlow's demo warehouse is five tables — small enough that
  retrieval is trivial (all tables fit the prompt).

So the port is **hybrid**, not a wholesale lift:

- **Generation half — vendored from NL_SQL:** the LangGraph pipeline
  (`generate_sql → validate → repair_once`), the prompt templates, and the
  sqlglot validation. `sql_provider` = the **`GraceKellyProvider`** added to
  `nl_sql/llm/` this session (default `claude-sonnet-5`, verified live: a real
  Sonnet 5.0 browser call returns correct SQL). **The generation path runs on
  Sonnet 5.0 via GraceKelly — never Mistral, never a direct SDK.**
- **Context — lightweight, no ChromaDB for the demo:** build the `ContextBundle`
  directly from AgentFlow's `DataCatalog` (all demo tables), skipping ChromaDB /
  onnxruntime / embeddings. Revisit RAG only if the schema grows past what fits a
  prompt.
- **Execution half — AgentFlow's own DuckDB path + PII deny-gate:** do not vendor
  NL_SQL's SQLAlchemy sqlite executor. Run generated SQL through AgentFlow's
  existing DuckDB serving path so the PII boundary (`sql_guard`) stays in force.

New dependency: `langgraph` (pipeline). `sqlglot` and `langchain-core` are
already present; ChromaDB is deliberately avoided for the demo.

### Vendoring steps (each verified before the next)

1. Install `langgraph`; vendor the generation subtree into
   `src/serving/semantic_layer/nl_sql_engine/`, import-clean.
2. Build a demo `ContextBundle` from `DataCatalog`; run `generate_sql` →
   GraceKelly Sonnet 5 → SQL for a demo question (live).
3. Wire the pipeline as the `translate_nl_to_sql` LLM path; execute via
   AgentFlow's DuckDB + deny-gate.
4. Run the eval harness (ADR step 2) through it → the real Sonnet-5 EA number on
   the demo (vs the 38.9% rule-based baseline).

## Follow-up

- Execute the sequence above (eval port → schema-grounding PII → full port).
- Track the accuracy number in the R5/E-workstream once the eval port lands.
- Revisit the schema-index build/ship story alongside the ClickHouse cutover
  (`docs/clickhouse-cutover-plan.md`), since both add demo-time setup weight.
- See ADR 0006 for the serving-engine decision this builds on and the bounded-PII
  motivation.
