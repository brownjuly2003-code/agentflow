# External Gate Evidence Intake Checklist

## Purpose

Use this checklist before marking any blocked external release gate or
account-control follow-up complete. The item stays blocked until a real
operator or owner supplies the required fields and links to acceptable
artifacts. Internal repo analysis, modeled planning, local dry runs, or verbal
updates are not enough.

This document is an intake standard only. It does not authorize AWS access,
Terraform apply, production CDC attachment, customer outreach, paid services,
benchmark publication, security testing, deploys, or external account changes.

## Intake Rules

- Record the submitting owner, review owner, evidence date, and artifact
  location before changing release readiness or publication follow-up status.
- Prefer links to durable artifacts: repository paths, GitHub run URLs, secure
  evidence folders, ticket IDs, signed reports, dashboards, or exported metric
  files.
- Redact secrets, credentials, customer records, private hostnames, account IDs,
  and raw production data before linking from the repo.
- Keep the item blocked if required fields are incomplete, evidence is stale for
  the claimed state, or the reviewer cannot inspect the artifact.
- Do not replace the existing handoff docs. Link this intake record beside the
  item-specific handoff after evidence is accepted.

## Project-Local Pi Skill

The project-local Pi skill at `.pi/skills/external-gate-evidence-intake` wraps
this checklist for operator sessions. It is a workflow aid only: using the skill
does not authorize external account changes and does not make local analysis,
modeled evidence, or historical CI runs sufficient to close a gate.

## Coverage

| Item | Source handoff |
|------|----------------|
| AWS OIDC Terraform apply readiness | [AWS OIDC Setup For Terraform Apply](aws-oidc-setup.md) |
| Production CDC source onboarding | [Production CDC Source Onboarding](cdc-production-onboarding.md) |
| Phase 1 PMF and pricing evidence | [Customer Discovery Tracker](../customer-discovery-tracker.md) and [Pricing Validation Plan](../pricing-validation-plan.md) |
| Public production-hardware benchmark | [Public Production-Hardware Benchmark Plan](../perf/public-production-hardware-benchmark-plan.md) |
| External pen-test attestation | [External Pen-Test Attestation Handoff](external-pen-test-attestation-handoff.md) |
| Legacy npm `NPM_TOKEN` revocation | [Publication Checklist](../publication-checklist.md) |

## AWS OIDC Terraform Apply Readiness

Source handoff: [AWS OIDC Setup For Terraform Apply](aws-oidc-setup.md).

### Required Owner-Provided Fields

| Field | Required value |
|-------|----------------|
| AWS account owner | Team/person accountable for the target AWS account |
| Bootstrap operator | Person who ran or supervised the first trusted bootstrap |
| IAM role creation path | Approved method used to create the GitHub Actions OIDC role |
| `AWS_TERRAFORM_ROLE_ARN` | Exact non-secret role ARN configured in repository variables |
| `AWS_REGION` | Region used by Terraform and GitHub Actions |
| tfvars owner | Owner and secure location for staging/prod tfvars |
| Workflow guard approval | Explicit approval to remove the workflow-level `if: false` guard |
| First apply scope | Environment, commit SHA, reviewer, and rollback owner |
| OIDC proof | CloudTrail or equivalent proof of `AssumeRoleWithWebIdentity` |
| Apply evidence | GitHub Actions run URL or operator transcript with exit code |

### Acceptable Artifact Links Or Paths

- GitHub Actions run URL for the approved `Terraform Apply` run.
- Redacted CloudTrail export showing `AssumeRoleWithWebIdentity`.
- Repository variable screenshot or admin export showing
  `AWS_TERRAFORM_ROLE_ARN` and `AWS_REGION` without secrets.
- Secure ticket or evidence-folder link for real tfvars ownership and storage.
- Terraform plan/apply transcript with commit SHA, environment, and exit code.

### Explicit No-Go Conditions

- `AWS_TERRAFORM_ROLE_ARN` is absent or only described verbally.
- `.github/workflows/terraform-apply.yml` still has `if: false` and no operator
  approval exists to remove it.
- Real staging or production tfvars are missing or stored in the repo.
- The apply depends on long-lived AWS access keys instead of GitHub OIDC.
- No reviewer or rollback owner is named for the first apply.

### Insufficient Evidence

- `terraform init -backend=false`, `terraform validate`, or local container
  validation only.
- The presence of `AWS_REGION` alone.
- A planned role name without a configured ARN.
- Screenshots that omit date, account, workflow, or run result.
- Any claim based on this workstation having AWS access.

## Production CDC Source Onboarding

Source handoff: [Production CDC Source Onboarding](cdc-production-onboarding.md).

### Required Owner-Provided Fields

| Field | Required value |
|-------|----------------|
| Source owner | Team and escalation contact for the database |
| Secret owner | Team/person responsible for CDC credential lifecycle |
| Source details | Engine, version, hostname, port, and database name |
| Table scope | Explicit schema/table allowlist |
| Data classification | PII, financial, operational, or public classification |
| Network path owner | Owner and approved private path from Kafka Connect to source |
| Kubernetes Secret | Existing Secret name, namespace, and owner |
| Snapshot policy | Full, incremental, or schema-only start with approved window |
| Monitoring owner | Owner for lag, connector status, dead letters, and freshness |
| Rollback owner | Person authorized to pause/delete connector and rotate credentials |
| First-run evidence | Connector status, topic list, normalized event, lag/freshness record |

### Acceptable Artifact Links Or Paths

- Completed production CDC decision record or approved change ticket.
- Redacted network reachability proof from Kafka Connect to the source host.
- Secret-management record naming the existing Kubernetes Secret and owner.
- Connector status export showing tasks `RUNNING`.
- Topic list showing expected raw and heartbeat topics.
- Redacted first normalized event sample and dead-letter/lag metric export.

### Explicit No-Go Conditions

- Table scope uses wildcards or includes unreviewed sensitive tables.
- The CDC user cannot be rotated or revoked on demand.
- The source is reachable only over a public network path.
- Production credentials would be committed or rendered from Helm values.
- The source owner has not approved replication, binlog, snapshot load, or slot
  settings.
- No operator is assigned to monitor the first snapshot.

### Insufficient Evidence

- Local/demo CDC compose success.
- Kubernetes-shaped Helm rendering without real source approval.
- Placeholder hostnames, example credentials, or wildcard table lists.
- A connector config without source-owner, secret-owner, and rollback-owner
  signoff.
- A topic list without proof of normalized events and monitored lag.

## Phase 1 PMF And Pricing Evidence

Source handoffs: [Customer Discovery Tracker](../customer-discovery-tracker.md)
and [Pricing Validation Plan](../pricing-validation-plan.md).

### Required Owner-Provided Fields

| Field | Required value |
|-------|----------------|
| Evidence owner | Founder/operator accountable for customer evidence |
| Participant identity | Company, role, segment, and non-secret contact reference |
| Outreach record | Date, channel, consent/context, and outcome |
| Interview record | Date, interviewer, notes location, and workflow discussed |
| PMF signal | Concrete pain, urgency, current workaround, and success criteria |
| Pricing signal | Budget owner, replaceable cost, natural value metric, pilot shape, and pricing risk |
| First-paying-customer signal | Paid pilot, purchase intent, procurement path, LOI, invoice, or contract status |
| Evidence count | Real sends, replies, scheduled calls, completed interviews, and paying-customer signals |
| Review owner | Person approving that evidence can update release readiness |

### Acceptable Artifact Links Or Paths

- Redacted interview notes in the tracker or a secure research folder.
- CRM, email, calendar, or ticket links that prove real outreach and scheduling.
- Signed LOI, pilot agreement, invoice, or procurement ticket with sensitive
  details redacted.
- Pricing/WTP notes tied to a named interview and workflow.
- Post-batch review table showing the first 5 real interviews and pricing-gate
  counts.

### Explicit No-Go Conditions

- Evidence counts remain `0` for real outreach, replies, interviews, or PMF
  score records.
- The only material is synthetic/modelled discovery.
- Pricing gates are not met but public pricing, tiers, or sales collateral are
  proposed.
- Participant identity, segment, or workflow is too vague to audit.
- The evidence exposes private contact details, customer data, or commercial
  terms in the repo.

### Insufficient Evidence

- Modeled candidates, simulated sends, simulated replies, or public research
  anchors.
- Generic interest without budget owner, replaceable cost, or pilot path.
- Competitor pricing pages used as a substitute for buyer WTP.
- Verbal founder confidence without dated notes or artifact links.
- First-paying-customer claims without a signed, invoiced, or procurement-backed
  artifact.

## Public Production-Hardware Benchmark Evidence

Source handoff:
[Public Production-Hardware Benchmark Plan](../perf/public-production-hardware-benchmark-plan.md).

### Required Owner-Provided Fields

| Field | Required value |
|-------|----------------|
| Benchmark owner | Operator accountable for the run and publication request |
| Hardware description | Instance class, CPU architecture, memory, OS, region, and lifecycle owner |
| Commit SHA | Exact checked-out commit used for the benchmark |
| API target topology | Local host, same private network, or remote target URL description |
| Data fixture owner | Confirmation that fixtures contain no production/customer data |
| Command transcript | Benchmark and performance-check commands with exit codes |
| Result artifacts | JSON results, human-readable report, logs, and environment metadata |
| Caveats | Excluded endpoints, noisy-neighbor notes, warmup, duration, and topology caveats |
| Publication approval | Owner approval to publish summarized latency/throughput numbers |

### Acceptable Artifact Links Or Paths

- `.artifacts/benchmark/...` JSON and report paths, if intentionally preserved
  as release evidence.
- Secure evidence-folder link containing benchmark logs and host metadata.
- Redacted terminal transcript for `scripts/run_benchmark.py` and
  `scripts/check_performance.py`.
- Screenshot or export of instance metadata that excludes account IDs and
  billing details.
- Release note draft that distinguishes production-hardware results from local
  and CI baselines.

### Explicit No-Go Conditions

- Hardware is below `c8g.4xlarge+` or lacks an approved equivalent rationale.
- The run uses production data, customer records, credentials, or private
  account details.
- Hardware, topology, commit, or command parameters are missing.
- Results are compared directly against laptop, CI-runner, or ad hoc local
  baselines without clear caveats.
- Publication approval is absent.

### Insufficient Evidence

- Existing checked-in single-node baseline only.
- Local laptop, GitHub-hosted runner, or unlabelled VM results.
- A benchmark summary without raw JSON, command transcript, and environment
  metadata.
- Screenshots of latency numbers without commit SHA and topology.
- Operator notes that omit fixture safety or publication approval.

## External Pen-Test Attestation

Source handoff:
[External Pen-Test Attestation Handoff](external-pen-test-attestation-handoff.md).

### Required Owner-Provided Fields

| Field | Required value |
|-------|----------------|
| Tester identity | External firm or named independent tester |
| Tester contact | Non-secret contact or procurement reference |
| Test scope | Domains, APIs, deployment targets, auth modes, and exclusions |
| Test window | Start date, end date, and report date |
| Method | Black-box, gray-box, white-box, authenticated, unauthenticated |
| Severity summary | Critical, high, medium, low, and informational counts |
| Report artifact | Redacted report path or secure evidence location |
| Remediation mapping | Finding IDs mapped to issues, commits, or documented non-fixes |
| Retest status | Not started, scheduled, passed, or residual-risk accepted |
| Attestation owner | Person accountable for customer-facing claims |

### Acceptable Artifact Links Or Paths

- Redacted third-party pen-test report.
- Signed attestation letter from the tester or assessment firm.
- Secure evidence-folder link with report, scope, dates, and severity summary.
- Remediation tracker mapping critical/high findings to fixes or accepted risk.
- Retest report or residual-risk acceptance record.

### Explicit No-Go Conditions

- Only internal security audit, static analysis, CI scanning, or modelled audit
  history exists.
- The report lacks date, scope, severity summary, tester identity, or owner.
- Critical/high findings have no remediation mapping or accepted-risk owner.
- The artifact would expose secrets, private infrastructure, customer data, or
  account material in the repo.
- Customer-facing claims exceed the tested scope.

### Insufficient Evidence

- `docs/security-audit.md`, `.bandit-baseline.json`, Trivy, Bandit, Safety, or
  release-readiness scan results alone.
- Verbal confirmation that a test happened.
- A generic vendor security questionnaire without test scope and findings.
- An unredacted report that cannot be linked or reviewed safely.
- A retest claim without the original finding IDs and outcome.

## Legacy npm `NPM_TOKEN` Revocation Evidence

Source handoff: [Publication Checklist](../publication-checklist.md).

### Required Owner-Provided Fields

| Field | Required value |
|-------|----------------|
| Token owner | npm/GitHub owner accountable for the legacy token |
| Revocation operator | Person who revoked the token or supervised revocation |
| Trusted-publish proof | Successful GitHub Actions publish run using npm OIDC |
| Package scope | Exact package name and version published without `NPM_TOKEN` |
| Repository secret audit | Evidence that `NPM_TOKEN` is absent or intentionally disabled |
| npm token audit | Redacted npm token/settings evidence showing the old token is revoked |
| Recovery-code reserve check | Confirmation that no reserve rule was violated for any OTP-gated step |
| Review owner | Person approving the release-readiness update |

### Acceptable Artifact Links Or Paths

- GitHub Actions run URL for a successful `publish-npm.yml` trusted-publish run.
- Redacted GitHub secret list or admin export showing `NPM_TOKEN` removed.
- Redacted npm token/settings screenshot or CLI transcript showing revocation.
- Operator note confirming whether any OTP or recovery code was used without
  printing the OTP, recovery code, token value, auth URL, or cookie.
- Publication checklist update that links the trusted-publish proof and
  revocation evidence.

### Explicit No-Go Conditions

- No successful trusted-publish workflow run exists for the new package.
- The successful publish run targets the legacy package scope instead of the
  new package scope being approved for future publishing.
- `NPM_TOKEN` still exists as an active repository secret after revocation is
  claimed.
- The package publish path still depends on `NODE_AUTH_TOKEN` or `NPM_TOKEN`.
- An OTP-gated npm action would consume a recovery code below the required
  reserve.
- The evidence exposes npm tokens, OTPs, recovery codes, auth URLs, cookies, or
  private account material in the repo.

### Insufficient Evidence

- `.github/workflows/publish-npm.yml` using OIDC by itself.
- `npm trust list` output without a later successful trusted-publish run.
- A green `publish-npm.yml` run that predates the no-token workflow path or
  publishes a different package scope.
- The package being visible on npm before the token is revoked.
- Verbal confirmation that the token was deleted.
- A screenshot that hides the token value but does not show revocation state,
  date, owner, or package/workflow context.

## Acceptance Record Template

Copy this table into the item-specific handoff, release-readiness update, or
publication follow-up only after evidence passes intake review.

| Field | Value |
|-------|-------|
| Gate or follow-up |  |
| Evidence owner |  |
| Review owner |  |
| Evidence date |  |
| Artifact links/paths |  |
| Required fields complete | Yes / No |
| No-go conditions checked | Yes / No |
| Insufficient-evidence cases excluded | Yes / No |
| Accepted release-readiness or publication update |  |
