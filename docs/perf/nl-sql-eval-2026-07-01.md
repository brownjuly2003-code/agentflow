# NL->SQL execution-accuracy eval — 2026-07-01

The first honest, reproducible accuracy number for AgentFlow's NL->SQL path.
Until now "natural-language queries work" was an unbacked claim (road-to-9.8
R5). This harness measures it. It is the eval-harness port called for by
**ADR 0008** (adopt the NL_SQL engine), step 2.

## Headline

| Engine (this run) | Overall EA | in-pattern | out-of-pattern |
|---|---|---|---|
| **rule-based** (shipped default) | **27.8%** (5/18) | 62.5% (5/8) | 0.0% (0/10) |

The shipped translator is `nl_engine._rule_based_translate`: seven regexes that
map a fixed set of question shapes to SQL templates. It answers its seven
designed shapes and **everything else not at all** — which is the point of
measuring: it quantifies the gap the NL_SQL adoption is meant to close. The
Sonnet-5 engine measured through the same harness scores **88.9%** — see
`nl-sql-eval-sonnet5-2026-07-01.md`.

> The demo ships with `GRACEKELLY_URL` unset, so the shipped engine is the
> rule-based path — this 27.8% is the number a real demo user experiences today,
> not a worst case.

> **Gold-set normalisation (2026-07-01).** The gold set now enforces a single
> minimal-projection convention (entity questions → the entity's name/id;
> aggregates → the value). Two golds (`top_products`, `out_of_stock`) previously
> carried wide multi-column "cards" copied from the rule-based templates
> themselves — the only golds that broke the convention, and inconsistent with
> each other. Normalising them dropped the rule-based number from 38.9% to 27.8%,
> because the templates **over-project**: they return `product_id`/`category`/
> `stock_quantity` the question never asked for, so they now miss the two
> product-listing questions they used to "pass" by matching their own wide gold.
> That over-projection is a real property of the rule-based path, now surfaced
> honestly rather than hidden by a gold that mirrored the template.

## What EA means here

Execution accuracy = run the predicted SQL and the gold SQL against the same
seeded DuckDB and compare **result sets** (not SQL text). Ported from the
NL_SQL engine's BIRD-style metric (`scripts/nl_sql_eval/metrics.py`):

- column names are ignored (any aliasing is fine if the values match);
- floats/Decimals compared with 1e-6 tolerance;
- `ORDER BY` in gold => order-sensitive; otherwise set equality;
- a `None` prediction ("untranslatable") or a pred that raises = a miss.

## Methodology / honesty notes

- **Warehouse** (`scripts/nl_sql_eval/warehouse.py`): a fresh in-memory DuckDB
  seeded with a fixed 8-order / 6-product / 5-session dataset. The DDL is
  imported from the production `local_pipeline._ensure_tables`, so the eval
  schema cannot drift from what the demo ships. `users_enriched` is derived from
  `orders_v2` with the same aggregation the production upsert uses.
- **Time windows are a deliberate no-op.** Every fact row is seeded via DuckDB's
  own `NOW() - INTERVAL '5 minutes'` (never a Python datetime — avoids all
  timezone-domain mismatch with the queries' `NOW()`). Because every row is
  < 1 hour old, the rule-based translator's `NOW() - INTERVAL '1 hour'` filter
  is a no-op. **The harness measures translation coverage/correctness, not
  time-window precision.** A future revision could add explicitly old rows to
  test window handling.
- **The path measured is the translator, not the served endpoint.** The eval
  calls `translate_nl_to_sql` and executes the result directly. The real
  `/query` path additionally runs the PII deny-gate (`sql_guard`), which would
  403 some of these (e.g. `SELECT *` over a PII table). That is a separate
  security concern (ADR 0006 / the deny-gate), not translation accuracy.

## The three in-pattern misses — all fixed-projection brittleness

- `conversion_rate`: the template returns a three-column breakdown
  (`conversions`, `total_sessions`, `conversion_pct` as a 0–100 percentage) while
  the gold is a single 0–1 ratio — different shape *and* scale.
- `top_products` / `out_of_stock`: the templates return a wide product "card"
  (`product_id`/`name`/`category`/`price`/`stock_quantity`) while the gold is the
  product names. The template **over-projects** columns the question did not ask
  for.

All three are the same lesson: a template that emits a fixed projection is
brittle — it can only match a question whose expected columns happen to equal its
hard-coded list.

## Per-item results

- in-pattern: 62.5% (5/8)
- out-of-pattern: 0.0% (0/10)

| id | category | match | reason |
|---|---|---|---|
| revenue_total | in-pattern | PASS | ok |
| revenue_window | in-pattern | PASS | ok |
| avg_order_value | in-pattern | PASS | ok |
| top_products | in-pattern | FAIL | over-projects: pred returns the wide card, gold is product names |
| conversion_rate | in-pattern | FAIL | set mismatch (3-col breakdown vs single ratio) |
| out_of_stock | in-pattern | FAIL | over-projects: pred returns the wide card, gold is product names |
| order_lookup | in-pattern | PASS | ok |
| active_sessions | in-pattern | PASS | ok |
| cancelled_count | out-of-pattern | FAIL | untranslatable (translator returned no SQL) |
| orders_by_status | out-of-pattern | FAIL | untranslatable (translator returned no SQL) |
| most_expensive_product | out-of-pattern | FAIL | untranslatable (translator returned no SQL) |
| products_in_category | out-of-pattern | FAIL | untranslatable (translator returned no SQL) |
| total_order_count | out-of-pattern | FAIL | untranslatable (translator returned no SQL) |
| top_spender | out-of-pattern | FAIL | untranslatable (translator returned no SQL) |
| avg_product_price | out-of-pattern | FAIL | untranslatable (translator returned no SQL) |
| converted_sessions | out-of-pattern | FAIL | untranslatable (translator returned no SQL) |
| distinct_categories | out-of-pattern | FAIL | untranslatable (translator returned no SQL) |
| user_count | out-of-pattern | FAIL | untranslatable (translator returned no SQL) |

## Reproduce

```
python -m scripts.run_nl_sql_eval                 # print
python -m scripts.run_nl_sql_eval --md report.md  # + markdown
```

The baseline shape is pinned by `tests/unit/test_nl_sql_eval.py` so this number
cannot drift silently: if the translator changes, that test fails and this
report must be regenerated.
