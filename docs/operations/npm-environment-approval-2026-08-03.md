# GitHub Environment `npm` approval protection — PASS

- **Recorded (UTC):** `2026-08-03T03:18:11Z`
- **Audit mode:** read-only GitHub API verification
- **Repository:** `brownjuly2003-code/agentflow`
- **Local HEAD:** `6d8ead454181fe898aebfc75aec2e3b9a460f74b`

**Audience:** release manager / repository admin reading the audit record

**Prerequisites:** none; this page is a record, the procedure lives in [publication-checklist.md](publication-checklist.md)

## Verdict

**PASS.** The GitHub Environment used by the npm publishing workflow exists
under the exact name `npm` and has a non-empty `required_reviewers` rule. The
reviewer returned by GitHub is user `brownjuly2003-code`, id `260272870`.

This closes the repository's Environment approval-protection evidence gate. It
does not elevate the golden topology beyond `candidate`: fresh 4h
soak/rollback and independent penetration-test evidence remain open.

## Verified contract

The local workflow at `.github/workflows/publish-npm.yml` binds its `publish`
job to `environment: npm`. A single read-only request queried the matching
GitHub Environment:

```powershell
gh api --method GET repos/brownjuly2003-code/agentflow/environments/npm --jq '{id: .id, name: .name, protection_rules: [.protection_rules[] | {type: .type, prevent_self_review: .prevent_self_review, reviewers: [.reviewers[]? | {type: .type, id: .reviewer.id, login: .reviewer.login}]}], deployment_branch_policy: .deployment_branch_policy}'
```

The command exited successfully and returned these material fields:

```json
{
  "deployment_branch_policy": null,
  "id": 19146851160,
  "name": "npm",
  "protection_rules": [
    {
      "prevent_self_review": false,
      "reviewers": [
        {
          "id": 260272870,
          "login": "brownjuly2003-code",
          "type": "User"
        }
      ],
      "type": "required_reviewers"
    }
  ]
}
```

| Requirement | Observed state | Result |
|---|---|---|
| Workflow/Environment name binding | workflow and API both use exact name `npm` | PASS |
| Approval protection | one `required_reviewers` rule | PASS |
| Human reviewer | non-empty User reviewer list | PASS |
| Reviewer identity | `brownjuly2003-code` / `260272870` | PASS |

`prevent_self_review: false` means this is not a four-eyes or reviewer-
independence claim. `deployment_branch_policy: null` means the Environment
adds no branch policy; the workflow retains its own tag/version checks. No
workflow, deployment, release, or npm publish was triggered by this audit.

## Historical transition

The read-only audit on `2026-08-01T16:51:29Z` correctly reported
**`BLOCKED_ENVIRONMENT_ABSENT`** at that time. Its immutable historical record
is [npm-environment-approval-blocker-2026-08-01.md](npm-environment-approval-blocker-2026-08-01.md).
The current successful GET supersedes that blocker for present-state claims.

## Mutation boundary

This verification performed one GitHub GET only. It made no GitHub, workflow,
release, registry, runtime, or local tracked-file mutation before this report
was written; credentials and token values were neither read nor printed.
