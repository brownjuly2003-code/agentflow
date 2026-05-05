# External Pen-Test Attestation Handoff

## Status

Status as of 2026-05-06: blocked on an external pen-test report or
attestation.

The repository contains internal security audit evidence, CI security scan
evidence, and audit-closure history. Those artifacts are not a substitute for a
third-party penetration test attestation.

Access triage on 2026-05-04 found no external testing firm, named independent
tester, report artifact, signed attestation, scope, test window, severity
summary, remediation mapping, retest status, or attestation owner in the repo or
task prompt. No external scan, exploitation, or paid security service was run.

Local evidence update on 2026-05-06 added
`docs/operations/security-evidence-template.md` for free internal scan evidence.
That template is not an external pen-test substitute and does not close H5.

Next operator packet to unblock review:

- External tester identity, non-secret contact/procurement reference, and
  attestation owner.
- Test scope, test window, method, exclusions, and customer-facing claim scope.
- Redacted report or signed attestation with severity summary.
- Remediation mapping for critical/high findings, retest status, and any
  accepted residual-risk owner.

## Required Attestation Record

Do not claim external pen-test completion until every field below is supplied by
the tester or the operator responsible for the assessment.

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

## Evidence Boundary

Internal evidence currently includes:

- `docs/security-audit.md`
- `docs/audit-history.md`
- `.github/workflows/security.yml`
- `.bandit-baseline.json`
- release-readiness scan and full-suite records
- `docs/operations/security-evidence-template.md`

Use those files for internal posture only. Customer-facing security
questionnaires must not describe a completed third-party pen test until an
external report or attestation is available and linked from this handoff.

## No-Go Conditions

Keep this item blocked if any condition is true:

- The only evidence is internal review, static analysis, CI scanning, or modelled
  audit history.
- The report is verbal only and has no date, scope, severity summary, or owner.
- The attestation cannot distinguish fixed findings from accepted residual risk.
- The artifact location would expose secrets, private target details, customer
  data, or account material in the repository.

## Publication Checklist

Before updating release readiness or customer-facing material:

- Confirm the report scope matches the product surface being claimed.
- Redact secrets, private infrastructure details, and customer data.
- Record the severity summary and retest status.
- Link remediation evidence for every critical or high finding.
- Record any accepted residual risk with an accountable owner.
- Keep internal audit evidence separate from third-party attestation evidence.
