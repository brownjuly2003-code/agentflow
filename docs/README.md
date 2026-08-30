# AgentFlow documentation

> Updated: 2026-08-26. This page is the navigation hub for the complete
> documentation corpus. It does not replace engineering evidence or status.

AgentFlow has documentation for several audiences: users evaluating the
project, developers changing the runtime, operators running the data path, and
reviewers validating historical evidence. Start from the smallest document
that answers the question; follow evidence links only when the underlying proof
is needed.

## Start here

| Need | Canonical entry |
| --- | --- |
| Understand the product | [Repository README](../README.md) |
| Run it locally | [Quickstart](quickstart.md) |
| Check what is proven now | [Engineering status](STATUS.md) |
| Understand the system | [Architecture walkthrough](architecture/index.md) |
| Integrate through HTTP | [API guide](api/index.md) |
| Use a client library | [SDK guide](sdk.md) |
| Operate or troubleshoot it | [Operations index](operations/README.md), [operational runbook](runbook.md), and [on-call runbooks](runbooks/README.md) |
| Review closure boundaries | [Project closure](PROJECT_CLOSURE.md) |

## Documentation sets

| Set | Purpose | Maintenance rule |
| --- | --- | --- |
| [MkDocs walkthrough](index.md) | Curated learning path: quickstart, architecture, API, SDK, deployment, observability, troubleshooting | Keep concise and runnable; `mkdocs build --strict` must pass |
| Current-state references | `STATUS.md`, `architecture.md`, `release-readiness.md`, `security-audit.md`, `runbook.md` | Update with code or operational truth; links and current versions are gated |
| Product and domain specs | `product.md`, `domain.md`, `generator-spec.md`, `ops-surfaces-spec.md` | Explain stable behavior and invariants; do not carry live status |
| Operations | [Operations index](operations/README.md) and [on-call runbooks](runbooks/README.md) | Current procedures stay actionable; superseded execution narratives move to the archive |
| Decisions | [`decisions/`](decisions/) | ADRs are immutable point-in-time decisions; supersede with a new ADR |
| Evidence | [`perf/`](perf/), [`evidence/`](evidence/), dated security and acceptance reports | Preserve measured facts and exact identity; never rewrite history as current truth |
| DV2 extension | [`dv2-multi-branch/`](dv2-multi-branch/) | Keep its architecture, schema, release record, and demo evidence together |
| Generated/reference artifacts | [Generated-reference ownership](#generated-reference-ownership), [`sdk-capabilities.md`](sdk-capabilities.md), [`quality.md`](quality.md), and the [full-load benchmark lifecycle](perf/load-benchmark-latest.md) | Regenerate deterministic families; keep mutable measurements in ignored artifacts |
| Archive | [`archive/`](archive/) | Preserve superseded or duplicate narrative with provenance; archived text is not current guidance |

## Generated-reference ownership

One writer owns each current generated family. For deterministic references,
run the writer when its source changes, commit the complete output family, and
run the drift check before review. Host- and time-dependent measurement outputs
stay in ignored runtime artifacts; promote only immutable, date-stamped evidence.
Do not hand-edit or update only part of the family.

| Family | Tracked outputs | Write | Drift check | Lifecycle |
| --- | --- | --- | --- | --- |
| OpenAPI and agent tools | `docs/openapi.json`, `docs/agent-tools/claude-tools.json`, `docs/agent-tools/openai-tools.json` | `python scripts/export_openapi.py` | `python scripts/export_openapi.py --check` | Current generated references; all three outputs move together. The contract workflow runs the drift check. |
| SDK capabilities | `docs/sdk-capabilities.md` | `python scripts/export_sdk_capabilities.py` | `python scripts/export_sdk_capabilities.py --check` | Current generated reference from `config/project_claims.toml`; the CI project-claims gate also checks SDK method parity and output drift. |
| Quality gates | `docs/quality.md` | `python scripts/export_quality_reference.py` | `python scripts/export_quality_reference.py --check` | Deterministic current reference from `config/project_claims.toml`; the CI project-claims gate checks config alignment and output drift. |
| Full-load benchmark | None; `docs/perf/load-benchmark-latest.md` is a lifecycle page | `python scripts/run_benchmark.py` writes `.artifacts/benchmark/benchmark.md` and `.artifacts/benchmark/current.json` | Runtime metric comparison, not byte drift | Measurements vary by host and time. CI consumes ignored artifacts; promote only date-stamped evidence with provenance. |
| Demo freshness benchmark | None; `docs/perf/freshness-benchmark.md` is a lifecycle page | `python scripts/benchmark_freshness.py` writes `.artifacts/freshness/freshness-benchmark.md` and `.artifacts/freshness/current.json` | Runtime evidence review, not byte drift | Measurements vary by host and time. The 2026-06-06 snapshot is archived; promote only date-stamped evidence with provenance. |

Historical OpenAPI comparison captures `docs/perf/live_openapi_local.json` and
`docs/perf/live_openapi_ci.json` are evidence, not current generated
references. Preserve those captures under the evidence policy; do not replace
them when refreshing the current OpenAPI family.

The SDK capability family currently has one tracked output and no historical
generated snapshots. If a dated capability snapshot is needed as evidence,
preserve it under the evidence/archive policy instead of refreshing it as the
current contract.

`docs/quality.md` contains only reproducible quality-gate claims. The dynamic
`scripts/quality_report.py` collector writes
`.artifacts/quality/quality-report.md` by default because its timestamp and
coverage, security, mutation, chaos, and load inputs are host-specific. The
last tracked dynamic report is preserved as a
[historical generated snapshot](archive/quality-report-2026-07-23.md); do not
refresh it as the current reference.

The full-load benchmark has the same dynamic boundary: its former mutable
tracked report is preserved as a
[2026-04-17 historical snapshot](archive/performance/load-benchmark-2026-04-17.md).
The stable [artifact lifecycle page](perf/load-benchmark-latest.md) names the
runtime outputs, CI comparison, promotion rule, and protected tracked paths.

The demo freshness benchmark is also host- and time-dependent. Its
[artifact lifecycle page](perf/freshness-benchmark.md) names the ignored
runtime outputs and protects both tracked documentation paths; the last
mutable report is preserved as a
[2026-06-06 historical snapshot](archive/performance/freshness-benchmark-2026-06-06.md).

## Sources of truth

| Topic | Source of truth | Supporting or historical material |
| --- | --- | --- |
| Package version | [`pyproject.toml`](../pyproject.toml) | [Changelog](../CHANGELOG.md), release readiness |
| Machine claims | [`config/project_claims.toml`](../config/project_claims.toml) | Status and evidence files linked by the manifest |
| Current engineering gates | [Engineering status](STATUS.md) | Dated acceptance/evidence records |
| Lifecycle and non-goals | [Project closure](PROJECT_CLOSURE.md) | Audit and planning records |
| Runtime design | [Architecture reference](architecture.md) | [Walkthrough](architecture/index.md) and ADRs |
| API contract | [`openapi.json`](openapi.json) and running FastAPI schema | API guide/reference and SDKs |
| Security policy | [`SECURITY.md`](../SECURITY.md) | Security audit and dated remediation evidence |
| Release history | [Changelog](../CHANGELOG.md) | [Archived narrative](archive/release-history-v1-v2.md) |

## Placement rules

- Keep `docs/` root for stable entrypoints and current references. Do not add a
  new dated report there.
- The exact tracked root allowlist is enforced by
  `scripts/check_docs_root_placement.py`; update it only for an intentional
  stable entrypoint or current reference.
- Put immutable measurements in `perf/` or `evidence/`, operational procedures
  in `operations/` or `runbooks/`, and decisions in `decisions/`.
- Do not delete documentation. Move superseded or duplicate narrative to
  `archive/` with its original path, archive date, reason, and replacement.
- Update every inbound link in the same commit as a move. Use `git mv` so file
  history remains discoverable.
- Keep credentials, raw prompts, private payloads, databases, and local runtime
  artifacts out of documentation.

## Verification

Run the proportional documentation gate after edits:

```powershell
python scripts/check_docs_links.py
python scripts/check_docs_root_placement.py
python scripts/validate_project_claims.py
python -m pytest tests/unit/test_docs_links.py tests/unit/test_docs_root_placement.py tests/unit/test_docs_single_source_of_truth.py tests/unit/test_project_claims.py -q
python -m mkdocs build --strict
```

The link checker covers the tracked corpus, while MkDocs intentionally builds
only the curated walkthrough listed in `mkdocs.yml`.
