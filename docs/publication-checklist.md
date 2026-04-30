# GitHub Publication and Release Checklist

Before publishing AgentFlow changes or pushing a release tag:

Status snapshot (2026-04-30): content, security, link, SDK publish preflight,
live `v1.1.0` PyPI/npm registry publishing, and the GitHub Release record are
complete.

## Content

- [x] `README.md` is publication-ready
- [x] `LICENSE` is present and set to MIT
- [x] `CHANGELOG.md` includes the current release or `[Unreleased]` entry
- [x] `CONTRIBUTING.md` is present
- [x] `.env.example` contains placeholders only
- [x] `docs/glossary.md` is ready for interview prep

## Security

- [x] Secret scan is clean for checked-in files
- [x] `.env` is ignored in `.gitignore`
- [x] `.bandit-baseline.json` is present and unchanged
- [x] `*.duckdb` files remain ignored in `.gitignore`
- [x] `admin-secret` appears only in tests or docs examples, not in production config

## Links

- [x] Relative links in `README.md` resolve
- [x] No markdown links point to `localhost`
- [x] No absolute `D:\...` paths appear in publishable docs
- [x] `docs/` links point only to files that exist in the repo

## Optional screenshots

- [x] `docs/screenshots/admin-ui.png`
- [x] `docs/screenshots/swagger-docs.png`
- [x] `docs/screenshots/landing-page.png`
- [x] `docs/screenshots/benchmark-terminal.png`

Capture notes:

- Captured on 2026-04-30 from the local demo API on `http://127.0.0.1:8000` and static landing server on `http://127.0.0.1:8002`.
- Swagger UI loaded from `/docs`; Playwright used `bypassCSP` so the FastAPI CDN assets render in the screenshot.
- Benchmark terminal screenshot uses a short local screenshot run: `python scripts/run_benchmark.py --host http://localhost:8000 --users 5 --spawn-rate 2 --run-time 10s --report-path .tmp\benchmark-screenshot.md --results-json .tmp\benchmark-screenshot.json`.

## Repo settings after push

- [x] Fill the repository description in the GitHub About section
- [x] Add topics: `data-engineering`, `real-time`, `ai-agents`, `fastapi`, `duckdb`, `kafka`, `flink`
- [x] Create or update the approved `vX.Y.Z` GitHub Release using notes from `CHANGELOG.md`

## SDK registry release

Clear state: GitHub source releases and registry publishes are separate. A `vX.Y.Z` tag can publish runtime + SDK packages, while `sdk-vX.Y.Z` remains the standalone SDK release path created by `scripts/release.py`.

- [x] On a clean venv, verify both install orders resolve the same package identities:

```bash
python -m pip install -e . -e ./sdk -e ./integrations
pip show agentflow-client
pip show agentflow-runtime
python -c "from agentflow import AgentFlowClient"
agentflow --help
python -m pip uninstall -y agentflow-client agentflow-runtime agentflow-integrations
python -m pip install -e ./sdk -e . -e ./integrations
pip show agentflow-client
pip show agentflow-runtime
python -c "from agentflow import AgentFlowClient"
agentflow --help
```

- [x] Confirm `pip show agentflow-client` points at `sdk/`, `pip show agentflow-runtime` points at the root repo, and integrations import cleanly without `sys.path` shims
- [x] Use `sdk-vX.Y.Z` for standalone SDK releases, `vX.Y.Z-rcN` for release-candidate smoke, and `vX.Y.Z` for production runtime+SDK release tags
- [x] Treat `.github/workflows/publish-npm.yml` and `.github/workflows/publish-pypi.yml` as production-capable workflows: approved `sdk-v*` and production `vX.Y.Z` tags publish real artifacts
- [ ] On a clean tree, run `python scripts/release.py patch|minor|major` to bump `sdk/` and `sdk-ts/` together and create the local `sdk-vX.Y.Z` tag
- [x] Before pushing the tag, rehearse the publish steps locally without uploading anything:

```bash
cd sdk-ts
npm ci
npm audit --audit-level=moderate
npm run build
npm pack --dry-run
cd ..
python -m build .
python -m build sdk/
python -m twine check dist/* sdk/dist/*
python scripts/check_release_artifacts.py dist/* sdk/dist/*
```

- [x] If `sdk/dist/` already contains older artifacts, clear it before `python -m build sdk/` so `twine check` only validates the current release
- [x] Stop after the rehearsal when you only need proof; the real publish event is pushing the approved release tag
- [x] On the approved release commit, push the commit and release tag, then confirm green runs for `Publish TypeScript SDK` and `Publish Python Packages`
- [x] Confirm registry visibility for `agentflow-runtime`, `agentflow-client`, and `@uedomskikh/agentflow-client` 1.1.0
- [ ] Before the next npm publish, migrate `@uedomskikh/agentflow-client` to npm Trusted Publishing or rotate GitHub `NPM_TOKEN`; the current npm write token was created on 2026-04-30 with a 90-day expiry selected, so assume expiry by 2026-07-29

## Verification after publish

- [x] Clone a fresh copy and run `make demo` or the same `Makefile` recipe where `make` is unavailable. Verified from fresh origin clone `0bf1181` on 2026-04-30: seed pipeline, seed benchmark fixtures, start API with `AGENTFLOW_AUTH_DISABLED=true`, then `/docs`, `/v1/entity/order/ORD-20260404-1001`, and `/v1/query` all returned `200`. This Windows host lacks `make` and reused the already-running Redis on `localhost:6379` because the port was occupied.
- [x] Run `python -m pytest tests/unit tests/integration tests/sdk -q` from the fresh clone. Windows-safe local command with `-p no:schemathesis -p no:metadata -p no:cacheprovider` and project-local temp paths passed with `657 passed, 4 skipped in 225.71s`.
- [x] Re-check README links from the fresh clone (`README links OK`).
