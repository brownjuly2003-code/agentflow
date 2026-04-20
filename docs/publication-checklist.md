# GitHub Publication Checklist

Before pushing AgentFlow to a public repository:

## Content

- [ ] `README.md` is publication-ready
- [ ] `LICENSE` is present and set to MIT
- [ ] `CHANGELOG.md` includes the `v1.0.0` entry
- [ ] `CONTRIBUTING.md` is present
- [ ] `.env.example` contains placeholders only
- [ ] `docs/glossary.md` is ready for interview prep

## Security

- [ ] Secret scan is clean for checked-in files
- [ ] `.env` is ignored in `.gitignore`
- [ ] `.bandit-baseline.json` is present and unchanged
- [ ] `*.duckdb` files remain ignored in `.gitignore`
- [ ] `admin-secret` appears only in tests or docs examples, not in production config

## Links

- [ ] Relative links in `README.md` resolve
- [ ] No markdown links point to `localhost`
- [ ] No absolute `D:\...` paths appear in publishable docs
- [ ] `docs/` links point only to files that exist in the repo

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

- [ ] Fill the repository description in the GitHub About section
- [ ] Add topics: `data-engineering`, `real-time`, `ai-agents`, `fastapi`, `duckdb`, `kafka`, `flink`
- [ ] Create a `v1.0.0` release using notes from `CHANGELOG.md`

## Verification after publish

- [ ] Clone a fresh copy and run `make demo`
- [ ] Run `python -m pytest tests/unit tests/integration tests/sdk -q`
- [ ] Re-check README links from the fresh clone
