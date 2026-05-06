# AWS OIDC setup for Terraform apply

## Purpose

This guide bootstraps the AWS IAM OIDC provider and the GitHub Actions role used by `.github/workflows/terraform-apply.yml`.

## Current readiness handoff

Status as of 2026-05-06: blocked on external AWS account inputs.

Confirmed local/repository evidence:

- Repository variable `AWS_REGION` exists and is set to `us-east-1`.
- Repository variable `AWS_TERRAFORM_ROLE_ARN` is not configured.
- `.github/workflows/terraform-apply.yml` remains disabled with `if: false`.
- Real `infrastructure/terraform/environments/staging.tfvars` and `prod.tfvars` files are absent.
- No AWS credentials are configured on the verification workstation.
- Terraform config sanity has passed through `hashicorp/terraform:1.13.5` with `init -backend=false` and `validate`; this is not evidence of a real apply.
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
GitHub Actions API reports `total_count: 0` for `Terraform Apply` workflow runs,
so there is no apply/preflight run or CloudTrail evidence to cite.

The tracked root-level `infrastructure/terraform/dev.tfvars` and
`infrastructure/terraform/prod.tfvars` are not proof of H4 readiness. The
current workflow resolves only `environments/staging.tfvars` and
`environments/prod.tfvars`, and the root files still contain placeholder-shaped
VPC, subnet, and SNS values. Treat them as local scaffold inputs, not as an
owner-approved apply packet.

Local readiness update on 2026-05-06 added a no-apply preflight. It improves
evidence intake but does not close H4 because no AWS role ARN, real tfvars,
CloudTrail `AssumeRoleWithWebIdentity` proof, owner approval, or successful
apply evidence was supplied.

Next operator packet to unblock review:

- Secure ticket or evidence folder with AWS account owner and bootstrap
  operator.
- Non-secret `AWS_TERRAFORM_ROLE_ARN` value and repo-variable proof.
- Secure staging/prod tfvars ownership record; do not commit tfvars.
- Explicit approval to remove the workflow-level `if: false` guard.
- First apply environment, reviewer, rollback owner, run URL or transcript, and
  redacted CloudTrail `AssumeRoleWithWebIdentity` proof.

Do not enable the workflow or run a real Terraform apply until an operator
provides all external inputs:

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
- Terraform CLI or an equivalent container image available on the bootstrap machine.

## Bootstrap the role

1. Start from a trusted local machine with temporary administrator credentials in AWS.
2. Change into `infrastructure/terraform`.
3. Copy `environments/staging.tfvars.example` to `environments/staging.tfvars` for the first non-production proof run.
4. Replace the placeholder VPC, subnet, and SNS values with real values for your AWS account.
5. Run:

```bash
terraform init
terraform plan -var-file=environments/staging.tfvars
terraform apply -var-file=environments/staging.tfvars
```

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
validation.

1. Open the `Terraform Apply` workflow and confirm the run includes `aws-actions/configure-aws-credentials@v4`.
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
4. Run `terraform plan` and apply the change with trusted credentials.

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
