# Third-Party Pen-Test Intake

## Status

Current status: not present / unclaimed.

This checklist is the intake packet for a future third-party penetration-test
attestation. It does not create a security claim by itself. Do not claim that
AgentFlow has completed an external penetration test until the required
third-party evidence below exists, remediation is mapped to repository changes
or accepted risks, and retest status is recorded.

## Required decision record

| Field | Required value |
|-------|----------------|
| Assessor | Third-party organization name, primary contact, and independence statement |
| Engagement type | Black-box, gray-box, white-box, API-only, infrastructure, or combined |
| Tested target | Exact deployment URL, API surface, container image digest, Helm release, and commit SHA |
| Dates | Start date, end date, report date, and retest date when applicable |
| Scope | Included endpoints, auth roles, tenants, data stores, CI/CD, cloud resources, and explicit exclusions |
| Rules of engagement | Test windows, rate limits, destructive-test boundaries, and escalation path |
| Test credentials | Owner and rotation plan; never commit the credentials or raw tokens |
| Data handling | Confirmation that no production secrets, customer data, or private reports are committed |
| Remediation owner | Person accountable for fixes, retest coordination, and risk acceptance |

## Required third-party evidence

- Final report or portal export from the assessor, stored in an approved
  non-repository location if it is confidential.
- Redacted executive summary suitable for repository documentation, including
  assessor name, dates, target, scope, severity counts, and explicit exclusions.
- Finding inventory with stable IDs, severity, affected component, exploit
  preconditions, and remediation owner.
- Remediation map from each finding to a commit, PR, configuration change, or
  signed risk acceptance.
- Retest report or assessor confirmation for every finding claimed fixed.
- Remaining-risk record for findings that are accepted, deferred, duplicate, or
  out of scope.
- Evidence that all test credentials, API keys, callbacks, and temporary access
  paths were rotated or revoked after the engagement.

## Repository intake

1. Keep the full unredacted report outside git unless the assessor and security
   owner explicitly approve publication.
2. Add only a redacted summary under `docs/operations/` or `docs/security-*.md`.
3. Update `docs/security-audit.md`, `docs/release-readiness.md`, and
   `docs/STATUS.md` only after the report and remediation/retest evidence exist.
4. Link repository-visible evidence to immutable commits, CI run URLs, or
   redacted artifact locations.
5. Keep OpenSSF Scorecard and Best Practices wording separate from this
   attestation. Those are posture signals, not penetration tests.

## No-go conditions

- The assessor is not independent from the repository maintainer.
- The report scope omits the public API but the requested claim says
  "AgentFlow was penetration tested" without qualification.
- Findings marked fixed have no commit/configuration evidence or no retest.
- The only evidence is an automated scan without human assessment.
- The packet requires committing secrets, private hostnames, customer data,
  raw report contents, or live exploit payloads.
- Risk acceptance has no named owner and expiration or revisit date.

## Acceptance checklist

- [ ] Required decision record is complete.
- [ ] Redacted summary is safe to publish.
- [ ] Full report location is recorded outside git.
- [ ] Every finding has a remediation/retest or accepted-risk state.
- [ ] Temporary credentials and network openings were revoked or rotated.
- [ ] Security audit wording still distinguishes internal scans from the
      external third-party attestation.
- [ ] Release readiness links to the redacted evidence and keeps any remaining
      blockers explicit.
