# Documentation archive

The archive preserves superseded or duplicated documentation that is no longer
the best entrypoint. Nothing here is deleted evidence, and nothing here should
be read as current runtime or production status.

## Archive contract

Every archived document must record:

- its original path;
- the archive date;
- why it moved;
- the current replacement or source of truth;
- whether the content is historical narrative, generated output, or immutable
  evidence.

Moves use `git mv`, preserve content unless a short archive header is added,
and update all inbound links in the same commit. Dated evidence already placed
under `docs/perf/`, `docs/evidence/`, or an ADR directory stays there; those
directories are historical by design and do not need a second archive move.

## Current archive map

| Area | Contents | Current replacement |
| --- | --- | --- |
| [`release-history-v1-v2.md`](release-history-v1-v2.md) | README release narrative for v1.1.0 through v2.0.0 | [`CHANGELOG.md`](../../CHANGELOG.md) and [`STATUS.md`](../STATUS.md) |
| [`plans/`](plans/) | Superseded planning interpretations | Active root plan or current status document named in each archived file |
| [`performance/`](performance/README.md) | Non-canonical benchmark reports and superseded performance follow-ups moved from the `docs/` root | [`perf/load-benchmark-latest.md`](../perf/load-benchmark-latest.md) and [`perf/entity-benchmark-contract.md`](../perf/entity-benchmark-contract.md) |
| [`product/`](product/README.md) | Point-in-time market and cost analyses moved from the `docs/` root | [`product.md`](../product.md) and [`STATUS.md`](../STATUS.md) |
| [`operations/`](operations/README.md) | Consumed operational execution contracts whose identities and commands must not be reused | [`operations/README.md`](../operations/README.md) and the current guide named by each archived file |

Return to the [documentation hub](../README.md).
