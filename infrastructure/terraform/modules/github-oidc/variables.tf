variable "github_org" {
  description = "GitHub organization or user that owns the repository"
  type        = string

  validation {
    condition     = trimspace(var.github_org) != ""
    error_message = "github_org must not be empty."
  }
}

variable "github_repo" {
  description = "GitHub repository name allowed to assume the role"
  type        = string

  validation {
    condition     = trimspace(var.github_repo) != ""
    error_message = "github_repo must not be empty."
  }
}

variable "role_name" {
  description = "IAM role name for GitHub Actions Terraform runs"
  type        = string

  validation {
    condition     = trimspace(var.role_name) != ""
    error_message = "role_name must not be empty."
  }
}

variable "allowed_branches" {
  description = "Git refs allowed to assume the IAM role"
  type        = list(string)

  validation {
    condition     = length(var.allowed_branches) > 0
    error_message = "allowed_branches must contain at least one branch."
  }
}

variable "allowed_environments" {
  description = "GitHub environments allowed to assume the IAM role"
  type        = list(string)

  validation {
    condition     = length(var.allowed_environments) > 0
    error_message = "allowed_environments must contain at least one environment."
  }
}

variable "state_environments" {
  description = "Environment names whose env/<name> Terraform state keys the role may access"
  type        = list(string)

  validation {
    condition = (
      length(var.state_environments) > 0 &&
      length(distinct(var.state_environments)) == length(var.state_environments) &&
      alltrue([for environment in var.state_environments : trimspace(environment) != ""]) &&
      alltrue([for environment in var.state_environments : can(regex("^[a-z0-9][a-z0-9-]*$", environment))])
    )
    error_message = "state_environments must contain unique, non-empty names matching ^[a-z0-9][a-z0-9-]*$ (no slashes or parent-path segments)."
  }
}
