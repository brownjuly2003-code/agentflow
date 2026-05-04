# AWS OIDC setup for Terraform apply

## Purpose

This guide bootstraps the AWS IAM OIDC provider and the GitHub Actions role used by `.github/workflows/terraform-apply.yml`.

## Current readiness handoff

Status as of 2026-05-04: blocked on external AWS account inputs.

Confirmed local/repository evidence:

- Repository variable `AWS_REGION` exists and is set to `us-east-1`.
- Repository variable `AWS_TERRAFORM_ROLE_ARN` is not configured.
- `.github/workflows/terraform-apply.yml` remains disabled with `if: false`.
- Real `infrastructure/terraform/environments/staging.tfvars` and `prod.tfvars` files are absent.
- No AWS credentials are configured on the verification workstation.
- Terraform config sanity has passed through `hashicorp/terraform:1.13.5` with `init -backend=false` and `validate`; this is not evidence of a real apply.

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
