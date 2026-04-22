module "github_oidc" {
  source = "./modules/github-oidc"

  github_org           = var.github_org
  github_repo          = var.github_repo
  role_name            = "agentflow-terraform-${var.environment}"
  allowed_branches     = ["main"]
  allowed_environments = ["production", "staging"]
}
