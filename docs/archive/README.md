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

`tests/unit/test_archive_provenance.py` runs `scripts/check_archive_provenance.py`
over every tracked `docs/archive/**/*.md` except `README.md` index pages and fails
when any of the five facts is missing from the first 40 lines (the replacement
fact is also satisfied when the `Original path` still names a tracked file).
`tests/unit/test_historical_claims.py` runs `scripts/check_historical_claims.py`
over every tracked point-in-time page under `docs/archive/`, `docs/decisions/`,
`docs/evidence/` (except `INDEX.md`), `docs/migration/` and `docs/perf/` and
fails when a page uses living-status vocabulary owned by `docs/STATUS.md`:
`Updated:`, `production accepted`, `production-accepted`, `closure candidate`,
or `release line`.
The orphan-link checker `scripts/check_docs_orphans.py` (unit test
`tests/unit/test_docs_orphans.py`) covers every tracked living `docs/**/*.md` page outside
those historical directories and `docs/dv2-multi-branch/` (hubs `docs/README.md`
and `docs/index.md` need no inbound) and fails when a living page has no inbound
link from tracked Markdown or the MkDocs nav: it must be reachable from the
documentation hub or archived with provenance.
The generated-owner checker `scripts/check_generated_reference_owners.py` (unit test
`tests/unit/test_generated_reference_owners.py`) pins the generated-reference ownership
table in `docs/README.md` to the tracked tree: it fails when a row names a path Git does
not track, when a `.artifacts/` runtime path has become tracked, when a row runs a
`--check` drift check without listing a tracked output, or when a tracked
`scripts/**/*.py` that declares `--check` has no row at all.
The anchor checker `scripts/check_docs_anchors.py` (unit test
`tests/unit/test_docs_anchors.py`) requires every tracked Markdown file to decode as
strict UTF-8 with no U+FFFD, and every living-page fragment link to resolve to a
MkDocs heading id.
The Updated-stamp checker `scripts/check_docs_updated_stamps.py` (unit test
`tests/unit/test_docs_updated_stamps.py`) allows `Updated` stamps only on the
dated-page allowlist and only in the canonical form.

## Current archive map

| Area | Contents | Current replacement |
| --- | --- | --- |
| [`release-history-v1-v2.md`](release-history-v1-v2.md) | README release narrative for v1.1.0 through v2.0.0 | [`CHANGELOG.md`](../../CHANGELOG.md) and [`STATUS.md`](../STATUS.md) |
| [`plans/`](plans/) | Superseded planning interpretations | Active root plan or current status document named in each archived file |
| [`performance/`](performance/README.md) | Historical generated benchmarks, non-canonical reports, and superseded performance follow-ups | [Full-load](../perf/load-benchmark-latest.md), [demo freshness](../perf/freshness-benchmark.md), [S8 real-path freshness](../perf/freshness-e2e-realpath.md), and [real-path throughput](../perf/throughput-realpath.md) lifecycles plus [`perf/entity-benchmark-contract.md`](../perf/entity-benchmark-contract.md) |
| [`product/`](product/README.md) | Point-in-time market and cost analyses moved from the `docs/` root | [`product.md`](../product.md) and [`STATUS.md`](../STATUS.md) |
| [`operations/`](operations/README.md) | Consumed operational execution contracts whose identities and commands must not be reused | [`operations/README.md`](../operations/README.md) and the current guide named by each archived file |
| [`quality-report-2026-07-23.md`](quality-report-2026-07-23.md) | Host- and time-specific generated quality snapshot formerly at `docs/quality.md` | Deterministic [quality-gate reference](../quality.md) and ignored local `.artifacts/quality/` reports |

Return to the [documentation hub](../README.md).
