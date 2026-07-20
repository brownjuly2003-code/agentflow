output "role_arn" {
  description = "ARN of the GitHub Actions Terraform IAM role"
  value       = aws_iam_role.github_actions.arn
}

output "provider_arn" {
  description = "ARN of the GitHub Actions OIDC provider"
  value       = aws_iam_openid_connect_provider.github_actions.arn
}

output "permissions_boundary_arn" {
  description = "ARN of the permissions boundary required on project service roles"
  value       = aws_iam_policy.permissions_boundary.arn
}
