# AgentFlow Release Readiness

**Date**: 2026-04-20
**Last updated**: 2026-05-01
**Version**: v1.1.0 + post-v1.1 CDC follow-up + 2026-04-27 audit closure sprint + post-release benchmark workflow split
**Status**: v1.0.0 published; v1.0.1 patch released for clean-clone support; v1.1.0 release line published to PyPI and npm with SDK/runtime split; post-v1.1 CDC operationalization checked in; the 2026-04-27 audit closure sprint landed six commits closing all P0/P1/P2 findings (see [docs/audits/2026-04-27/](audits/2026-04-27/README.md)); registry credentials configured; main protected with required status checks; GitHub Actions environments `staging` and `production` configured with required reviewers; GitHub Release record created

## Executive Summary

AgentFlow закрыл технические блокеры из internal audit baseline от 2026-04-12, опубликовал v1.0.0 на GitHub 2026-04-20 и выпустил v1.0.1 patch release для clean-clone установки. Поверх v13.5 security refresh работы v15-v18 закрыли GTM/documentation хвост: narrative API reference, competitive analysis, security audit, landing page, README/glossary/LICENSE/CHANGELOG, public repo, and Fly.io demo config are now part of the release evidence. `bandit_diff.py` остаётся зелёным against the checked-in baseline, а clean-clone verification для patch release зафиксирован в `CHANGELOG.md` (`pytest tests/unit -q`: 340 passed). Retrospective reconstruction of the lost audit artifact is preserved in `docs/audit-history.md`.

The v1.1 line split runtime and SDK distribution identity: the runtime publishes as `agentflow-runtime`, while the Python SDK publishes as `agentflow-client` and keeps the `agentflow` import path. The current post-v1.1 follow-up operationalizes ADR 0005 with Debezium/Kafka Connect local compose, a Kubernetes-shaped Helm chart, raw CDC topic bootstrap, and canonical CDC normalization before downstream validation.

## Current Status (2026-05-01)

| Area | Clear status |
|------|--------------|
| Public repository | Published and release-ready from the checked-in evidence trail |
| Runtime package | `agentflow-runtime` is the root distribution name |
| Python SDK package | `agentflow-client` is the PyPI distribution; `from agentflow import ...` stays unchanged |
| Registry publishing | PyPI `agentflow-runtime` 1.1.0, PyPI `agentflow-client` 1.1.0, legacy npm `@uedomskikh/agentflow-client` 1.1.0, and new npm `@yuliaedomskikh/agentflow-client` 1.1.0 are live; PyPI uploads used Trusted Publishing attestations; the new npm package is owned by `yuliaedomskikh <yulia.edomskikh@gmail.com>`; npm Trusted Publishing was created for `brownjuly2003-code/agentflow`, workflow `publish-npm.yml`, no environment, verified in the npm package settings UI, and confirmed by CLI `npm trust list` readback on 2026-05-01; usable saved recovery-code reserve is 4 |
| GitHub deployment gates | Environments `staging` and `production` exist with required reviewer `brownjuly2003-code`; the workflow environment name is `production`, not `prod` |
| CDC local path | Checked in: compose source DBs, Kafka Connect image, connector registration, topic bootstrap, and integration tests |
| CDC Kubernetes path | Checked in: `helm/kafka-connect` chart, values schema, connector hooks, and topic bootstrap hook |
| CDC production onboarding | Not done: real hostnames, table scope, network path, and secret owner still need an explicit decision; the required decision record and no-go gates are documented in [Production CDC Source Onboarding](operations/cdc-production-onboarding.md) |
| Recorded full-suite evidence | 2026-05-01 Docker-backed local full-suite pass after Docker Desktop recovery: 741 passed, 4 skipped in 393.84s with project-local temp/cache paths. Earlier 2026-04-30 full-suite, Docker README-copy, documentation-refresh, npm-prep, and CDC-runbook evidence remain recorded below. |
| Current post-release main | Local `main` contains the post-release npm Trusted Publishing handoff plus refreshed external-gate evidence. Push remains separate; do not assume origin has these local commits until `git push` is explicitly run. |

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
- Real Terraform `apply` has not been executed from GitHub Actions yet; current state is local `terraform init -backend=false` and `terraform validate` through the Terraform container plus workflow wiring.
- GitHub Actions environments `staging` and `production` are configured with required reviewer `brownjuly2003-code`; `prevent_self_review=false` because the repo currently has one admin collaborator.
- AWS OIDC role setup for GitHub Actions is still a manual setup step. As of 2026-05-01, repo variable `AWS_REGION` exists, `AWS_TERRAFORM_ROLE_ARN` is not configured, `.github/workflows/terraform-apply.yml` remains disabled with `if: false`, real `infrastructure/terraform/environments/*.tfvars` files are not committed, and no AWS credentials are configured on the verification workstation.
- SDK registry publish evidence is complete for v1.1.0. The legacy npm package `@uedomskikh/agentflow-client` remains live but is not the future publish target. Future TypeScript SDK publishing now targets `@yuliaedomskikh/agentflow-client`, which is public, owned by `yuliaedomskikh`, and has npm Trusted Publishing configured for GitHub Actions OIDC (`brownjuly2003-code/agentflow`, workflow `publish-npm.yml`, no environment). CLI readback confirmed the same Trusted Publisher on 2026-05-01. The current npm `NPM_TOKEN` is a time-limited write token created on 2026-04-30 with a 90-day expiry selected in the npm UI; treat it as expiring by 2026-07-29 until revoked. Revoke it after the first successful trusted-publish workflow run on the new package. A new account still cannot control the old `@uedomskikh/agentflow-client` package unless old owner auth adds it as a maintainer or npm support intervenes; scoped packages cannot be transferred to a different user scope.
- Public benchmark on production hardware is still pending; current evidence is the checked-in single-node baseline.
- Chaos full suite runs on schedule; PR path covers smoke scope only.
- Production CDC source onboarding is not yet enabled. The checked-in CDC path covers local/demo and Kubernetes-shaped staging primitives; real production Postgres/MySQL attachment still needs hostnames, table scope, network access, and secret ownership. The approval checklist is documented in [Production CDC Source Onboarding](operations/cdc-production-onboarding.md).
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
- [x] GitHub environments `staging` and `production` configured with required reviewer `brownjuly2003-code` (verified via `gh api` on 2026-04-30; `prevent_self_review=false` because the repo currently has one admin collaborator)
- [ ] AWS OIDC role configured for GitHub Actions (`AWS_REGION` exists; `AWS_TERRAFORM_ROLE_ARN`, enabled terraform workflow, and real environment tfvars are still missing)
- [x] First approved registry release tag produces green `Publish TypeScript SDK` and `Publish Python Packages` runs (`v1.1.0` tag target `2c72387`)
- [ ] Production CDC source onboarding approved and configured
- [x] Full-suite release-line verification — `741 passed, 4 skipped` in 393.84s on 2026-05-01 after Docker Desktop recovery; prior `743 passed, 4 skipped` in 845.60s on 2026-04-30 remains in the evidence table
- [x] Standalone chaos smoke green on 2026-05-01 (`3 passed in 16.71s` through the CI compose path); audit-closure HEAD also clean
- [x] npm Trusted Publishing CLI readback verified on 2026-05-01 for `@yuliaedomskikh/agentflow-client`
- [x] Hashed API-key auth cache regression fixed locally and covered by `tests/unit/test_auth.py::test_hashed_key_authentication_caches_successful_plaintext`
- [x] SDK/runtime publish preflight completed locally without pushing a tag
- [x] 2026-04-27 audit closure sprint — all P0/P1/P2 findings from Claude Opus + Codex p1–p9 closed in 6 commits ([docs/audits/2026-04-27/README.md](audits/2026-04-27/README.md))
- [x] `main` protected with 12 required status checks (`lint`, `test-unit`, `test-integration`, `perf-check`, `helm-schema-live`, `schema-check`, `terraform-validate`, `bandit`, `safety`, `npm-audit`, `trivy`, `contract`) — `record-deployment` removed because the bot push it required is incompatible with the protection gate; DORA metrics fall back to the GitHub Actions API source already used by `scripts/dora_metrics.py`
- [x] `publish-pypi.yml` `environment: pypi` committed (`e8b1237`)
- [x] `sdk-ts/package-lock.json` committed; `npm audit` clean (0 vulns)
- [x] Vulnerable runtime/integrations deps bumped (`dagster>=1.13.1`, `langchain-core>=1.2.22`, `langchain-text-splitters>=1.1.2`, `langsmith>=0.7.31`)
- [ ] Phase 1 PMF work completed (`docs/customer-discovery-tracker.md` now defines the 15-candidate sourcing worklist, outreach queue, qualification rules, outreach templates, 5-interview operating tracker, and batch synthesis workflow; `docs/pricing-validation-plan.md` defines the pricing/WTP evidence gates and pilot-offer signals to capture during interviews; real interviews are still pending)

## SDK Publish Proof Path

- Publish workflows accept standalone SDK tags (`sdk-vX.Y.Z`), release-candidate tags (`vX.Y.Z-rcN`), and production release tags (`vX.Y.Z`). `scripts/release.py` still creates `sdk-vX.Y.Z` tags for standalone SDK releases.
- Existing repo releases/tags (`v1.0.0`, `v1.0.1`, `v1.1.0`) are not registry-proof by themselves; proof requires green npm/PyPI publish workflow runs for the approved tag. The current `v1.1.0` tag points at `2c72387`; the GitHub Release is published and registry proof is green.
- Safe preflight for the first live SDK publish is documented in `docs/publication-checklist.md` and was completed locally on 2026-04-27 at `8d7088d`: build the TypeScript SDK, run `npm pack --dry-run`, build SDK wheels/sdists, and verify both editable install orders in a clean venv. The local run also built runtime wheels/sdists and passed `python -m twine check dist\* sdk\dist\*`.
- The first green proof for both publish workflows is the `v1.1.0` tag retry on `2c72387`: PyPI publish succeeded, TypeScript SDK publish succeeded after replacing `NPM_TOKEN`, and registry lookups confirmed PyPI `agentflow-runtime` 1.1.0, PyPI `agentflow-client` 1.1.0, and npm `@uedomskikh/agentflow-client` 1.1.0.

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
| `python -m pytest -p no:schemathesis -q --basetemp=.tmp\codex-readme-copy-basetemp -o cache_dir=.tmp\codex-readme-copy-cache` | ✅ PASS | 734 passed, 4 skipped, 104 warnings in 431.00s on 2026-04-30 after the Docker README-copy sync |
| `python -m pytest -p no:schemathesis -q --basetemp=.tmp\codex-doc-refresh-basetemp -o cache_dir=.tmp\codex-doc-refresh-cache` | ✅ PASS | 741 passed, 4 skipped, 104 warnings in 839.03s on 2026-04-30 after the post-release documentation refresh |
| `python -m pytest -p no:schemathesis -q --basetemp=.tmp\codex-npm-trusted-basetemp -o cache_dir=.tmp\codex-npm-trusted-cache` | ✅ PASS | 742 passed, 4 skipped, 104 warnings in 823.06s on 2026-04-30 after npm Trusted Publishing workflow prep |
| `python -m pytest -p no:schemathesis -q --basetemp=.tmp\codex-cdc-onboarding-basetemp -o cache_dir=.tmp\codex-cdc-onboarding-cache` | ✅ PASS | 742 passed, 4 skipped, 104 warnings in 819.42s on 2026-04-30 after the CDC onboarding runbook |
| `python -m pytest -p no:schemathesis -q --basetemp=.tmp\codex-npm-final-basetemp -o cache_dir=.tmp\codex-npm-final-cache` | ✅ PASS | 743 passed, 4 skipped, 104 warnings in 845.60s on 2026-04-30 after documenting the npm Trusted Publishing account handoff |
| `python -m pytest -p no:schemathesis -q tests/unit`; `tests/property`; `.venv\Scripts\python.exe -m pytest ... tests/integration -m "not requires_docker"`; `.venv\Scripts\python.exe -m pytest ... tests/e2e` | ✅ PASS | 2026-05-01 local no-Docker slice: 448 unit passed, 15 property passed, 200 integration passed / 3 skipped / 5 deselected, and 18 e2e passed. This was superseded by the Docker-backed full-suite rerun below after Docker Desktop recovery. |
| Docker Desktop recovery + `docker compose up -d redis` | ✅ PASS | Docker Desktop recovered on 2026-05-01 by stopping Desktop, terminating the `docker-desktop` WSL distribution, and restarting Desktop. `docker desktop status` returned `running`; Redis is healthy. |
| `.venv\Scripts\python.exe -m pytest -p no:schemathesis -q --basetemp .tmp\pytest-basetemp-t32-full` with project-local `TMP`/`TEMP` | ✅ PASS | 741 passed, 4 skipped in 393.84s on 2026-05-01 after Docker Desktop recovery |
| `docker compose -p agentflow-chaos -f docker-compose.chaos.yml up -d --wait --wait-timeout 120`; `tests/chaos/test_chaos_smoke.py`; `scripts/chaos_report.py` | ✅ PASS | 3 passed in 16.71s on 2026-05-01 through the CI compose path; stack was torn down with `down -v` |
| `docker compose -f docker-compose.prod.yml build agentflow-api`; Trivy `aquasec/trivy:0.68.1 image --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 agentflow-api:security-scan` | ✅ PASS | Production API image built successfully and the Trivy image scan reported 0 HIGH/CRITICAL findings |
| `docker compose -f docker-compose.yml -f docker-compose.cdc.yml ...`; `tests/integration/test_cdc_capture.py::test_cdc_compose_stack_captures_postgres_and_mysql_rows` with `AGENTFLOW_RUN_CDC_DOCKER=1` | ✅ PASS | CDC connectors reached `RUNNING`, and the gated Postgres/MySQL CDC capture test passed in 103.60s on 2026-05-01 |
| Terraform container `init -backend=false` + `validate`; Helm production CDC secret-mode render | ✅ PASS | `hashicorp/terraform:1.13.5` validated `infrastructure/terraform`; Helm rendered production CDC secret mode with only `secretName: agentflow-prod-cdc-secret` and no credential values |
| `.venv\Scripts\python.exe scripts\export_openapi.py --check`; `python scripts\generate_contracts.py --check`; `python scripts\check_schema_evolution.py` | ✅ PASS | OpenAPI drift check passes in the project `.venv`; the global Python install still reproduces the known FastAPI-version `ValidationError.input/ctx` drift documented in `docs/perf/test_openapi_compliance-divergence-2026-04-25.md`. |
| Docker API image README-copy regression on `67c2ae5` | ✅ PASS | `Dockerfile.api`, inline `docker-compose.prod.yml` build, and `scripts/k8s_staging_up.sh` copy `README.md` before editable installs; GitHub checks for `67c2ae5` are green: `lint`, `test-unit`, `test-integration`, `perf-check`, `helm-schema-live`, `schema-check`, `terraform-validate`, `bandit`, `safety`, `npm-audit`, `trivy`, `e2e`, `load-test`, and `staging` |
| `cd sdk-ts`; `npm ci`; `npm run typecheck`; `npm run test:unit`; `npm run build`; `npm pack --dry-run` | ✅ PASS | `@yuliaedomskikh/agentflow-client@1.1.0`, 42 unit tests passed, tarball `yuliaedomskikh-agentflow-client-1.1.0.tgz`, 16 files, package size 8.3 kB |
| `python -m build . --outdir .tmp\codex-continue-build2-root`; `python -m build sdk --outdir .tmp\codex-continue-build2-sdk`; `python -m twine check ...`; `python scripts\check_release_artifacts.py ...` | ✅ PASS | Runtime and SDK wheels/sdists build cleanly, pass `twine check`, and pass artifact policy. SDK starter `.env.example.tmpl` placeholders are explicitly allowed; real `.env`, API-key configs, webhook configs, and secret paths remain forbidden. |
| `v1.1.0` publish attempt on `2f96f08` | ⚠️ PARTIAL | PyPI `agentflow-runtime` 1.1.0 and `agentflow-client` 1.1.0 are visible; `Publish Python Packages` failed on an already-existing runtime sdist during a retry-shaped upload, and `Publish TypeScript SDK` failed because npm upload ran without `NPM_TOKEN`. The first follow-up used the configured npm token; the current workflow is now prepared for OIDC Trusted Publishing before the next npm release. |
| `v1.1.0` final registry publish on `2c72387` | ✅ PASS | `Publish Python Packages`, `Publish TypeScript SDK`, and tag `Contract Tests` succeeded. `npm view @uedomskikh/agentflow-client@1.1.0 version --registry https://registry.npmjs.org/ --prefer-online --json` returned `"1.1.0"` after registry propagation. |
| New npm package first publish and Trusted Publisher setup | ✅ PASS | `@yuliaedomskikh/agentflow-client@1.1.0` was published from a `yuliaedomskikh` CLI session, registry view returns owner `yuliaedomskikh <yulia.edomskikh@gmail.com>`, and `npm trust github` created trust id `693e8f2f-c592-4fd0-8942-232356bb5e9a` for `brownjuly2003-code/agentflow`, workflow `publish-npm.yml`, no environment |
| GitHub Actions on `45165b3` plus manual `Contract Tests` dispatch on `8d7088d` | ✅ PASS | `CI`, `Security Scan`, `E2E Tests`, `Load Test`, and `Staging Deploy` succeeded on `45165b3`; manually dispatched `Contract Tests` succeeded on `8d7088d` |
| `cd sdk-ts`; `npm install --package-lock=false`; `npm run build`; `npm pack --dry-run` | ✅ PASS | TypeScript SDK tarball `agentflow-client-1.1.0.tgz`, 16 files, package size 8.2 kB, unpacked 32.9 kB |
| Clear `dist` and `sdk/dist`; `python -m build .`; `python -m build sdk\`; `python -m twine check dist\* sdk\dist\*` | ✅ PASS | runtime and SDK artifacts passed `twine check`; runtime artifacts still warn that long description metadata is missing |
| `python -m build . --outdir .tmp\build-root-readme`; `python -m twine check .tmp\build-root-readme\*` | ✅ PASS | root runtime artifacts pass `twine check` without long-description warnings after adding `readme = "README.md"` |
| `python scripts\check_release_artifacts.py .tmp\build-root-readme\*` | ✅ PASS | root runtime wheel and sdist contain no forbidden release members such as `.env`, API key configs, webhook configs, or `docker/**/secrets/**` |
| Clean temp venv editable install-order check for root, SDK, and integrations | ✅ PASS | both install orders resolved `agentflow-runtime` 1.1.0 from repo root and `agentflow-client` 1.1.0 from `sdk/`; imports and `agentflow --help` worked |
| PyPI Trusted Publishing | ✅ ACTIVE | PyPI file metadata for both `agentflow-runtime` 1.1.0 and `agentflow-client` 1.1.0 shows `Uploaded using Trusted Publishing? Yes` with provenance tied to `publish-pypi.yml` on tag `v1.1.0` |
| npm Trusted Publishing | ✅ ACTIVE / CLI VERIFIED | `publish-npm.yml` uses GitHub Actions OIDC (`id-token: write`), Node 24, npm `^11.5.1`, and no `NODE_AUTH_TOKEN` on the production publish step. New npm account `yuliaedomskikh` is email-verified, has 2FA mode `auth-and-writes`, owns public package `@yuliaedomskikh/agentflow-client@1.1.0`, and has Trusted Publisher `brownjuly2003-code/agentflow` with workflow `publish-npm.yml` and no environment. `npm trust github` created trust id `693e8f2f-c592-4fd0-8942-232356bb5e9a`; the npm package settings UI shows the same repository/workflow. CLI `npm trust list` readback on 2026-05-01 returned provider `github`, repository `brownjuly2003-code/agentflow`, workflow `publish-npm.yml`, and no environment. Usable saved recovery-code reserve is 4. |
| Pending workflow environment change | ✅ COMMITTED | `.github/workflows/publish-pypi.yml` `environment: pypi` landed in `e8b1237` |
| Release pre-commit full-suite gate | ✅ PASS | `670 passed, 4 skipped` in 269s on audit-closure HEAD; the earlier chaos smoke hang did not reproduce, standalone re-run gives `3 passed in 44s` |
| Audit closure sprint (Codex p1–p9 + Opus) | ✅ CLOSED | 6 commits landed on `main`: `e8b1237`, `fb6aa14`, `1c24e58`, `d295ecf`, `d61261b`, `3c887b1`. Full mapping in [`docs/audits/2026-04-27/README.md`](audits/2026-04-27/README.md) |
| Branch protection on `main` | ✅ APPLIED | 12 required status checks via `gh api`; `strict=true`, force-pushes / deletions disabled |
| GitHub Actions environments `staging` and `production` | ✅ APPLIED | `gh api repos/brownjuly2003-code/agentflow/environments` shows a `required_reviewers` protection rule on both environments with reviewer `brownjuly2003-code`; `prevent_self_review=false` |
| AWS OIDC Terraform apply readiness | ⚠️ BLOCKED | `gh variable list` shows `AWS_REGION=us-east-1` only; `AWS_TERRAFORM_ROLE_ARN` is missing, terraform apply jobs are still `if: false`, real `environments/*.tfvars` are absent, and this workstation has no AWS credentials. Terraform CLI is not installed locally, but `hashicorp/terraform:1.13.5` `init -backend=false` and `validate` pass for the checked-in config. |
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
  - v1.1.0 release: https://github.com/brownjuly2003-code/agentflow/releases/tag/v1.1.0
- Security triage: `.artifacts/security/bandit-triage-2026-04-17.md`

## New Session Handoff

Local `main` contains the post-release npm Trusted Publishing handoff and refreshed
external-gate evidence. Push remains separate; do not assume origin has these
local commits until `git push` is explicitly run. The approved `v1.1.0` tag
points at `2c72387`. Registry artifacts are live on PyPI and npm. Future
TypeScript SDK publishing now uses the new npm account and package
`@yuliaedomskikh/agentflow-client`.

Current npm handoff state:

1. New npm user `yuliaedomskikh` / `yulia.edomskikh@gmail.com` is email-verified
   and has 2FA mode `auth-and-writes`.
2. `@yuliaedomskikh/agentflow-client@1.1.0` is public and owned by
   `yuliaedomskikh <yulia.edomskikh@gmail.com>`.
3. `npm trust github @yuliaedomskikh/agentflow-client --repo
   brownjuly2003-code/agentflow --file publish-npm.yml --yes` succeeded and
   created trust id `693e8f2f-c592-4fd0-8942-232356bb5e9a`.
4. The npm package settings UI shows Trusted Publisher
   `brownjuly2003-code/agentflow`, workflow `publish-npm.yml`, no environment.
5. `npm trust list @yuliaedomskikh/agentflow-client --json --registry
   https://registry.npmjs.org/` now confirms provider `github`, repository
   `brownjuly2003-code/agentflow`, workflow `publish-npm.yml`, and no
   environment.
6. Obsolete standalone 16-character recovery-code candidates were removed from
   the local untracked secret notes; the active note now has zero legacy
   candidates and four usable 64-character npm recovery codes.
7. A new account cannot control legacy `@uedomskikh/agentflow-client` unless old
   owner auth adds it as a maintainer or npm support intervenes. Treat the old
   package as legacy and publish future SDK releases under the new scope.
8. Continue production CDC source onboarding only after hostnames, table scope,
   network path, and secret ownership are approved.

npm follow-up note:

- No npm Trusted Publishing setup/readback work remains for
  `@yuliaedomskikh/agentflow-client`; the CLI readback is complete.
- Use the `npm-recovery-codes` skill before any future OTP-gated npm operation.
  The current usable saved recovery-code reserve is 4, and at least 2 must
  remain unused after any planned operation.
- After one successful trusted-publish workflow run, revoke the old `NPM_TOKEN`.

## Release Verdict

**v1.1.0 release line prepared; post-release local gates recorded.**

AgentFlow is publicly available and the current checked-in docs/code describe the intended release, npm Trusted Publishing, Docker-backed verification, and CDC state. Do not treat AWS Terraform apply or production CDC source onboarding as complete until the unchecked gates above are closed. Remaining open items:
- Phase 1 PMF: customer discovery and pricing validation - needs founder outreach (script ready in `docs/customer-discovery-questions.md`; first-batch sourcing worklist, outreach queue, candidate qualification, templates, operating tracker, and synthesis workflow ready in `docs/customer-discovery-tracker.md`; pricing/WTP evidence gates and pilot-offer signal capture ready in `docs/pricing-validation-plan.md`)
- AWS OIDC role setup for real terraform apply: create/apply the IAM role, add `AWS_TERRAFORM_ROLE_ARN`, provide real environment tfvars, and re-enable `.github/workflows/terraform-apply.yml`
- Revoke the legacy npm `NPM_TOKEN` after the first successful trusted-publish run for `@yuliaedomskikh/agentflow-client`
- Production CDC source onboarding decision and secrets/network setup; use [Production CDC Source Onboarding](operations/cdc-production-onboarding.md) as the approval checklist
- External pen-test attestation
- Public benchmark on production hardware (`c8g.4xlarge+`)
- First paying customers (sales track)

v1.1 direction informed by research sprint (`docs/v1-1-research.md`): read-first MCP surface, thin LangChain adapter, freshness primitives as differentiation. Confidence is medium - real interviews required before implementation.
