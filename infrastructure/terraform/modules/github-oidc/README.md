# github-oidc

Terraform module that provisions the AWS IAM OIDC provider for GitHub Actions and an IAM role for `terraform plan/apply` runs.

## Inputs

| Name | Description | Type |
| --- | --- | --- |
| `github_org` | GitHub organization or user that owns the repository | `string` |
| `github_repo` | Repository name allowed to assume the role | `string` |
| `role_name` | IAM role name for GitHub Actions Terraform runs | `string` |
| `allowed_branches` | Branch refs allowed in the OIDC `sub` claim | `list(string)` |
| `allowed_environments` | GitHub environments allowed in the OIDC `sub` claim | `list(string)` |

## Outputs

| Name | Description |
| --- | --- |
| `role_arn` | ARN of the IAM role used by GitHub Actions |
| `provider_arn` | ARN of the IAM OIDC provider |

## Bootstrap

1. Run the first apply locally with temporary admin credentials so Terraform can create the OIDC provider and IAM role.
2. Retrieve the role ARN from `terraform state show module.github_oidc.aws_iam_role.github_actions` and save it into the GitHub repository variable `AWS_TERRAFORM_ROLE_ARN`.
3. Save the deployment region into the repository variable `AWS_REGION`.
4. Configure GitHub environments `staging` and `production` with required reviewers before enabling `terraform-apply.yml`.

## Notes

- The trust policy is locked to `refs/heads/main` plus the `staging` and `production` GitHub environments.
- The inline policy is intentionally action-scoped instead of using broad admin policies. Some AWS APIs still require `Resource = "*"` for create/list operations.
- The checked-in thumbprint is `dd55b4520291e276588f0dd02fafd83a7368e0fa`, observed for `token.actions.githubusercontent.com` on 2026-04-22. Rotate it if the top intermediate CA changes.
