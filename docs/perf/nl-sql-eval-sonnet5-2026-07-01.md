# NL->SQL execution-accuracy eval — Sonnet 5 via GraceKelly — 2026-07-01

The real accuracy number for AgentFlow's **LLM** NL->SQL path, measured through
the vendored NL_SQL engine (ADR 0008) on **Claude Sonnet 5 via GraceKelly**.
This is ADR 0008 step 4: run the same 18-question harness that measured the
rule-based baseline (`nl-sql-eval-2026-07-01.md`, 38.9%) through the ported
engine, so the two numbers are directly comparable.

## Headline

| Engine | Overall EA | in-pattern | out-of-pattern |
|---|---|---|---|
| rule-based (shipped default) | 38.9% (7/18) | 87.5% (7/8) | 0.0% (0/10) |
| **Sonnet 5 via GraceKelly** (opt-in LLM) | **83.3% (15/18)** | 87.5% (7/8) | **80.0% (8/10)** |

**+44.4 pp overall.** The rule-based translator answers only its seven designed
shapes and returns *nothing* for everything else (0/10 out-of-pattern). The
Sonnet-5 engine answers **8 of the 10** questions the rule-based path can't touch
at all — the exact gap ADR 0008 set out to close. The in-pattern number is
unchanged (7/8) because both engines hit the same lone near-miss there
(`top_products`, see below).

## What EA means here

Execution accuracy = run the predicted SQL and the gold SQL against the same
seeded in-memory DuckDB and compare **result sets** (column names ignored;
floats within 1e-6; `ORDER BY` in gold ⇒ order-sensitive, else set equality; a
`None` prediction or a pred that raises = a miss). Identical metric and gold set
as the rule-based run — only `GRACEKELLY_URL` was set, which routes
`translate_nl_to_sql` through the vendored engine.

## The three misses — all projection granularity, none semantic

Every failure is the model picking a **different column set** than the gold
query, not a wrong answer. It identified the right entity in all three:

| id | gold columns | pred columns | nature |
|---|---|---|---|
| `top_products` | `(name, category, price, stock)` | `(name, price)` | gold template is unusually wide (4 cols); model returned the natural 2 |
| `most_expensive_product` | `(name)` | `(name, price)` | model appended the ranking measure it sorted on |
| `top_spender` | `(user_id)` | `(user_id, spent)` | model appended the ranking measure it sorted on |

`most_expensive_product` and `top_spender` are the canonical "top X **by** Y"
trap: the prompt's projection-discipline rule says Y belongs in `ORDER BY`, not
`SELECT`, but the model still returned it. `top_products` is the mirror image —
the *gold* is the quirky one (the rule-based template projects four columns for
"top 3 products by price"), and the model returned the leaner, arguably more
correct answer. All three are the well-known EA brittleness around projection
cardinality — the entity is right; the exact column tuple is a judgment call the
metric scores strictly.

These are cheap to close if desired (tighten the projection rule / few-shots, or
loosen the gold on ranking questions), but they are **not** correctness bugs, so
the honest number stands at 83.3% rather than being massaged upward.

## Latency

18 questions, single generation pass each (no repairs fired — every candidate
passed the static guard first try). ~11-24 s per question over the GraceKelly
browser path; ~4.5 min wall-clock total. This is an evaluation/probe surface,
not an interactive one.

## Reproduce (needs a running GraceKelly)

```
# start GraceKelly on :8011 (browser mode, logged-in profile), then:
GRACEKELLY_URL=http://127.0.0.1:8011 \
GRACEKELLY_NL_SQL_MODEL=claude-sonnet-5 \
python -m scripts.run_nl_sql_eval --md report.md
```

## Honesty notes

- **This number is NOT pinned in CI.** It comes from a live, non-deterministic
  browser call to Sonnet 5 through GraceKelly, which CI has no access to. The
  CI-pinned baseline stays the rule-based 38.9% (`tests/unit/test_nl_sql_eval.py`);
  this file records the measured LLM result and the run that produced it
  (2026-07-01, model `claude-sonnet-5-0`).
- **Time windows remain a no-op** (all seed rows < 1 h old, seeded via DuckDB
  `NOW()`), same as the baseline run — EA measures translation coverage and
  correctness, not clock precision.
- **The path measured is the translator**, executed directly. The real `/query`
  path additionally runs the `sql_guard` PII deny-gate, which would 403 some
  shapes; that is a separate security concern, not translation accuracy.
