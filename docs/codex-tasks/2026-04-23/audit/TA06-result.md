# TA06 result

- Snapshot: local `HEAD a010a2d` on `main` as of `2026-04-23`.
- Scope checked: `README.md`, `CHANGELOG.md`, `docs/architecture.md`, `docs/runbook.md`, `docs/helm-deployment.md`, `docs/codex-tasks/2026-04-23/README.md`, `CONTRIBUTING.md`, `docs/contributing.md`, `.github/PULL_REQUEST_TEMPLATE.md`, and the presence of `docs/codex-tasks/2026-04-24/README.md`.
- Verified with no gap: local links from `README.md:106-116` are live, and `docs/codex-tasks/2026-04-23/audit/README.md` matches the current audit split.

## Docs alignment audit

| Doc | Section | Issue | Recommendation |
|-----|---------|-------|----------------|
| `README.md` | badges / release status (`5-6`, `111`, `139`) | Top-of-file status is misleading as current-state guidance: the badge is a static green `tests-543_verified` shield, while the README still says `v1.0.0` is release-ready even though `pyproject.toml:3` is `1.0.1`. | Add a live `CI` badge for `main`, relabel the static badge as a checked release slice, and update current-state copy from `v1.0.0` to `v1.0.1` or "current repository state". |
| `README.md` | Quick start / Development (`38-56`, `120-135`) | README routes contributors through `scripts/setup.*`, but those scripts install only `.[dev]` plus `sdk/` (`scripts/setup.ps1:47-50`, `scripts/setup.sh:54-56`). Full local verification now expects `.[dev,integrations,cloud]` (`Makefile:5-8`, `CHANGELOG.md:135-147`, `.github/workflows/ci.yml:60-101`). | Add an explicit "full contributor install" command (`make setup` or `pip install -e ".[dev,integrations,cloud]"`) and label the script path as the quick demo setup. |
| `CHANGELOG.md` | `[Unreleased]` CI repair trail (`87-123`) | The trail still says E2E used `docker-compose.prod.yml` and was not investigated, but the checked-in workflow and tests now use `docker-compose.e2e.yml` (`.github/workflows/e2e.yml:32-93`, `tests/e2e/test_ci_compose_config.py:20-49`). | Replace the stale E2E bullet with the final outcome: lite compose stack, health polling via `docker compose ... ps --format json`, and the narrowed service set. |
| `CHANGELOG.md` | missing sprint outcomes (`45-75`, `87-123`) | `[Unreleased]` does not capture several merged CI-repair outcomes: explicit staging `key_id` values (`k8s/staging/values-staging.yaml:47-70`), the security image pin `setuptools==82.0.1` / `wheel==0.47.0` (`docker-compose.prod.yml:184`), and the post-audit follow-up batch under `docs/codex-tasks/2026-04-24/`. | Add concrete bullets under `Changed`, `Security`/`Dependencies`, and `Documentation` so the changelog reflects the actual post-sprint repo state. |
| `docs/architecture.md` | production serving path (`40-57`) | The document says production serving reads from Iceberg via Trino / Athena (`46`), but the checked-in serving layer exposes DuckDB and optional ClickHouse backends, not a Trino/Athena runtime path. | Rewrite the serving sentence so Iceberg remains storage context, while the current checked-in serving backends are described accurately. |
| `docs/architecture.md` | deployment topologies (`138-142`) | The "Prod-like Docker" row still claims `docker-compose.prod.yml` covers E2E and smoke, but `.github/workflows/e2e.yml:32-93` moved E2E to `docker-compose.e2e.yml`. | Split the topology table into two entries: prod-like observability stack on `docker-compose.prod.yml` and lite E2E stack on `docker-compose.e2e.yml`. |
| `docs/architecture.md` | known issues / SDK packaging | The architecture doc is silent about the root/SDK package-name collision, even though both manifests are still `name = "agentflow"` (`pyproject.toml:2`, `sdk/pyproject.toml:2`) and `CHANGELOG.md:92-96` already documents the install conflict. | Add a short known-issue note or link to the follow-up ticket so contributors do not rediscover the collision during editable installs. |
| `docs/runbook.md` | Docker stack / incidents (`49-59`, `123-130`) | Runbook guidance still routes E2E-style bring-up and incident commands through `docker-compose.prod.yml`, while the current E2E workflow uses the lighter `docker-compose.e2e.yml`. | Add a dedicated E2E subsection for `docker-compose.e2e.yml` and narrow `docker-compose.prod.yml` to observability or prod-like debugging only. |
| `docs/runbook.md` | maintenance / security (`191-204`) | There is no documented Trivy remediation path or `.trivyignore` procedure, even though the Security Scan now runs with `ignore-unfixed: true` (`.github/workflows/security.yml:103-116`). | Add a short maintenance note describing when to bump dependencies versus when to add a scoped `.trivyignore` entry with reason and review date. |
| `docs/helm-deployment.md` | API key examples (`43-70`) | Helm examples still show API keys without `key_id`, while staging seed values now carry explicit `key_id` entries (`k8s/staging/values-staging.yaml:47-70`) used by rotation/status flows and deterministic staging fixtures. | Add `key_id` to the sample keys and explain why stable IDs matter for admin rotation and staging checks. |
| `docs/codex-tasks/2026-04-23/README.md` | snapshot/status (`8-10`) | The index still says `HEAD 5631353`, "CI fully red", and a clean pre-T00 tree, but `docs/codex-tasks/2026-04-23/audit/README.md:10-33` treats the sprint as closed and `T05-result.md:3-31` records follow-up tickets. | Mark the file as historical kickoff context or update the status block to closed/completed with links to the result docs. |
| `docs/codex-tasks/2026-04-23/README.md` | execution order (`34-41`) | The order section is still a plan-only sequence and does not point readers to the actual result trail (`T05-result.md`, audit split, and 2026-04-24 follow-ups). | Add a post-sprint note linking to `audit/README.md`, `T05-result.md`, and `docs/codex-tasks/2026-04-24/README.md`. |
| `docs/codex-tasks/2026-04-24/README.md` | missing file | The folder already contains `T06`-`T13` follow-up tickets, but there was no README index. | Create the missing index README and group the original T06-T09 batch plus later audit-created tickets. |
| `CONTRIBUTING.md` | setup / verification (`5-18`, `27-52`) | The contributor guide points to `scripts/setup.*` and test commands, but it does not document the full extras install path or `ruff format --check`, so local verification prerequisites are incomplete. | Add `make setup` / `pip install -e ".[dev,integrations,cloud]"` and list `ruff check`, `ruff format --check`, and `mypy` explicitly. |
| `docs/contributing.md` | setup / test matrix (`9-45`, `79-101`) | The secondary contributing doc has the same missing full-install guidance and still treats `docker-compose.prod.yml` as the default non-demo stack after the E2E split. | Either collapse guidance into root `CONTRIBUTING.md` or keep both files but synchronize install, compose, and verification instructions. |
| `.github/PULL_REQUEST_TEMPLATE.md` | missing file | The repository has no PR template to prompt doc-sync checks, formatting checks, or workflow-specific verification. | Add a lightweight PR template or explicitly route all PR hygiene through `CONTRIBUTING.md`. |

## Suggested CHANGELOG bullets

- `Changed:` E2E automation now uses `docker-compose.e2e.yml` plus compose-health polling instead of the heavier `docker-compose.prod.yml` path.
- `Changed:` staging sample keys in `k8s/staging/values-staging.yaml` now include explicit `key_id` values for stable admin-rotation and staging assertions.
- `Security:` the production-image build path upgrades `setuptools==82.0.1` and `wheel==0.47.0` before the Trivy scan image is evaluated.
- `Documentation:` add `docs/codex-tasks/2026-04-24/README.md` as the follow-up ticket index for T06-T13.

## Single recommended PR

`docs: align documentation with CI repair sprint state`

Checklist of edits:

- `README.md:5-8, 30-56, 111, 137-139` — add a live CI badge or relabel the static badge, add the full contributor install command, and update current-state release text from `v1.0.0` to `v1.0.1`.
- `CHANGELOG.md:45-123` — refresh `[Unreleased]` so it reflects the final E2E compose split, staging key IDs, security-image dependency pin, and the post-audit follow-up batch.
- `docs/architecture.md:40-57, 138-142` — remove the Trino/Athena direct-serving claim, add a lite E2E topology entry, and mention the duplicate `agentflow` package-name known issue.
- `docs/runbook.md:49-59, 121-130, 191-204` — split prod-like versus E2E stack instructions and add a short Trivy / `.trivyignore` maintenance note.
- `docs/helm-deployment.md:43-70` — add `key_id` to the sample key payloads and explain its role in rotation/status flows.
- `CONTRIBUTING.md:5-18, 27-52` and `docs/contributing.md:9-45, 79-101` — document `make setup` / `pip install -e ".[dev,integrations,cloud]"`, plus `ruff check`, `ruff format --check`, and `mypy`.
- `docs/codex-tasks/2026-04-23/README.md:8-10, 34-41` — mark the file as historical kickoff context and link to the actual result trail.
- `.github/PULL_REQUEST_TEMPLATE.md` — optionally add a small checklist for docs sync, formatting, targeted tests, and affected workflows.
