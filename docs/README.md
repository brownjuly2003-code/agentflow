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
| Operate or troubleshoot it | [Operational runbook](runbook.md) and [on-call runbooks](runbooks/README.md) |
| Review closure boundaries | [Project closure](PROJECT_CLOSURE.md) |

## Documentation sets

| Set | Purpose | Maintenance rule |
| --- | --- | --- |
| [MkDocs walkthrough](index.md) | Curated learning path: quickstart, architecture, API, SDK, deployment, observability, troubleshooting | Keep concise and runnable; `mkdocs build --strict` must pass |
| Current-state references | `STATUS.md`, `architecture.md`, `release-readiness.md`, `security-audit.md`, `runbook.md` | Update with code or operational truth; links and current versions are gated |
| Product and domain specs | `product.md`, `domain.md`, `generator-spec.md`, `ops-surfaces-spec.md` | Explain stable behavior and invariants; do not carry live status |
| Operations | [`operations/`](operations/), [`runbooks/`](runbooks/), and [control-plane testing](operations/testing-control-plane.md) | Current procedures stay actionable; superseded execution narratives move to the archive |
| Decisions | [`decisions/`](decisions/) | ADRs are immutable point-in-time decisions; supersede with a new ADR |
| Evidence | [`perf/`](perf/), [`evidence/`](evidence/), dated security and acceptance reports | Preserve measured facts and exact identity; never rewrite history as current truth |
| DV2 extension | [`dv2-multi-branch/`](dv2-multi-branch/) | Keep its architecture, schema, release record, and demo evidence together |
| Generated/reference artifacts | `openapi.json`, `sdk-capabilities.md`, `quality.md`, and the [latest load benchmark](perf/load-benchmark-latest.md) | Regenerate from the owning source; do not hand-edit generated output |
| Archive | [`archive/`](archive/) | Preserve superseded or duplicate narrative with provenance; archived text is not current guidance |

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
python scripts/validate_project_claims.py
python -m pytest tests/unit/test_docs_links.py tests/unit/test_docs_single_source_of_truth.py tests/unit/test_project_claims.py -q
python -m mkdocs build --strict
```

The link checker covers the tracked corpus, while MkDocs intentionally builds
only the curated walkthrough listed in `mkdocs.yml`.
