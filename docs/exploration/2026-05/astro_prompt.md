# CX task — Astro Starlight docs-site for DE_project (AgentFlow)

## Goal

Stand up an interactive static-docs site for this codebase, mirroring the
setup that already lives in the sibling `D:\RAG_Support_Assistant\docs-site\`
repository (Astro Starlight + auto-generators reading the live source tree).
Final state: `npm run dev` serves the site on `http://127.0.0.1:8010/` and
`npm run build` produces a self-contained `dist/` that GitHub Actions deploys
to GitHub Pages on every push to `master`. The site replaces / complements
whatever currently lives at `127.0.0.1:8010/architecture/`.

## Context

- Repo root: `D:\DE_project\`. Branch: `master`. The repo is the AgentFlow
  monorepo: a Python runtime (`agentflow-runtime`), a Python client SDK
  (`agentflow-client`), integrations, infra/Helm/Docker, alembic migrations,
  CI on GitHub Actions, mkdocs/Sphinx-style site already running on port
  8010. Owner on GitHub: `brownjuly2003-code`. Repo name: confirm with
  `git config --get remote.origin.url`.
- A working reference implementation already exists in
  `D:\RAG_Support_Assistant\docs-site\`. Use it as the template:
    - `package.json` — scripts (`predev`, `dev`, `prebuild`, `build`),
      `astro dev --port 8010`, dependencies (`astro@^6`, `@astrojs/starlight@^0.39`,
      `sharp`, `yaml`).
    - `astro.config.mjs` — Starlight integration with `site` + `base` set to
      the GitHub Pages URL of this repo, sidebar groups for
      Architecture / Operations / Plans & history / Research / Reference,
      `customCss: ['./src/assets/custom.css']`.
    - `tsconfig.json` (`extends: astro/tsconfigs/strict`).
    - `src/content.config.ts` (Starlight `docsLoader` + `docsSchema`).
    - `src/assets/custom.css` (Inter font, accent palette, route-method
      pill styles).
    - `src/content/docs/index.mdx` — landing splash with hero + at-a-glance
      cards.
    - `src/content/docs/architecture/index.mdx` — module map + Mermaid
      request-lifecycle diagram + data-store reference.
    - `src/content/docs/404.md` — splash 404.
    - `scripts/sync-docs.mjs` — copies markdown from `../docs/**/*.md` plus
      a few root files (README, AGENT_STATE, BACKLOG, AUTOPILOT,
      DEPRECATIONS) into `src/content/docs/guides/`, patches in
      front-matter when missing, lowercases slugs.
    - `scripts/gen-graph.mjs` — regex-parses a Python source file and
      emits a Mermaid state-machine diagram. (For DE_project, repurpose
      this to a `gen-pipelines.mjs` that visualizes whatever orchestrator
      DAG / state machine the runtime exposes.)
    - `scripts/gen-routes.mjs` — regex-walks FastAPI route decorators
      across `api/app.py` + `api/routers/*.py` and renders a method/path/
      file table. Adapt to the DE_project HTTP surface (search for
      `@router.<method>(` and `@app.<method>(` in the runtime).
    - `scripts/gen-providers.mjs` — reads `config/providers.yml` via the
      `yaml` package and renders a routing matrix. For DE_project, swap
      this to a generator that reads the equivalent declarative config in
      this repo (e.g. tenant config, integrations registry, agent
      manifests — confirm which file is the canonical source).
    - `.gitignore` — keeps `node_modules/`, `dist/`, `.astro/`,
      `src/content/docs/guides/`, and the auto-generated MDX files out
      of git so the source of truth stays the live code/markdown.
    - `.github/workflows/docs-site.yml` (one directory up at the project's
      `.github/workflows/`) — paths-filtered trigger, Node 22,
      `actions/setup-node@v4` with `cache: npm` and
      `cache-dependency-path: docs-site/package-lock.json`,
      `actions/upload-pages-artifact@v3`, `actions/deploy-pages@v4`,
      `permissions: { contents: read, pages: write, id-token: write }`,
      `concurrency: { group: pages, cancel-in-progress: false }`.
- The reference repo's deployed URL is
  `https://brownjuly2003-code.github.io/RAG_Support_Assistant/` — open it
  to see what the finished result looks like.

## Deliverables

1. New directory `docs-site/` at the repo root containing the same shape
   as the reference: `package.json`, `astro.config.mjs`, `tsconfig.json`,
   `.gitignore`, `src/content.config.ts`, `src/assets/custom.css`,
   `src/content/docs/{index,404}.{mdx,md}`,
   `src/content/docs/architecture/index.mdx`, `scripts/{sync-docs,
   gen-routes,gen-pipelines,gen-providers}.mjs` (rename / reshape the
   generators for DE_project's actual code structure — see Notes).
2. `astro.config.mjs.site` and `.base` pointing at the resolved
   `https://brownjuly2003-code.github.io/<repo-name>/` for the actual
   `<repo-name>` of this repo.
3. Hand-authored landing (`src/content/docs/index.mdx`) tailored to
   AgentFlow: tagline mentions runtime + client SDK + integrations,
   At-a-glance cards summarise the actual modules, Auto-generated section
   links to the three auto-pages, Status snapshot links to the live
   `AGENT_STATE.md` / backlog. No copy-paste of the RAG copy.
4. Hand-authored `src/content/docs/architecture/index.mdx` describing the
   real top-level modules of this repo (AgentFlow runtime / SDK /
   integrations / migrations / observability), with a Mermaid request /
   pipeline lifecycle diagram and a data-stores table.
5. `.github/workflows/docs-site.yml` triggering on pushes to `master`
   that touch `docs/**`, `docs-site/**`, the actual source files the
   generators read (e.g. `agentflow_runtime/**/graph.py`,
   `agentflow_runtime/api/**`, `config/**`), `README.md`, top-level
   `*.md` snapshots, and the workflow file itself. Node 22, npm cache,
   Pages permissions, concurrency `pages`.
6. Rebuilt sidebar in `astro.config.mjs` that references real DE_project
   markdown after `sync-docs.mjs` runs (no broken slugs).

## Acceptance criteria

- `cd docs-site && npm install` resolves cleanly (Node 22, no peer-dep
  errors).
- `npm run build` exits 0, produces `dist/` with at least the home page,
  the architecture overview, the three auto-generated pages, and one
  page per markdown file synced from `docs/`. Pagefind index gets built;
  `dist/sitemap-index.xml` exists.
- Build does **not** import any Python or run the FastAPI app — generators
  are regex-based plus the `yaml` package, never `python -c "from agentflow
  import ..."`.
- `npm run dev` serves the site on `http://127.0.0.1:8010/` (matching the
  port DE_project's existing local docs use).
- Re-running the generators after a code change picks up the new state
  (e.g. add a new FastAPI route → it appears in
  `/architecture/routes/`; add a new pipeline node → it shows up in
  `/architecture/pipelines/`).
- `.gitignore` keeps generated MDX, `node_modules/`, `dist/`, and
  `.astro/` out of git.
- After a push that triggers the workflow, the GitHub Actions run reaches
  `deploy=success` and the published URL returns HTTP 200 with the
  AgentFlow title (verify with `curl -I` once Pages is enabled and the
  repo is public).

## Notes / gotchas (carried over from the RAG implementation)

- Astro 6 requires Node ≥22.12.0 — pin Node 22 in the workflow, not 20.
- Starlight requires every markdown page to have a `title` in front-matter.
  `sync-docs.mjs` patches one in when missing, deriving from the H1 or
  filename. Keep that behaviour.
- For Windows local dev: `npm run dev` writes generators output to
  `src/content/docs/guides/` and `src/content/docs/architecture/{...}.mdx`
  before Astro's dev server starts. Make sure the generators run via a
  cross-platform `node scripts/...` chain in `predev`/`prebuild`, not
  PowerShell-specific commands.
- GitHub Pages on the **free** plan only works for public repos. If
  `D:\DE_project\` is currently private, either flip it public (sanity-
  check no committed secrets first: `git ls-files | grep -i "\.env$"`,
  scan history for `api_key` / `sk-` patterns, run bandit at -ll) or
  move the deploy target to Cloudflare Pages / Netlify (which support
  private GitHub repos through the GitHub App + token). The workflow
  itself is the same shape either way; only the deploy step changes.
- After enabling Pages via the GitHub Actions source, the *first* push
  run's deploy step may already 404 because the Pages backend creates the
  deployment slot lazily; re-trigger the workflow manually
  (`gh workflow run "Deploy docs site (Astro Starlight) to Pages"`) to
  pick up the now-provisioned slot.
- DE_project already enforces a workflow YAML ↔ pyproject.toml profile
  match (the A06 contract). The new `docs-site.yml` is a static-site
  workflow, not a Python profile, so it should sit outside that contract
  — confirm with the existing `.github/workflows/` layout before adding
  it. Do not edit Python profiles to mention the docs-site.
- Don't try to share `package.json` with anything Node-side that already
  exists in the repo; keep `docs-site/` self-contained so its
  dependencies do not leak into the rest of the project's CI.
- The reference implementation uses `pytestmark = skipif(sys.platform !=
  "win32")` to keep Windows-only autopilot tests out of Linux CI. If
  DE_project has analogous Windows-only tests, apply the same pattern
  rather than adding a Linux-only branch to the script.

## Out of scope

- Migrating AgentFlow's existing on-port-8010 docs (Sphinx / mkdocs / etc.)
  away from their current toolchain. Stand up the Astro site **alongside**
  the existing one; the user will decide later which becomes canonical.
- Live API browsers, OpenAPI try-it consoles, or React-component-heavy
  interactivity beyond what Starlight + Mermaid + the auto-generators give
  you for free. Defer custom interactive widgets to a follow-up task.
- Adding the docs-site to the project's protection-zone / dual-agent
  review surface. It is documentation tooling, not product code.
