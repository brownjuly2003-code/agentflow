# GitHub Publication and Release Checklist

Before publishing AgentFlow changes or pushing a release tag:

Status snapshot (2026-04-29, local `main` includes `f1b398c`): content, security,
link, and local SDK publish preflight checks are complete. Live `v1.1.0`
publish still depends on pushing the commit, getting green CI, and re-tagging.

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

- [ ] `docs/screenshots/admin-ui.png`
- [ ] `docs/screenshots/swagger-docs.png`
- [ ] `docs/screenshots/landing-page.png`
- [ ] `docs/screenshots/benchmark-terminal.png`

Capture notes:

- Run `make demo`
- Open Swagger at `http://localhost:8000/docs`
- Open the landing page from `site/index.html`
- Capture the benchmark terminal after running `python scripts/run_benchmark.py`

## Repo settings after push

- [x] Fill the repository description in the GitHub About section
- [x] Add topics: `data-engineering`, `real-time`, `ai-agents`, `fastapi`, `duckdb`, `kafka`, `flink`
- [ ] Create or update the approved `vX.Y.Z` release using notes from `CHANGELOG.md`

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
npm install --package-lock=false
npm run build
npm pack --dry-run
cd ..
python -m build sdk/
python -m twine check sdk/dist/*
```

- [x] If `sdk/dist/` already contains older artifacts, clear it before `python -m build sdk/` so `twine check` only validates the current release
- [x] Stop after the rehearsal when you only need proof; the real publish event is pushing the approved release tag
- [ ] On the approved release commit, push the commit and release tag, then confirm green runs for `Publish TypeScript SDK` and `Publish Python Packages`

## Verification after publish

- [ ] Clone a fresh copy and run `make demo`
- [ ] Run `python -m pytest tests/unit tests/integration tests/sdk -q`
- [ ] Re-check README links from the fresh clone
