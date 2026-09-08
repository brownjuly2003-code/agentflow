# AWS OIDC setup for Terraform apply

This page owns the optional bootstrap of the AWS IAM OIDC provider and the
GitHub Actions role used by `.github/workflows/terraform-apply.yml`, plus
the GitHub variable, environment, and CloudTrail checks that follow a first
local apply. Read it when the repository owner and AWS account owner are
performing that bootstrap. It does not inventory other operations
procedures — those live in [README.md](README.md) — and it does not report
measured engineering status, which lives in [STATUS.md](../STATUS.md).

**Audience:** repository owner / AWS account owner performing the optional OIDC bootstrap

**Prerequisites:** AWS administrator credentials for the initial bootstrap only, the existing S3 backend bucket `agentflow-terraform-state` and DynamoDB lock table `agentflow-terraform-locks`, GitHub repository admin access, and Terraform CLI 1.15.4 or an equivalent container image of that version; see [Prerequisites](#prerequisites)

## Purpose

This archived optional guide bootstraps the AWS IAM OIDC provider and the GitHub Actions role used by `.github/workflows/terraform-apply.yml` if AWS is ever explicitly reintroduced.

The workflow's `plan` job writes its binary plan to ignored `.artifacts/terraform/tfplan` and uploads it as `terraform-plan-<environment>`; the `apply` job downloads the same path. That file is a replaceable per-run working copy that embeds resolved variable values: never write it next to the configuration or commit it, and do not treat it as reviewed evidence, OIDC/apply evidence, or production acceptance.

Current project decision as of 2026-05-30: a managed-AWS / Terraform-apply production deployment is out of scope for this pre-production portfolio project — a deliberate non-goal, with the stack validated end-to-end on a local/kind demo instead. Do not treat missing AWS apply evidence as a project deficiency, active blocker, or autonomous follow-up. Reopen this path only if the operator explicitly provides an AWS account and approval to reintroduce it.

For the DV2 demo, use the already documented S3-compatible cold-tier path with HF Datasets or Backblaze B2 for derived/anonymized parquet. Do not require AWS/S3 for that dataset.

## Current readiness handoff

Status: not applicable for the current plan — a managed-AWS production deployment is a deliberate non-goal for this pre-production portfolio project. The older AWS evidence below is retained only as historical context.

Confirmed local/repository evidence:

- Repository variable `AWS_REGION` exists and is set to `us-east-1`.
- Repository variable `AWS_TERRAFORM_ROLE_ARN` is not configured.
- `.github/workflows/terraform-apply.yml` remains disabled with `if: false`.
- Real `infrastructure/terraform/environments/staging.tfvars` and `prod.tfvars` files are absent.
- No AWS credentials are configured on the verification workstation.
- The `hashicorp/terraform:1.13.5` container evidence for config sanity
  (`init -backend=false` and `validate`) is superseded by the
  `required_version = "~> 1.15.4"` pin and can no longer be reproduced:
  `terraform init` on 1.13.5 evaluates the constraint and fails with
  `Unsupported Terraform Core version`. Config sanity was re-verified on 2026-09-05 with a local
  Terraform CLI 1.15.4 running `terraform init -backend=false` and
  `terraform validate` from `infrastructure/terraform` (both succeeded;
  `validate` reported `Success! The configuration is valid.`). This is
  still not evidence of a real apply, and a container-image run at
  `hashicorp/terraform:1.15.4` has not been performed.
- `.github/workflows/terraform-apply.yml` includes a manual `PREFLIGHT`
  path that validates required variables, real tfvars presence, and
  `terraform init -backend=false` / `terraform validate` without running
  `apply`.

Access triage on 2026-05-04 confirmed the blocker is still external: GitHub CLI
is authenticated for repository inspection, but AWS CLI and Terraform CLI are
not available in `PATH`; `gh variable list` still reports only `AWS_REGION`;
the workflow still has both Terraform jobs guarded with `if: false`; and only
example tfvars files exist locally. No AWS account bootstrap, role ARN, real
tfvars, CloudTrail OIDC proof, first apply run, reviewer, or rollback owner was
available to record.

Evidence recheck on 2026-05-06 confirmed the same blocker on the pushed `main`
HEAD `ca5ba1d44c35bc27bc561b64f5e0c5c706415756`: repository variables contain
`AWS_REGION=us-east-1` only; `AWS_TERRAFORM_ROLE_ARN` is absent; GitHub
environments `staging` and `production` have required reviewers but no
environment-level variables or secrets; this workstation has no AWS credential
environment hints, AWS config, or AWS credentials file; `aws`, `terraform`, and
`tofu` are not installed in `PATH`; real
`infrastructure/terraform/environments/staging.tfvars` and
`infrastructure/terraform/environments/prod.tfvars` remain absent; and the
GitHub Actions API reports `total_count: 0` for runs of the Terraform workflow
(`terraform-apply.yml`, now named `Terraform (streaming-infrastructure-reference)`),
so there is no apply/preflight run or CloudTrail evidence to cite.

Historical evidence recheck on 2026-05-30 kept the blocker external. Repository variables
still contain only `AWS_REGION=us-east-1`; `AWS_TERRAFORM_ROLE_ARN` is absent;
`terraform` is now available in `PATH`, but AWS CLI and AWS credential
environment hints are absent; workflow-expected
`infrastructure/terraform/environments/*.tfvars` files remain absent; both
Terraform plan/apply jobs remain guarded with `if: false`; and `gh run list
--workflow terraform-apply.yml` reports no workflow runs. Local Terraform CLI
availability is not AWS role, tfvars, CloudTrail, approval, or apply evidence.
Under the current out-of-scope decision this is expected and should not be
rechecked without an explicit decision to reintroduce AWS.

The tracked root-level `infrastructure/terraform/dev.tfvars` is not proof of
H4 readiness: it is the local sandbox scaffold with placeholder-shaped VPC,
subnet, and SNS values. The root `prod.tfvars` was removed (audit P2-4) —
production inputs exist only as the operator-provided
`environments/prod.tfvars` (never committed; template in
`environments/prod.tfvars.example`), which is what both the workflow and
`make deploy-prod` resolve.

Local readiness update on 2026-05-06 added a no-apply preflight. It improves
evidence intake but does not close H4 because no AWS role ARN, real tfvars,
CloudTrail `AssumeRoleWithWebIdentity` proof, owner approval, or successful
apply evidence was supplied.

If AWS is explicitly reintroduced later, the operator packet to unblock review is:

- Secure ticket or evidence folder with AWS account owner and bootstrap
  operator.
- Non-secret `AWS_TERRAFORM_ROLE_ARN` value and repo-variable proof.
- Secure staging/prod tfvars ownership record; do not commit tfvars.
- Explicit approval to remove the workflow-level `if: false` guard.
- First apply environment, reviewer, rollback owner, run URL or transcript, and
  redacted CloudTrail `AssumeRoleWithWebIdentity` proof.

Do not enable the workflow or run a real Terraform apply unless the operator
first reopens AWS with an account and approval and then provides all
external inputs:

- AWS account owner and bootstrap operator.
- Approved IAM role creation path for GitHub Actions OIDC.
- Resulting `AWS_TERRAFORM_ROLE_ARN`.
- Real staging and production tfvars supplied through the approved secure process.
- Explicit approval to remove the workflow-level `if: false` guard.
- First apply environment, reviewer, rollback owner, and evidence location.

If any item above is missing, keep the release readiness state blocked and hand
the missing input list back to the operator.

## Prerequisites

- AWS account with administrator credentials available for the initial bootstrap only.
- Existing S3 backend bucket `agentflow-terraform-state` and DynamoDB lock table `agentflow-terraform-locks`.
- GitHub repository admin access for repository variables and environment protection rules.
- Terraform CLI 1.15.4 (the floor of `required_version` in `infrastructure/terraform/main.tf` and the exact version the `hashicorp/setup-terraform` pins in `.github/workflows/terraform-apply.yml` and `.github/workflows/ci.yml` install), or an equivalent container image of that version, available on the bootstrap machine. `~> 1.15.4` also admits later 1.15 patch releases; 1.16 and newer are refused.

## State locking

The tracked S3 backend keeps `dynamodb_table = "agentflow-terraform-locks"`
on purpose, together with the `TerraformStateLockTableDescribe` /
`TerraformStateLockItems` statements and the `dynamodb:LeadingKeys`
condition in `infrastructure/terraform/modules/github-oidc/main.tf`. The
parameter is deprecated as of Terraform 1.15.4 and `terraform init` emits
`Warning: Deprecated Parameter`. The replacement is S3 native locking
(`use_lockfile = true`). Migration is deferred because it changes the
locking mechanism of a live backend and needs AWS access plus a
lock-migration step. Revisit on the next Terraform major bump, or the first
time the backend is recreated from scratch — whichever comes first.

### Migration to S3 native locking (planned, not executed)

The trigger above says *when*; this says *what to run*, so the person who hits
that day is not designing the migration under time pressure. Nothing here has
been executed: there is no AWS access on the development hosts, and `plan` /
`apply` in `.github/workflows/terraform-apply.yml` remain `if: false`.

**Before starting**

- Every client that runs `terraform init` against `env/staging` or
  `env/production` must be on a Terraform that supports `use_lockfile` (1.10 or
  newer). `required_version = "~> 1.15.4"` holds every client to the 1.15
  patch line, and the `hashicorp/setup-terraform` pins hold CI to exactly
  1.15.4; an operator's local CLI may be any 1.15.x at or above that.
- No `plan` or `apply` may be in flight. The dual-lock phase below exists so
  that migrated and unmigrated clients still block each other; starting it
  mid-run defeats that.
- **No IAM change is needed to begin.** `TerraformStateObject` already allows
  `s3:GetObject`, `s3:PutObject` and `s3:DeleteObject` on `env/<environment>/*`
  (`state_prefix_arns` in
  [`infrastructure/terraform/modules/github-oidc/main.tf`](../../infrastructure/terraform/modules/github-oidc/main.tf)),
  and the native lock is the object
  `env/<environment>/terraform.tfstate.tflock` under exactly that prefix.

**Steps**

1. **Take both locks.** Add `use_lockfile = true` to the `backend "s3"` block in
   `infrastructure/terraform/main.tf`, *keeping* `dynamodb_table`, then run
   `terraform init -reconfigure` from `infrastructure/terraform/`. Terraform
   acquires the DynamoDB item and the `.tflock` object, so a client still on the
   old configuration cannot run concurrently with a migrated one.
2. **Observe both mechanisms once.** With AWS access, run `terraform plan` and
   confirm the `.tflock` object exists under the state key for the duration of
   the run and is gone afterwards, and that the DynamoDB item is still written.
   Record it as dated evidence: this is the only step that proves native locking
   works on this backend rather than in the documentation.
3. **Drop DynamoDB from the backend** once every client has completed step 1:
   remove `dynamodb_table` and run `terraform init -reconfigure` again.
4. **Remove the IAM grants, then the table.** Delete the
   `TerraformStateLockTableDescribe` and `TerraformStateLockItems` statements
   with the `state_table_arn` and `state_lock_ids` locals, apply, and only then
   delete the `agentflow-terraform-locks` table. Deleting the table first leaves
   a role granting DynamoDB access to nothing and hides the mistake.
5. **Update the record.** This section, the same section in
   [`infrastructure/terraform/modules/github-oidc/README.md`](../../infrastructure/terraform/modules/github-oidc/README.md),
   and `ASSUMPTION-T-36-BACKEND` below all describe DynamoDB retention as
   deliberate. They stop being true at step 3 and must change in that commit.

**Rollback.** Before step 3, remove `use_lockfile` and re-run `terraform init
-reconfigure`; a leftover `.tflock` object is removed with `aws s3 rm`. After
step 3 the reverse of step 1 restores DynamoDB locking — but only while the
table still exists, which is why step 4 deletes it last.

Remaining assumptions (same class as the apply-guard retention: the tracked
contract is honest, the live delivery path is not claimed):

- **ASSUMPTION-T-36-BACKEND**: this page does not claim that `terraform init`,
  `plan`, or `apply` ran against the real S3 backend. DynamoDB locking is
  retained on the tracked configuration; a live-backend migration to
  `use_lockfile` still needs AWS access.
- **ASSUMPTION-T-36-CI-LOCK** — discharged 2026-09-08. The provider-lock
  step in `.github/workflows/ci.yml` `terraform-validate` runs
  `terraform providers lock -platform=linux_amd64 -platform=darwin_arm64
  -platform=windows_amd64` followed by `git diff --exit-code
  .terraform.lock.hcl`. It was a tracked guard with no runner behind it until
  the work reached `origin`; it has since passed on `ubuntu-latest` (run
  34213482386, `terraform-validate` success, step "Provider lock covers
  linux_amd64"), which is the evidence that the tracked lock covers the
  platform CI actually runs on. What remains unobserved is only the
  `darwin_arm64` / `windows_amd64` halves being *used*, as opposed to being
  regenerated identically — CI has no runner on either.

## State-key and role scope

The GitHub Actions role's S3 object read/write is limited to `env/staging/*`
and `env/production/*`. Those names are exactly the `workflow_dispatch`
`environment` options in `.github/workflows/terraform-apply.yml`.
`env/dev/*` is used only by `make deploy-dev` with an operator's own
credentials; those objects are not readable or writable by the CI role.
`s3:ListBucket` is bucket-wide, so the role can see other environments'
state key names, sizes and timestamps. Narrowing `s3:ListBucket` with an
`s3:prefix` condition is a follow-up that needs verification against a
real backend init.

### Shared CI role and account-global OIDC provider

No bootstrap apply has been performed, so no role exists yet and
`AWS_TERRAFORM_ROLE_ARN` is unset — see [Current readiness handoff](#current-readiness-handoff).
The scope below is what the tracked configuration would produce.

The workflow reads exactly one `AWS_TERRAFORM_ROLE_ARN` repository variable
for both `workflow_dispatch` environments, so a single role serves both.
Because that role is shared, it holds `s3:PutObject`/`s3:DeleteObject` on
every environment listed in `state_environments`, so the per-environment
state keys separate *state objects*, not *credentials*. A per-environment
role would need a per-environment role variable in the workflow, which this
repository does not have.

`aws_iam_openid_connect_provider.github_actions` is account-global and is
owned by the state the bootstrap was run from
(`env/staging/terraform.tfstate`). A second environment applied from an
empty state would fail with `EntityAlreadyExists`; that state must first
import the existing provider. `terraform import` loads the configuration, so
it needs both the production backend key and the root variables
(`environment`, `vpc_id` and `private_subnet_ids` have no defaults):

```bash
terraform init -reconfigure -backend-config="key=env/production/terraform.tfstate"
terraform import -var-file=environments/prod.tfvars \
  module.github_oidc.aws_iam_openid_connect_provider.github_actions \
  arn:aws:iam::<account-id>:oidc-provider/token.actions.githubusercontent.com
```

Run this from a working directory inited against the **production** key. An
operator who has just followed [Bootstrap the role](#bootstrap-the-role) is
inited against `env/staging/terraform.tfstate`, where the provider is already
managed; importing there does nothing useful.

After this import both states own the same account-global provider: a
`terraform destroy` or removal from either state deletes the trust
anchor for both, and a thumbprint change applied from one state leaves
the other drifted. Rotate the thumbprint from the staging state only.
The import covers only `aws_iam_openid_connect_provider`. A production
apply also creates `agentflow-terraform-production` plus its own
`-boundary` policy, and `AWS_TERRAFORM_ROLE_ARN` must continue to name
the single role the workflows use — the operator decides which of the two ARNs that variable keeps.

These are facts about the current repository, not a recommended design.

## Bootstrap the role

1. Start from a trusted local machine with temporary administrator credentials in AWS.
2. Change into `infrastructure/terraform`.
3. Copy `environments/staging.tfvars.example` to `environments/staging.tfvars` for the first non-production proof run.
4. Replace the placeholder VPC, subnet, and SNS values with real values for your AWS account.
5. Run:

```bash
terraform init -backend-config="key=env/staging/terraform.tfstate"
terraform plan -var-file=environments/staging.tfvars
terraform apply -var-file=environments/staging.tfvars
```

The OIDC provider is account-global and lives in this staging state. A later
apply against `env/production/terraform.tfstate` from an empty state must
import it first (see [Shared CI role and account-global OIDC provider](#shared-ci-role-and-account-global-oidc-provider)) or it will fail with `EntityAlreadyExists`.

6. Capture the resulting role ARN from `terraform state show module.github_oidc.aws_iam_role.github_actions`.

The first apply must be local because the role does not exist yet. After the role exists, GitHub Actions can assume it through OIDC.

## Configure GitHub

1. Open `Settings -> Secrets and variables -> Actions -> Variables`.
2. Create `AWS_TERRAFORM_ROLE_ARN` with the ARN output from Terraform.
3. Create `AWS_REGION` with the same region used by Terraform, for example `us-east-1`.
4. Remove legacy long-lived credentials such as `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `TF_AWS_ROLE` if they exist.
5. Open `Settings -> Environments` and create `staging` and `production`.
6. Add required reviewers to both environments before allowing apply runs.

The workflow maps the GitHub `production` environment to `environments/prod.tfvars` and the `staging` environment to `environments/staging.tfvars`.

## Verify OIDC is active

Before enabling the disabled plan/apply jobs, an operator can run the manual
workflow with `confirm=PREFLIGHT`. That path does not call `terraform apply`;
it only checks repository variables, real tfvars presence, and Terraform local
validation. Steps 1, 2 and 4 are static inspections of the tracked workflow
file and hold today. Step 3 needs a real federated run, so it can only be
satisfied once the `if: false` guards on `plan`/`apply` are lifted.

1. In `terraform-apply.yml`, confirm the `plan` and `apply` jobs use the SHA-pinned `aws-actions/configure-aws-credentials` (`e6de054…` / v6.2.3).
2. Confirm the workflow uses repository variables `AWS_TERRAFORM_ROLE_ARN` and `AWS_REGION`, not AWS access key secrets.
3. Inspect the AWS CloudTrail event for `AssumeRoleWithWebIdentity` and confirm the federated principal is `token.actions.githubusercontent.com`.
4. Confirm the job has `permissions.id-token: write`.

If a run succeeds without `AWS_ACCESS_KEY_ID` and CloudTrail shows `AssumeRoleWithWebIdentity`, the workflow is using OIDC.

## Thumbprint rotation

The checked-in thumbprint as of 2026-04-22 is:

```text
dd55b4520291e276588f0dd02fafd83a7368e0fa
```

To refresh it:

1. Follow the AWS IAM procedure for obtaining the top intermediate CA thumbprint for an OIDC provider.
2. Re-check the certificate chain for `token.actions.githubusercontent.com`.
3. Update `infrastructure/terraform/modules/github-oidc/main.tf`.
4. Run `terraform plan` and apply the change with trusted credentials from
   the staging state (`env/staging/terraform.tfstate`) only. After a
   production import both states own the same account-global provider:
   applying the thumbprint change from one state leaves the other drifted
   on `thumbprint_list`, and a `terraform destroy` or removal from either
   state deletes the trust anchor for both.

Example PowerShell check used for this repository:

```powershell
$tcp = [System.Net.Sockets.TcpClient]::new('token.actions.githubusercontent.com', 443)
try {
  $ssl = [System.Net.Security.SslStream]::new($tcp.GetStream(), $false, ({ $true }))
  $ssl.AuthenticateAsClient('token.actions.githubusercontent.com')
  $cert = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new($ssl.RemoteCertificate)
  $chain = [System.Security.Cryptography.X509Certificates.X509Chain]::new()
  $chain.ChainPolicy.RevocationMode = [System.Security.Cryptography.X509Certificates.X509RevocationMode]::NoCheck
  $null = $chain.Build($cert)
  $chain.ChainElements | Select-Object Subject, Thumbprint
}
finally {
  if ($ssl) { $ssl.Dispose() }
  $tcp.Dispose()
}
```
