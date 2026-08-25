# Security Policy

## Supported versions

Security fixes are released against the **current `v2.x` line**. The current
release on PyPI / npm is the supported version; previous minor versions on
the same `v2.x` line receive backports at maintainer discretion when the
fix is mechanical.

See [docs/dv2-multi-branch/RELEASE_STATUS.md](docs/dv2-multi-branch/RELEASE_STATUS.md)
for the live published version.

| Version line | Supported |
|--------------|-----------|
| `2.x` (current) | ✅ Yes |
| `< 2.0` | ❌ No |

## Reporting a vulnerability

**Do not report security vulnerabilities through public GitHub issues,
discussions, or pull requests.**

Use one of these private channels:

1. **GitHub Security Advisories** (preferred):
   https://github.com/brownjuly2003-code/agentflow/security/advisories/new
   — opens a private draft advisory the maintainers can triage and
   collaborate on without exposing the report.
2. **Email**: send a report to the address listed on the maintainer's
   GitHub profile (`brownjuly2003-code`). Use `[SECURITY]` in the subject
   line.

Include in your report:

- A description of the issue and the affected component / version.
- Steps to reproduce (proof-of-concept code or a minimal repro is
  appreciated, never required).
- Your assessment of severity and impact (data exposure, RCE, auth
  bypass, supply-chain risk, etc.).
- Any disclosure timeline constraints on your side.

We will acknowledge receipt within **3 business days** and aim to share an
initial triage decision within **7 business days**.

## What is in scope

- The AgentFlow API (`src/agentflow_runtime/serving/api/`) — auth, tenant isolation, SQL
  guard, rate limiting, input validation, secrets handling.
- The Python SDK (`sdk/agentflow/`) and the TypeScript SDK
  (`sdk-ts/`) — both as installed from PyPI / npm.
- The published wheels and the npm tarball — supply-chain integrity,
  bundled secrets, malicious dependencies.
- The published container image when one exists (`Dockerfile.api`).
- The Helm chart defaults (`helm/agentflow/`, `helm/kafka-connect/`) —
  insecure defaults, secret exposure, privilege escalation.
- The release pipeline (`.github/workflows/publish-pypi.yml`,
  `.github/workflows/publish-npm.yml`,
  `.github/workflows/container-attestation.yml`) — provenance, OIDC
  trust, signing.

## What is out of scope

- Vulnerabilities in third-party dependencies that already have a public
  advisory — those should go to the upstream maintainer; we will pick up
  the fix on our normal dependency-bump cadence (see
  `safety` / `npm audit` / `trivy` jobs in `.github/workflows/`).
- Findings that require an attacker to already have full control of the
  host running AgentFlow, or to already hold admin credentials.
- The DV2 multi-branch demo cluster (`infrastructure/dv2/`,
  `warehouse/agentflow/dv2/`) — that is a single-machine showcase and
  has no users.
- Social engineering of the maintainer.
- Theoretical issues without a concrete attack path against a real
  AgentFlow deployment.

## Disclosure policy

Default policy is **coordinated disclosure**: we ask for up to 90 days
from acknowledgement to publish a fix and the advisory, longer for
issues that require a coordinated SDK + runtime + Helm chart release.
We will work with reporters on shorter timelines for low-severity
findings or longer timelines for harder-to-fix ones.

When a fix ships, the advisory is published with credit to the reporter
unless they prefer to remain anonymous.

## What query analytics keeps

`/v1/query` takes a free-text question, so an analytics record can end up
holding whatever a caller typed — personal data, commercial figures, or a
credential pasted from somewhere else. The policy is deliberately narrow
(audit F-18):

- **By default no question text is stored.** The record keeps a peppered
  HMAC fingerprint of the normalised question, which answers what analytics is
  for — which questions repeat, and how often — without keeping the question.
  `GET /v1/admin/analytics/top-queries` returns that fingerprint with a null
  `query`.
- **Storing text is opt-in and still redacted.** With
  `AGENTFLOW_QUERY_ANALYTICS_STORE_TEXT=true` the question is kept with
  emails, credential-shaped tokens, JWTs and long digit runs replaced by
  placeholders, and truncated to 1000 characters. There is deliberately no
  setting that stores the raw prompt: an operator's decision to read questions
  is not the user's consent to have a pasted secret retained.
- **Retention is finite.** `AGENTFLOW_QUERY_ANALYTICS_RETENTION_DAYS`
  (default 30) is the window, and `scripts/prune_query_analytics.py` is what
  enforces it — run it on a schedule against the store the API writes to.
  Nothing prunes automatically; a deployment that never runs the job keeps
  analytics indefinitely, which is the state this policy exists to end.
- **Fingerprints are peppered** (`AGENTFLOW_QUERY_FINGERPRINT_PEPPER`) so a
  leaked analytics table cannot be joined against fingerprints of the same
  questions computed elsewhere. Changing the pepper re-partitions history:
  older rows stop grouping with newer ones.

`api_usage` — per-tenant, per-key, per-endpoint counters with no user content —
is out of this window on purpose: it is the record of how much a tenant used,
which is a billing and abuse-investigation surface with its own lifetime.

A tenant asking for their analytics to be deleted does not wait out the
window: `scripts/prune_query_analytics.py --erase-tenant <tenant>` removes
every `api_sessions` row for that tenant whatever its age. It leaves
`api_usage` counters in place for the reason above.

Two things this policy does **not** claim. Analytics rows are stored by
whichever control-plane store is configured — encryption at rest is the
deployment's property (an encrypted volume, a managed PostgreSQL with
encryption enabled), not something the application does to the column. And
reads of `GET /v1/admin/analytics/top-queries` are authenticated and
rate-limited but not written to a separate access-audit trail; if you opt into
storing question text, treat who may hold an admin key as the access control.

## Hardening references

If you are deploying AgentFlow yourself, the following docs describe the
hardening already in place — useful context when assessing severity:

- [docs/security-audit.md](docs/security-audit.md) — threat model and
  control surface.
- [docs/runbooks/auth-401-spike.md](docs/runbooks/auth-401-spike.md) —
  fail-closed auth behavior, recovery, and emergency bypass rules.
- [docs/runbooks/release-rollback.md](docs/runbooks/release-rollback.md)
  — yank/deprecate procedure when a leaked secret reaches a published
  artifact.
- [docs/operations/cdc-production-onboarding.md](docs/operations/cdc-production-onboarding.md)
  — production CDC decision record and secret-ownership requirements.
