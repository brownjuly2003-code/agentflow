# AgentFlow Release Readiness

**Date**: 2026-04-20
**Last updated**: 2026-04-28
**Version**: v1.1.0 + post-v1.1 CDC follow-up + 2026-04-27 audit closure sprint
**Status**: v1.0.0 published; v1.0.1 patch released for clean-clone support; v1.1.0 release line prepared with SDK/runtime split; post-v1.1 CDC operationalization checked in; the 2026-04-27 audit closure sprint landed six commits closing all P0/P1/P2 findings (see [docs/audits/2026-04-27/](audits/2026-04-27/README.md)); registry credentials configured; main protected with required status checks; live v1.1.0 publish ready after the current auth-cache/docs worktree is committed, pushed, CI is green, and `v1.1.0` is re-tagged

## Executive Summary

AgentFlow закрыл технические блокеры из internal audit baseline от 2026-04-12, опубликовал v1.0.0 на GitHub 2026-04-20 и выпустил v1.0.1 patch release для clean-clone установки. Поверх v13.5 security refresh работы v15-v18 закрыли GTM/documentation хвост: narrative API reference, competitive analysis, security audit, landing page, README/glossary/LICENSE/CHANGELOG, public repo, and Fly.io demo config are now part of the release evidence. `bandit_diff.py` остаётся зелёным against the checked-in baseline, а clean-clone verification для patch release зафиксирован в `CHANGELOG.md` (`pytest tests/unit -q`: 340 passed). Retrospective reconstruction of the lost audit artifact is preserved in `docs/audit-history.md`.

The v1.1 line split runtime and SDK distribution identity: the runtime publishes as `agentflow-runtime`, while the Python SDK publishes as `agentflow-client` and keeps the `agentflow` import path. The current post-v1.1 follow-up operationalizes ADR 0005 with Debezium/Kafka Connect local compose, a Kubernetes-shaped Helm chart, raw CDC topic bootstrap, and canonical CDC normalization before downstream validation.

## Current Status (2026-04-28)

| Area | Clear status |
|------|--------------|
| Public repository | Published and release-ready from the checked-in evidence trail |
| Runtime package | `agentflow-runtime` is the root distribution name |
| Python SDK package | `agentflow-client` is the PyPI distribution; `from agentflow import ...` stays unchanged |
| Registry publishing | Local build/pack/twine preflight is green; PyPI pending Trusted Publishers for `agentflow-runtime` and `agentflow-client` are visible in the PyPI account; GitHub `pypi` environment exists; GitHub Actions secret `NPM_TOKEN` exists; live publish is still incomplete until the release commit/tag runs green |
| CDC local path | Checked in: compose source DBs, Kafka Connect image, connector registration, topic bootstrap, and integration tests |
| CDC Kubernetes path | Checked in: `helm/kafka-connect` chart, values schema, connector hooks, and topic bootstrap hook |
| CDC production onboarding | Not done: real hostnames, table scope, network path, and secret owner still need an explicit decision |
| Recorded full-suite evidence | Current auth-cache worktree full-suite pass on 2026-04-28: 724 passed, 4 skipped in 498.66s with Redis running and project-local pytest temp/cache paths. Targeted auth file: 11 passed; all unit tests: 433 passed; contract/e2e subset: 35 passed. The earlier chaos-smoke pre-commit hang is no longer the active blocker. |

## Status by BCG Dimension

| Направление | Было (2026-04-12) | Стало (2026-04-20) | Комментарий |
|-------------|-------------------|---------------------|-------------|
| Продукт | 6.5 / 10 | 6.5 / 10 | Competitive analysis is done, but PMF validation remains post-release |
| Дизайн | 7.5 / 10 | 8.0 / 10 | Added minimal `/admin` dashboard |
| Код | 7.0 / 10 | 9.0 / 10 | Performance, query safety, code health closure |
| DevOps | 8.5 / 10 | 9.0 / 10 | CI gates, chaos/load workflows, terraform validation |
| Документация | 9.0 / 10 | 9.7 / 10 | v15-v17 close competitive, security, narrative API-reference, glossary, and publication docs |

## Performance Summary

Source: `docs/benchmark-baseline.json` generated 2026-04-17T13:37:10+03:00.

| Endpoint | p50 (ms) | p99 (ms) | RPS | Gate | Status |
|----------|----------|----------|-----|------|--------|
| GET /v1/entity/order/{id} | 55 | 300 | 4.24 | p50 < 100, p99 < 500 | ✅ |
| GET /v1/entity/product/{id} | 49 | 320 | 2.39 | p50 < 100, p99 < 500 | ✅ |
| GET /v1/entity/user/{id} | 38 | 290 | 3.07 | p50 < 100, p99 < 500 | ✅ |
| GET /v1/metrics/{name} | 53 | 220 | 7.27 | informational | ✅ |
| POST /v1/query | 74 | 370 | 5.22 | informational | ✅ |
| POST /v1/batch | 62 | 340 | 5.56 | informational | ✅ |

**Aggregate run:** 569 requests, 0 failures, 27.76 RPS, p50 56 ms, p95 260 ms, p99 330 ms.

## Code Health Snapshot

- God-class split completed for auth, alerts, and query modules with compatibility imports preserved.
- SQL injection exposure closed via parameterized queries and `sqlglot` AST validation.
- Flink critical paths now have 28 unit tests combined (`session_aggregator`: 12, `stream_processor`: 16).
- Silent exception cleanup is mostly complete; 5 `nosec B110` sites remain in rollback/audit paths with documented rationale.

## Known Limitations

- Phase 1 PMF work remains open: customer discovery, pricing validation, and first paying customers are post-release items, not technical blockers.
- Scope cut was intentionally not applied; v1.0.0 keeps the current 15-endpoint surface.
- Entity p99 remains 290-320 ms in `docs/benchmark-baseline.json` generated on 2026-04-17T13:37:10+03:00: above the earlier ~170 ms pre-regression lab result, but still inside the <500 ms gate.
- v14 changes only SDK resilience and SDK tests/docs, so this release records the entity p99 tail as a serving-path known limitation rather than claiming a new performance fix.
- Real Terraform `apply` has not been executed from GitHub Actions yet; current state is local `validate` plus workflow wiring.
- GitHub environments `staging`/`prod` with required reviewers are still a manual setup step.
- AWS OIDC role setup for GitHub Actions is still a manual setup step.
- SDK registry publish still needs successful production evidence. Local build/pack/twine preflight is green; publish workflows accept `sdk-v*`, release-candidate `v*-rc*`, and production `vX.Y.Z` tags; PyPI Trusted Publishing and GitHub `NPM_TOKEN` setup are complete. The local full-suite gate is green again; the remaining publish blocker is committing/pushing the current auth-cache/docs worktree, getting green CI, then pushing the approved release tag.
- Public benchmark on production hardware is still pending; current evidence is the checked-in single-node baseline.
- Chaos full suite runs on schedule; PR path covers smoke scope only.
- Production CDC source onboarding is not yet enabled. The checked-in CDC path covers local/demo and Kubernetes-shaped staging primitives; real production Postgres/MySQL attachment still needs hostnames, table scope, network access, and secret ownership.
- This Windows workstation has a local pytest startup issue unrelated to release code: `pyreadline3`, `pytest-metadata`, and `prometheus_client` can call `platform.*` and hang in Windows WMI before test output appears. The 2026-04-28 full-suite pass used a temporary project-local `sitecustomize` shim for that workstation only; the shim was removed after verification. Keep publishable docs free of absolute local paths.

## Release Checklist

- [x] Phase 0 blockers closed
- [x] Phase 2 code health completed for release scope
- [x] Phase 3 production readiness completed for release scope
- [x] Regression blockers fixed
- [x] Audit history reconstructed (`docs/audit-history.md`)
- [x] Phase 4 GTM docs and public entry assets completed
- [x] Benchmark baseline updated and gate definition documented
- [x] Release readiness report created
- [x] Bandit diff is green against the checked-in baseline
- [x] v1.1 runtime/SDK package split documented
- [x] Local and Kubernetes-shaped CDC operationalization checked in
- [ ] GitHub environments `staging`/`prod` configured with required reviewers
- [ ] AWS OIDC role configured for GitHub Actions
- [ ] First approved registry release tag produces green `Publish TypeScript SDK` and `Publish Python Packages` runs
- [ ] Production CDC source onboarding approved and configured
- [x] Last completed local full suite green on the release line — `724 passed, 4 skipped` in 498.66s on 2026-04-28 with the auth-cache worktree applied
- [x] Standalone chaos smoke green on `fb6aa14` (`3 passed in 44.29s` with `--timeout=60 --timeout-method=thread`); audit-closure HEAD also clean
- [x] Hashed API-key auth cache regression fixed locally and covered by `tests/unit/test_auth.py::test_hashed_key_authentication_caches_successful_plaintext`
- [x] SDK/runtime publish preflight completed locally without pushing a tag
- [x] 2026-04-27 audit closure sprint — all P0/P1/P2 findings from Claude Opus + Codex p1–p9 closed in 6 commits ([docs/audits/2026-04-27/README.md](audits/2026-04-27/README.md))
- [x] `main` protected with 12 required status checks (`lint`, `test-unit`, `test-integration`, `perf-check`, `helm-schema-live`, `schema-check`, `terraform-validate`, `bandit`, `safety`, `npm-audit`, `trivy`, `contract`) — `record-deployment` removed because the bot push it required is incompatible with the protection gate (chicken-and-egg: a self-push can't pre-satisfy 13 checks); DORA metrics fall back to the GitHub Actions API source already used by `scripts/dora_metrics.py`
- [x] `publish-pypi.yml` `environment: pypi` committed (`e8b1237`)
- [x] `sdk-ts/package-lock.json` committed; `npm audit` clean (0 vulns)
- [x] Vulnerable runtime/integrations deps bumped (`dagster>=1.13.1`, `langchain-core>=1.2.22`, `langchain-text-splitters>=1.1.2`, `langsmith>=0.7.31`)
- [ ] Phase 1 PMF work completed

## SDK Publish Proof Path

- Publish workflows accept standalone SDK tags (`sdk-vX.Y.Z`), release-candidate tags (`vX.Y.Z-rcN`), and production release tags (`vX.Y.Z`). `scripts/release.py` still creates `sdk-vX.Y.Z` tags for standalone SDK releases.
- Existing repo releases/tags (`v1.0.0`, `v1.0.1`, `v1.1.0`) are not registry-proof by themselves; proof requires green npm/PyPI publish workflow runs for the approved tag. The existing `v1.1.0` tag points at older commit `1ee89a3`, and there is no GitHub Release for that tag.
- Safe preflight for the first live SDK publish is documented in `docs/publication-checklist.md` and was completed locally on 2026-04-27 at `8d7088d`: build the TypeScript SDK, run `npm pack --dry-run`, build SDK wheels/sdists, and verify both editable install orders in a clean venv. The local run also built runtime wheels/sdists and passed `python -m twine check dist\* sdk\dist\*`.
- The first green proof for both publish workflows will be the next approved release tag push after the current auth-cache/docs worktree is reviewed, committed, pushed, and CI is green.
- Registry lookups on 2026-04-27 still returned not found for PyPI `agentflow-runtime`, PyPI `agentflow-client`, PyPI `agentflow-integrations`, and npm `@agentflow/client`; treat install commands as post-publish commands until the publish workflows are green.

## Verification Snapshot

| Check | Result | Evidence |
|-------|--------|----------|
| `docker compose up -d redis` + `python -m pytest tests/unit tests/integration tests/sdk --tb=line -q` | ✅ PASS | 543 passed, 1 warning in 238.60s |
| `bandit -r src/ sdk/ -f json -o .tmp/bandit-current.json --severity-level medium` + `python scripts/bandit_diff.py .bandit-baseline.json .tmp/bandit-current.json` | ✅ PASS | scan wrote `.tmp/bandit-current.json`; diff reports `No new findings (baseline: 1 issues)` |
| `python scripts/check_performance.py --baseline ... --current ... --max-regress 20` | ✅ PASS | performance gate passed for aggregate and all entity endpoints |
| `python scripts/generate_contracts.py --check` | ✅ PASS | exit code 0 |
| `terraform init -backend=false` + `terraform validate` | ✅ PASS | init exit 0, validate OK |
| `python -m pytest tests/chaos/test_chaos_smoke.py -v --timeout=180` | ✅ PASS | 3 passed in 42.08s |
| `python -c "from html.parser import HTMLParser; ..."` | ✅ PASS | `OK` |
| `python -c "import tomllib; ... fly.toml ..."` | ✅ PASS | `OK` |
| security doc evidence-path check | ✅ PASS | `OK - 20 evidence paths valid` |
| API reference coverage check | ✅ PASS | `OK - all 6 endpoints documented` |
| `python -m pytest -p no:schemathesis tests/unit/test_cdc_normalizer.py tests/unit/test_stream_processor.py tests/unit/test_validators.py tests/integration/test_cdc_capture.py tests/integration/test_kafka_connect_helm_chart.py -q` | ✅ PASS | 44 passed, 4 skipped on 2026-04-27 |
| `python -m pytest -p no:schemathesis tests/unit/test_contract_dependencies.py tests/unit/test_version.py tests/unit/test_sdk_backwards_compat.py -q` | ✅ PASS | 21 passed on 2026-04-27 |
| `python -m pytest -p no:schemathesis tests/unit/test_auth.py::test_hashed_key_authentication_caches_successful_plaintext -q` through the Windows-safe local wrapper | ✅ PASS | 1 passed in 1.19s on 2026-04-28 |
| `tests/unit/test_auth.py` through the Windows-safe local wrapper | ✅ PASS | 11 passed, 1 warning in 3.26s on 2026-04-28 |
| `tests/unit` through the Windows-safe local wrapper | ✅ PASS | 433 passed in 81.64s on 2026-04-28 |
| `tests/contract tests/e2e` through the Windows-safe local wrapper and temporary project-local `sitecustomize` shim | ✅ PASS | 35 passed in 150.54s on 2026-04-28 |
| `docker compose up -d redis` + project-local `TEMP`/`TMP` + full `pytest` through the Windows-safe local wrapper and temporary project-local `sitecustomize` shim | ✅ PASS | 724 passed, 4 skipped in 498.66s on 2026-04-28; shim removed after the run |
| GitHub Actions on `45165b3` plus manual `Contract Tests` dispatch on `8d7088d` | ✅ PASS | `CI`, `Security Scan`, `E2E Tests`, `Load Test`, and `Staging Deploy` succeeded on `45165b3`; manually dispatched `Contract Tests` succeeded on `8d7088d` |
| `cd sdk-ts`; `npm install --package-lock=false`; `npm run build`; `npm pack --dry-run` | ✅ PASS | TypeScript SDK tarball `agentflow-client-1.1.0.tgz`, 16 files, package size 8.2 kB, unpacked 32.9 kB |
| Clear `dist` and `sdk/dist`; `python -m build .`; `python -m build sdk\`; `python -m twine check dist\* sdk\dist\*` | ✅ PASS | runtime and SDK artifacts passed `twine check`; runtime artifacts still warn that long description metadata is missing |
| Clean temp venv editable install-order check for root, SDK, and integrations | ✅ PASS | both install orders resolved `agentflow-runtime` 1.1.0 from repo root and `agentflow-client` 1.1.0 from `sdk/`; imports and `agentflow --help` worked |
| PyPI Trusted Publisher setup | ✅ READY | PyPI account publishing page shows pending publishers for `agentflow-runtime` and `agentflow-client` with owner `brownjuly2003-code`, repo `agentflow`, workflow `publish-pypi.yml`, environment `pypi` |
| GitHub registry secret setup | ✅ READY | `gh secret list --repo brownjuly2003-code/agentflow` shows `NPM_TOKEN` updated on 2026-04-27; npm token was validated with registry `/whoami` before storing |
| Pending workflow environment change | ✅ COMMITTED | `.github/workflows/publish-pypi.yml` `environment: pypi` landed in `e8b1237` |
| Release pre-commit full-suite gate | ✅ PASS | `670 passed, 4 skipped` in 269s on audit-closure HEAD; the earlier chaos smoke hang did not reproduce, standalone re-run gives `3 passed in 44s` |
| Audit closure sprint (Codex p1–p9 + Opus) | ✅ CLOSED | 6 commits on local `main` ahead of `origin`: `e8b1237`, `fb6aa14`, `1c24e58`, `d295ecf`, `d61261b`, `3c887b1`. Full mapping in [`docs/audits/2026-04-27/README.md`](audits/2026-04-27/README.md) |
| Branch protection on `main` | ✅ APPLIED | 13 required status checks via `gh api`; `strict=true`, force-pushes / deletions disabled |
| TypeScript SDK lockfile + audit | ✅ CLEAN | `sdk-ts/package-lock.json` committed (1500 lines); `npm audit --audit-level=moderate` reports 0 vulnerabilities |

Full-suite note: local verification requires Redis to be running for cache-backed API tests. This Windows workstation also needs project-local `TEMP`/`TMP` and `--basetemp` paths because the default `%TEMP%\pytest-of-uedom` path is not readable by the test process. On 2026-04-28, direct pytest also hung before output when Windows WMI was reached through `platform.*`; the successful local run used a temporary project-local `sitecustomize` shim and a dummy `readline` module in the test runner. Do not commit that shim.

Local note: `tests/chaos` already manage their own Docker stack via fixture. Running `docker compose -f docker-compose.chaos.yml up -d` before `pytest` creates a duplicate toxiproxy bind on port `8474`; the stable local command is the direct `pytest` invocation.

## Evidence

- Audit reference: `docs/audit-history.md` (retrospective reconstruction)
- Phase 4 docs: `docs/competitive-analysis.md`, `docs/security-audit.md`, `docs/api-reference.md`
- Landing: `site/index.html`
- Demo deploy: `deploy/fly/`
- Baseline data: `docs/benchmark-baseline.json`
- Plan trail: `docs/plans/2026-04-17-v8-*.md` ... `docs/plans/2026-04-20-v19-doc-completion.md`
  - v16 research: `2026-04-20-v16-research.md`, `2026-04-20-v16-synthetic-interviews.md`
  - v17 publication: `2026-04-20-v17-publication.md`
  - v18 GitHub: `2026-04-20-v18-github-publish.md`
  - v19 doc completion: `2026-04-20-v19-doc-completion.md`
- Derived artifacts:
  - Public repo: https://github.com/brownjuly2003-code/agentflow
  - v1.0.0 release: https://github.com/brownjuly2003-code/agentflow/releases/tag/v1.0.0
  - v1.0.1 patch release: https://github.com/brownjuly2003-code/agentflow/releases/tag/v1.0.1
- Security triage: `.artifacts/security/bandit-triage-2026-04-17.md`

## New Session Handoff

Current HEAD is `b2c0bc0` on `main`, aligned with `origin/main` before the
auth-cache worktree is committed. Intended uncommitted files at this handoff:
`src/serving/api/auth/manager.py`, `tests/unit/test_auth.py`,
`docs/release-readiness.md`, and
`docs/codex-tasks/2026-04-28/T31-hashed-api-key-auth-cache.md`.
Recommended next session starting point:

1. Review the auth-cache diff and commit with an explicit pathspec. Do not use
   `git add -A`; there are ignored/inaccessible pytest temp directories in the
   worktree.
2. Push `main` only after the commit is made and `git status --short` shows only
   intended files before staging. Branch protection requires the status checks
   listed above to be green on the pushed commit.
3. Once CI is green on `origin/main`, move `v1.1.0` from the stale
   `1ee89a3` to the new release commit:

   ```bash
   git push origin :refs/tags/v1.1.0
   git tag -d v1.1.0
   git tag -a v1.1.0 -m "AgentFlow v1.1.0 (audit-closure)"
   git push origin v1.1.0
   ```

4. Monitor `Publish Python Packages` and `Publish TypeScript SDK`. PyPI
   Trusted Publishers already exist for `agentflow-runtime` and
   `agentflow-client`; `NPM_TOKEN` already lives in GitHub Actions
   secrets. The `environment: pypi` claim is now committed.
5. After both publish workflows are green, `WebFetch` the registry pages
   to verify the artifacts are live before announcing the release.

## Release Verdict

**v1.1.0 release line prepared; post-v1.1 CDC follow-up checked in.**

AgentFlow is publicly available and the current checked-in docs/code describe the intended release and CDC state. Do not treat registry publishing or production CDC source onboarding as complete until the unchecked gates above are closed. Remaining open items:
- Phase 1 PMF: customer discovery - needs founder outreach (script ready in `docs/customer-discovery-questions.md`)
- Manual GH Actions setup: environments currently list `production`, `pypi`, and `staging`; required reviewer policy still needs explicit confirmation if it is part of the deployment gate
- AWS OIDC role setup for real terraform apply
- Registry publish: PyPI pending publishers and GitHub `NPM_TOKEN` are configured, but npm `@agentflow/client` and PyPI `agentflow-runtime`/`agentflow-client` are still unpublished. The local full-suite gate is green again; publish still requires committing/pushing the current auth-cache worktree, green CI, an approved release tag, and green publish workflows.
- Production CDC source onboarding decision and secrets/network setup
- External pen-test attestation
- Public benchmark on production hardware (`c8g.4xlarge+`)
- First paying customers (sales track)

v1.1 direction informed by research sprint (`docs/v1-1-research.md`): read-first MCP surface, thin LangChain adapter, freshness primitives as differentiation. Confidence is medium - real interviews required before implementation.
