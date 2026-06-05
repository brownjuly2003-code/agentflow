# OpenSSF Security Posture ($0 Channel)

**Added:** 2026-06-05
**Cost:** $0 (no card, no budget, no third party engaged)
**Scope of this document:** the two free, self-service OpenSSF artifacts this
project can produce to document its supply-chain security posture.

> **What this is NOT.** Neither artifact below is a third-party penetration
> test or attestation. OpenSSF Scorecard is an *automated* heuristic
> assessment; the Best Practices badge is *self-certification* by the
> maintainer. Backlog item 22 (external pen-test attestation) therefore stays
> **N/A / unclaimed** — see `docs/security-audit.md` §1 and
> `docs/release-readiness.md`. These are posture signals, kept explicitly
> distinct from third-party attestation, in the same discipline the audit doc
> already uses.

## 1. OpenSSF Scorecard (automated, live)

- **Channel:** `.github/workflows/scorecard.yml` (shape-pinned by
  `tests/unit/test_scorecard_workflow.py`).
- **What it does:** runs the OpenSSF/Google Scorecard heuristics
  (`ossf/scorecard-action@v2.4.3`, Scorecard v5.3.0) against this repository on
  every push to `main`, weekly, and on branch-protection changes. It assigns
  0–10 sub-scores for checks such as Branch-Protection, Token-Permissions,
  Pinned-Dependencies, Dangerous-Workflow, Code-Review, Maintained,
  Vulnerabilities, and SAST.
- **Artifacts produced:**
  - A SARIF result uploaded to the repository's **Code scanning** dashboard
    (`security-events: write`).
  - A **public, citable result** published to the OpenSSF registry
    (`publish_results: true`, OIDC `id-token: write`), readable at
    `https://api.securityscorecards.dev/projects/github.com/<owner>/<repo>`
    and badge-able via `api.securityscorecards.dev` /
    `scorecard.dev` shields.
- **How to read it after the first run:**
  1. Open the repo → **Security → Code scanning** to see per-check findings.
  2. Fetch the public JSON:
     `curl https://api.securityscorecards.dev/projects/github.com/brownjuly2003-code/agentflow`
  3. Optional README badge:
     `[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/brownjuly2003-code/agentflow/badge)](https://scorecard.dev/viewer/?uri=github.com/brownjuly2003-code/agentflow)`
- **Operator opt-out:** the only outward effect is publishing this repo's own
  posture score. To keep the result private, set `publish_results: false`
  (the SARIF still lands in Code scanning) and update the shape test.

## 2. OpenSSF Best Practices badge (SUBMITTED — live, in progress)

**Submitted 2026-06-05.** Live entry: **<https://www.bestpractices.dev/en/projects/13107>**
(project id `13107`, passing/Metal series, owned by the `brownjuly2003-code`
GitHub account). Current self-certified status: **81% (in_progress)** —
Quality 13/13, Security 15/16, Analysis 6/8, Basics 11/13, Change Control 7/9,
Reporting 2/8.

The remaining gap to a full passing badge is deliberate and honest: the
unclaimed Reporting criteria are the *responsiveness* ones (timely responses to
bug reports, enhancement requests, and vulnerability reports). A
portfolio/demo project with no external user base has no real track record to
self-certify those against, so they are left unmet rather than fabricated —
the same discipline as item 22's pen-test attestation. They can be marked Met
once the project has real report-response history.

The criteria below are the self-assessment that was filed (every Met is backed
by a real repository artifact). Evidence references are repository-relative.

Passing-level criteria, grouped:

### Basics
- **Project homepage / description:** `README.md` — MET.
- **Free/open license:** repository `LICENSE` (declared in `pyproject.toml`) —
  MET (confirm SPDX id on submission).
- **Documentation:** `README.md`, `docs/` (operations, runbooks, perf,
  security-audit) — MET.

### Change control
- **Public version-controlled source:** GitHub (`git`) — MET.
- **Unique version numbering / semver:** tags `v1.0.0 … v1.5.0` — MET.
- **Release notes:** `CHANGELOG.md` (Keep-a-Changelog form) — MET.

### Reporting
- **Bug-reporting process:** GitHub Issues + `CONTRIBUTING.md` — MET.
- **Vulnerability-reporting process:** `SECURITY.md` (private disclosure
  channel) — MET.

### Quality
- **Working build system / reproducible build:** `pyproject.toml`, CI `ci.yml`,
  `Dockerfile.api` — MET.
- **Automated test suite + CI:** large `tests/unit` + integration suites run by
  `ci.yml` / `contract.yml` / `e2e.yml` — MET.
- **Policy: tests for new functionality (TDD):** `CONTRIBUTING.md` +
  enforced shape/coverage/policy tests — MET.
- **Compiler/linter warning flags:** `ruff` (lint+format) and `mypy` strict
  (`disallow_untyped_defs = true` global) in CI — MET.

### Security
- **Developers know how to write secure software:** maintainer self-attest —
  CONFIRM on submission.
- **Good cryptographic practices:** API-key hashing argon2id (default) with
  bcrypt legacy fallback; TLS for CDC/transport — MET
  (`src/serving/api/auth/`, `docs/security-audit.md` §2).
- **Secured delivery against MITM:** HTTPS everywhere (GitHub, PyPI, npm);
  PyPI Trusted Publishing + npm Trusted Publishing (OIDC); CycloneDX SBOM +
  build provenance attestation (`security.yml`, `container-attestation.yml`) —
  MET.
- **Publicly-known vulnerabilities fixed:** Dependabot + Safety + Trivy in CI;
  CVE-driven dependency floors in `pyproject.toml` — MET.
- **No leaked credentials:** Bandit + `.bandit-baseline.json` (empty) +
  inline-`nosec`-with-reason policy — MET.

### Analysis
- **Static analysis:** Bandit, ruff, mypy, and now OpenSSF Scorecard's SAST
  check + Code scanning SARIF — MET.
- **Dynamic analysis:** Schemathesis property/fuzz testing of the API surface;
  load + chaos workflows (`load-test.yml`, `chaos.yml`) — MET.

**Open self-attest items for the operator at submission time:** secure-dev
knowledge confirmation, license SPDX id, and the public project URL field.

## 3. What this does and does not change for the backlog

- **Item 22 (external pen-test attestation):** status **unchanged — N/A /
  unclaimed.** These $0 artifacts are posture, not attestation. The audit doc
  and release-readiness wording stay authoritative.
- **No third-party claim is made.** If a real pen-test report ever arrives,
  route it through `docs/operations/external-pen-test-attestation-handoff.md`.

## 4. First Scorecard cycle — findings triaged (2026-06-06)

The first published run scored **5.8/10** and pushed **163 open findings**
into Code scanning. Triage split them into *fixed* and *honestly
accepted-open*; nothing was dismissed silently.

### Fixed

- **Pinned-Dependencies (GitHub actions, 99 refs):** every workflow `uses:`
  is pinned to a full commit SHA + `# <version>` comment (Dependabot keeps
  the pins fresh; `tests/unit/test_workflow_action_pinning.py` enforces the
  convention repo-wide).
- **Pinned-Dependencies (container images, 4 Dockerfiles):** all `FROM`
  lines carry the manifest-list digest of the tag they already used;
  `.github/dependabot.yml` `docker` ecosystem covers every Dockerfile
  directory so digests track upstream.
- **Token-Permissions (6 findings):** the five workflows running on an
  unrestricted default token got top-level `permissions: contents: read`;
  `container-attestation.yml` moved its `packages`/`id-token`/`attestations`
  writes from the workflow level down to the two operator-dispatched signing
  jobs (the every-PR `build-smoke` job is read-only now).
- **Vulnerabilities (2 OSV hits):** both came from resolution floors in the
  X5 demo loader's `requirements.txt` (`pydantic>=2.0` admits the
  GHSA-mr82-8j83-vxmv ReDoS range; `tqdm>=4.0` admits PYSEC-2017-74). Floors
  raised to `pydantic>=2.9` / `tqdm>=4.66.3`.

### Accepted-open (with reasons, not fabricated away)

- **Pinned-Dependencies (pip):** `pip install -e .[extras]` of the repo's own
  packages cannot be hash-pinned (`--require-hashes` rejects editable/local
  installs); converting CI and the Dockerfiles to fully hash-locked compiled
  requirements is an architectural change out of scope for posture cleanup.
  These findings stay open by design.
- **Code-Review / Contributors:** a single-maintainer portfolio repo cannot
  truthfully show second-person review or multi-org contributors.
- **Maintained:** scores activity over a 90-day window relative to project
  age; it converges on its own with normal activity.
- **CII-Best-Practices:** rises when the badge entry (project 13107, 81%
  in_progress) reaches passing — gated on the honest Reporting criteria, see
  §2.
- **Fuzzing:** the run reports "no fuzzer integrations found" — Scorecard's
  heuristic looks for OSS-Fuzz/ClusterFuzzLite-class integrations and does
  not register the repo's real Hypothesis property suites
  (`tests/property/`) or Schemathesis API fuzzing. The testing exists; only
  the badge heuristic misses it. No OSS-Fuzz onboarding is claimed — the
  2026-06-05 survey (BACKLOG item 22, $0 posture addendum) already ruled the
  project below OSS-Fuzz's adoption bar.
- **Branch-Protection (-1 inconclusive):** reading the full protection
  config needs an admin-scoped PAT secret; granting one to a scheduled
  workflow is worse for posture than an inconclusive sub-score.
- **Signed-Releases (-1 inconclusive):** releases ship via PyPI/npm Trusted
  Publishing (OIDC) with no GitHub-release binary artifacts to sign; the
  container path carries cosign + build provenance instead
  (`container-attestation.yml`).
