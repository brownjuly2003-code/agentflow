data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

data "aws_region" "current" {}

locals {
  oidc_url             = "https://token.actions.githubusercontent.com"
  oidc_provider_host   = "token.actions.githubusercontent.com"
  oidc_thumbprint      = "dd55b4520291e276588f0dd02fafd83a7368e0fa"
  project_prefix       = replace(var.role_name, "/-terraform-.*/", "")
  branch_subjects      = [for branch in var.allowed_branches : "repo:${var.github_org}/${var.github_repo}:ref:refs/heads/${branch}"]
  environment_subjects = [for environment in var.allowed_environments : "repo:${var.github_org}/${var.github_repo}:environment:${environment}"]
  allowed_subjects     = concat(local.branch_subjects, local.environment_subjects)
  lake_bucket_arn      = "arn:${data.aws_partition.current.partition}:s3:::${local.project_prefix}-lake-*"
  state_bucket_arn     = "arn:${data.aws_partition.current.partition}:s3:::agentflow-terraform-state"
  state_object_arn     = "${local.state_bucket_arn}/infrastructure/terraform.tfstate"
  state_prefix_arn     = "${local.state_bucket_arn}/infrastructure/*"
  state_table_arn      = "arn:${data.aws_partition.current.partition}:dynamodb:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:table/agentflow-terraform-locks"
  oidc_provider_arn    = "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/${local.oidc_provider_host}"
  terraform_role_arn   = "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:role/${local.project_prefix}-terraform-*"
  service_role_arns = [
    "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:role/${local.project_prefix}-flink-*",
    "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:role/${local.project_prefix}-grafana-*",
  ]
}

data "aws_iam_policy_document" "assume_role" {
  statement {
    sid     = "GitHubActionsAssumeRole"
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github_actions.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_provider_host}:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "${local.oidc_provider_host}:sub"
      values   = local.allowed_subjects
    }
  }
}

data "aws_iam_policy_document" "terraform" {
  statement {
    sid    = "TerraformStateBucket"
    effect = "Allow"
    actions = [
      "s3:GetBucketLocation",
      "s3:GetBucketVersioning",
      "s3:ListBucket",
    ]
    resources = [local.state_bucket_arn]
  }

  statement {
    sid    = "TerraformStateObject"
    effect = "Allow"
    actions = [
      "s3:DeleteObject",
      "s3:GetObject",
      "s3:PutObject",
    ]
    resources = [
      local.state_object_arn,
      local.state_prefix_arn,
    ]
  }

  statement {
    sid    = "TerraformStateLockTable"
    effect = "Allow"
    actions = [
      "dynamodb:DeleteItem",
      "dynamodb:DescribeTable",
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
    ]
    resources = [local.state_table_arn]
  }

  statement {
    sid    = "OidcProviderLifecycle"
    effect = "Allow"
    actions = [
      "iam:CreateOpenIDConnectProvider",
      "iam:ListOpenIDConnectProviders",
      "iam:*OpenIDConnectProvider*",
    ]
    resources = [
      "*",
      local.oidc_provider_arn,
    ]
  }

  statement {
    sid    = "TerraformRoleLifecycle"
    effect = "Allow"
    actions = [
      "iam:AttachRolePolicy",
      "iam:CreateRole",
      "iam:DeleteRole",
      "iam:DetachRolePolicy",
      "iam:GetRole",
      "iam:GetRolePolicy",
      "iam:ListAttachedRolePolicies",
      "iam:ListRolePolicies",
      "iam:ListRoleTags",
      "iam:PutRolePolicy",
      "iam:TagRole",
      "iam:UntagRole",
      "iam:UpdateAssumeRolePolicy",
      "iam:DeleteRolePolicy",
    ]
    resources = [
      local.terraform_role_arn,
      local.service_role_arns[0],
      local.service_role_arns[1],
    ]
  }

  statement {
    sid       = "PassServiceRoles"
    effect    = "Allow"
    actions   = ["iam:PassRole"]
    resources = local.service_role_arns
  }

  statement {
    sid       = "ServiceLinkedRoles"
    effect    = "Allow"
    actions   = ["iam:CreateServiceLinkedRole"]
    resources = ["*"]

    condition {
      test     = "StringLike"
      variable = "iam:AWSServiceName"
      values = [
        "grafana.amazonaws.com",
        "kafka.amazonaws.com",
        "kinesisanalytics.amazonaws.com",
      ]
    }
  }

  statement {
    sid    = "SecurityGroups"
    effect = "Allow"
    actions = [
      "ec2:AuthorizeSecurityGroupEgress",
      "ec2:AuthorizeSecurityGroupIngress",
      "ec2:CreateSecurityGroup",
      "ec2:CreateTags",
      "ec2:DeleteSecurityGroup",
      "ec2:DeleteTags",
      "ec2:DescribeSecurityGroups",
      "ec2:DescribeSubnets",
      "ec2:DescribeTags",
      "ec2:DescribeVpcs",
      "ec2:GetManagedPrefixListEntries",
      "ec2:RevokeSecurityGroupEgress",
      "ec2:RevokeSecurityGroupIngress",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "MSKClusters"
    effect = "Allow"
    actions = [
      "kafka:*Cluster*",
      "kafka:*Configuration*",
      "kafka:GetBootstrapBrokers",
      "kafka:ListTagsForResource",
      "kafka:TagResource",
      "kafka:UntagResource",
      "kafka:UpdateMonitoring",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "ManagedFlinkApplications"
    effect = "Allow"
    actions = [
      "kinesisanalytics:*Application*",
      "kinesisanalytics:ListApplications",
      "kinesisanalytics:ListTagsForResource",
      "kinesisanalytics:TagResource",
      "kinesisanalytics:UntagResource",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "LakeBucket"
    effect = "Allow"
    actions = [
      "s3:CreateBucket",
      "s3:DeleteBucket",
      "s3:DeleteBucketEncryption",
      "s3:DeleteBucketLifecycle",
      "s3:DeleteBucketPublicAccessBlock",
      "s3:GetBucketLocation",
      "s3:GetBucketPublicAccessBlock",
      "s3:GetBucketTagging",
      "s3:GetBucketVersioning",
      "s3:GetEncryptionConfiguration",
      "s3:GetLifecycleConfiguration",
      "s3:ListBucket",
      "s3:PutBucketPublicAccessBlock",
      "s3:PutBucketTagging",
      "s3:PutBucketVersioning",
      "s3:PutEncryptionConfiguration",
      "s3:PutLifecycleConfiguration",
    ]
    resources = [local.lake_bucket_arn]
  }

  statement {
    sid    = "CloudWatchAlarms"
    effect = "Allow"
    actions = [
      "cloudwatch:DeleteAlarms",
      "cloudwatch:DescribeAlarms",
      "cloudwatch:ListTagsForResource",
      "cloudwatch:PutMetricAlarm",
      "cloudwatch:TagResource",
      "cloudwatch:UntagResource",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "GrafanaWorkspaces"
    effect = "Allow"
    actions = [
      "grafana:CreateWorkspace",
      "grafana:DeleteWorkspace",
      "grafana:DescribeWorkspace",
      "grafana:DescribeWorkspaceAuthentication",
      "grafana:DescribeWorkspaceConfiguration",
      "grafana:ListTagsForResource",
      "grafana:ListVersions",
      "grafana:ListWorkspaces",
      "grafana:TagResource",
      "grafana:UntagResource",
      "grafana:UpdateWorkspace",
      "grafana:UpdateWorkspaceAuthentication",
      "grafana:UpdateWorkspaceConfiguration",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "GrafanaDependencies"
    effect = "Allow"
    actions = [
      "organizations:DescribeOrganization",
      "sso:CreateManagedApplicationInstance",
      "sso:DeleteManagedApplicationInstance",
      "sso:DescribeRegisteredRegions",
      "sso:GetSharedSsoConfiguration",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_openid_connect_provider" "github_actions" {
  url             = local.oidc_url
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [local.oidc_thumbprint]
}

resource "aws_iam_role" "github_actions" {
  name               = var.role_name
  assume_role_policy = data.aws_iam_policy_document.assume_role.json
}

resource "aws_iam_role_policy" "terraform" {
  name   = "${var.role_name}-terraform"
  role   = aws_iam_role.github_actions.id
  policy = data.aws_iam_policy_document.terraform.json
}
