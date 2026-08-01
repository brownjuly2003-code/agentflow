# GitHub Environment `npm` approval-protection blocker (2026-08-01)

**Date / audit timestamp:** `2026-08-01T16:51:29Z`<br>
**Result / verdict:** **`BLOCKED_ENVIRONMENT_ABSENT`**<br>
**Gate status:** open — cannot close; no non-empty required-reviewers rule exists for a nonexistent Environment<br>
**Repository:** public `brownjuly2003-code/agentflow`<br>
**Authenticated principal:** repository admin permission<br>
**Local HEAD before this documentation:**
`4b64fc04e23c5d22aea7d2120ab955d07539f65a` (local-only, unpushed, ahead 8;
**not** a runtime or Operator-accepted SHA). Runtime source / `origin/main`
remains `ed03fc47fa5f411016e588774d61a5b5eef21213`.<br>
**Audit mode:** read-only external-state (GET only)<br>
**Task control artifact (local only):**
`.codex-grok-tasks/npm-environment-approval-20260801/preflight-result.md`<br>


## Claim boundary

This note records a **completed read-only GitHub API audit** of Environment
`npm` approval-protection evidence.

It is **not** approval-protection PASS, **not** npm publish acceptance, and
**not** production acceptance. Workflow wiring alone is not approval-protection
evidence. A historical successful publish workflow run does not prove current
approval protection.

Repository-side `pending_acceptance` is **unchanged**:

1. `checkpoint restore and replay acceptance`
2. `4h soak and rollback rehearsal on the golden topology`

Exactly four production-acceptance gates remain overall (restore/replay,
fresh 4h soak+rollback, external pentest, npm approval). Product status
remains **`candidate`**. No score raised. No tracked code/product/workflow
change. No push. Zero GitHub, runtime, secret, deployment, release, tag, or
other external mutation during the audit.

## Local workflow contract (unchanged; correct repository-side wiring)

Source: `.github/workflows/publish-npm.yml` at the local HEAD above.

| Element | Observed |
| --- | --- |
| Workflow | `Publish TypeScript SDK` |
| Job environment binding | **`environment: npm`** |
| Tag / version safeguards | requires release tag; version must match `sdk/pyproject.toml` and `sdk-ts/package.json`; manual dispatch must match tag |
| RC path | `npm publish --dry-run` only (no registry upload) |
| Production path | `npm publish --access public` when not RC |
| Permissions | `contents: read`, `id-token: write` (OIDC trusted publishing) |

The binding is correct repository-side wiring. It still does **not** prove that
GitHub hosts Environment `npm` with a non-empty human required-reviewers rule.

## GitHub API facts (GET only)

| Request | HTTP / outcome |
| --- | --- |
| `GET /repos/brownjuly2003-code/agentflow/environments` | **200** — exactly four names: `github-pages`, `production`, `pypi`, `staging` |
| `GET /repos/brownjuly2003-code/agentflow/environments/npm` | **404 Not Found** |

- **`npm` was absent** from the environments list (`total_count: 4`).
- Because the list request succeeded and the authenticated principal had admin
  permission on a public repository, this is **not** a material auth/visibility
  ambiguity: the Environment does not exist.
- Sibling note (not substitute evidence): `pypi` exists with empty
  `protection_rules`; `production` has a `required_reviewers` rule. Neither
  substitutes for Environment `npm`.
- Recent `publish-npm.yml` runs exist (including historical success on tag
  `v2.0.0`). Successful historical runs do **not** prove current approval
  protection when Environment `npm` is absent today.

## Verdict

### `BLOCKED_ENVIRONMENT_ABSENT`

| Question | Answer |
| --- | --- |
| Can the gate “GitHub Environment `npm` approval-protection evidence” close now? | **No** |
| Is `environment: npm` wired in the workflow? | **Yes** |
| Does GitHub currently host Environment `npm`? | **No** (list omits it; detail **404**) |
| Non-empty human required-reviewers rule for `npm`? | **No** — cannot exist without the Environment |
| Auth/permission uncertainty? | **None material** — admin; list API **200** |
| Product status change? | **None** — remains **`candidate`** |

## Smallest owner action (do not perform from documentation work)

1. In repository **Settings → Environments**, create an Environment named
   exactly **`npm`** (must match workflow `environment: npm`).
2. Configure a **non-empty Required reviewers** rule (at least one human
   reviewer). Optionally prevent self-review and/or constrain deployment
   branch/tags; the gate minimum is a non-empty reviewer rule.
3. Re-run a read-only GET audit: `GET …/environments/npm` must return **200**
   with a `protection_rules` entry of type `required_reviewers` and a non-empty
   reviewers list.

Until step 3 succeeds, treat the gate as **open**.

## Mutation confirmation

| Surface | Mutations |
| --- | --- |
| GitHub Environments / protection rules / reviewers / branch policies | **zero** |
| Secrets, variables, deployments, workflow runs, releases, tags | **zero** |
| Issues / PRs / comments | **zero** |
| Local git (stage/commit/push/fetch/checkout/reset) | **zero** (this note is documentation only) |
| Runtime (Docker, Colima, SSH, K8s, Helm, Kafka, service APIs) | **zero** |
| Workflow / claims / product code | **zero** |

## Next independent safe audit item

Read-only consolidation of the external pentest intake/evidence state
(`docs/operations/third-party-pen-test-intake.md` and related security surfaces).
Do **not** claim a pentest was performed. Do **not** treat this npm audit as
approval-protection PASS.
