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
  boundary_policy_name = "${var.role_name}-boundary"
  boundary_policy_arn  = "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:policy/${local.boundary_policy_name}"
  region_account       = "${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}"
  msk_cluster_arns     = ["arn:${data.aws_partition.current.partition}:kafka:${local.region_account}:cluster/${local.project_prefix}-*/*"]
  msk_config_arns      = ["arn:${data.aws_partition.current.partition}:kafka:${local.region_account}:configuration/${local.project_prefix}-*/*"]
  flink_app_arns       = ["arn:${data.aws_partition.current.partition}:kinesisanalytics:${local.region_account}:application/${local.project_prefix}-*"]
  alarm_arns           = ["arn:${data.aws_partition.current.partition}:cloudwatch:${local.region_account}:alarm:${local.project_prefix}-*"]
  kms_key_arns         = ["arn:${data.aws_partition.current.partition}:kms:${local.region_account}:key/*"]
  kms_alias_arns       = ["arn:${data.aws_partition.current.partition}:kms:${local.region_account}:alias/${local.project_prefix}-*"]
  project_bucket_arns = [
    "arn:${data.aws_partition.current.partition}:s3:::${local.project_prefix}-*",
    "arn:${data.aws_partition.current.partition}:s3:::${local.project_prefix}-*/*",
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

  # List cannot be resource-scoped; every mutating OIDC-provider verb below is
  # pinned to the one provider this module manages (IaC-3: no wildcard verbs on
  # every provider in the account).
  statement {
    sid       = "OidcProviderDiscovery"
    effect    = "Allow"
    actions   = ["iam:ListOpenIDConnectProviders"]
    resources = ["*"]
  }

  statement {
    sid    = "OidcProviderLifecycle"
    effect = "Allow"
    actions = [
      "iam:AddClientIDToOpenIDConnectProvider",
      "iam:CreateOpenIDConnectProvider",
      "iam:DeleteOpenIDConnectProvider",
      "iam:GetOpenIDConnectProvider",
      "iam:ListOpenIDConnectProviderTags",
      "iam:RemoveClientIDFromOpenIDConnectProvider",
      "iam:TagOpenIDConnectProvider",
      "iam:UntagOpenIDConnectProvider",
      "iam:UpdateOpenIDConnectProviderThumbprint",
    ]
    resources = [local.oidc_provider_arn]
  }

  # IaC-2: the deploy role can refresh its own state (read-only) but can no
  # longer mutate roles matching its own name — writes are limited to the
  # service roles, and creating/re-policying them requires the permissions
  # boundary to be attached. Changes to this role or its inline policy are
  # applied out-of-band by an account admin, not by CI.
  statement {
    sid    = "RoleStateRead"
    effect = "Allow"
    actions = [
      "iam:GetRole",
      "iam:GetRolePolicy",
      "iam:ListAttachedRolePolicies",
      "iam:ListRolePolicies",
      "iam:ListRoleTags",
    ]
    resources = concat([local.terraform_role_arn], local.service_role_arns)
  }

  statement {
    sid       = "ServiceRoleCreate"
    effect    = "Allow"
    actions   = ["iam:CreateRole"]
    resources = local.service_role_arns

    condition {
      test     = "StringEquals"
      variable = "iam:PermissionsBoundary"
      values   = [local.boundary_policy_arn]
    }
  }

  statement {
    sid    = "ServiceRolePolicyMutation"
    effect = "Allow"
    actions = [
      "iam:AttachRolePolicy",
      "iam:DeleteRolePolicy",
      "iam:DetachRolePolicy",
      "iam:PutRolePolicy",
    ]
    resources = local.service_role_arns

    condition {
      test     = "StringEquals"
      variable = "iam:PermissionsBoundary"
      values   = [local.boundary_policy_arn]
    }
  }

  statement {
    sid    = "ServiceRoleLifecycle"
    effect = "Allow"
    actions = [
      "iam:DeleteRole",
      "iam:TagRole",
      "iam:UntagRole",
      "iam:UpdateAssumeRolePolicy",
    ]
    resources = local.service_role_arns
  }

  # Terraform needs to create and refresh the boundary policy, but not to
  # rewrite it: no CreatePolicyVersion/SetDefaultPolicyVersion/DeletePolicy —
  # loosening the ceiling is an out-of-band admin operation.
  statement {
    sid    = "BoundaryPolicyRead"
    effect = "Allow"
    actions = [
      "iam:GetPolicy",
      "iam:GetPolicyVersion",
      "iam:ListPolicyTags",
      "iam:ListPolicyVersions",
    ]
    resources = [local.boundary_policy_arn]
  }

  statement {
    sid    = "BoundaryPolicyCreate"
    effect = "Allow"
    actions = [
      "iam:CreatePolicy",
      "iam:TagPolicy",
      "iam:UntagPolicy",
    ]
    resources = [local.boundary_policy_arn]
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

  # Security-group ids are generated at create time and Describe* is not
  # resource-scopeable, so these stay on "*"; deleting a group is gated on the
  # project tag below.
  #trivy:ignore:AVD-AWS-0057
  statement {
    sid    = "SecurityGroups"
    effect = "Allow"
    actions = [
      "ec2:AuthorizeSecurityGroupEgress",
      "ec2:AuthorizeSecurityGroupIngress",
      "ec2:CreateSecurityGroup",
      "ec2:CreateTags",
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

  #trivy:ignore:AVD-AWS-0057
  statement {
    sid       = "SecurityGroupsDestroy"
    effect    = "Allow"
    actions   = ["ec2:DeleteSecurityGroup"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Project"
      values   = [local.project_prefix]
    }
  }

  # IaC-4: explicit verbs instead of kafka:*Cluster*/kafka:*Configuration*,
  # scoped to this project's cluster/configuration name patterns; cluster
  # deletion additionally requires the project tag.
  #trivy:ignore:AVD-AWS-0057
  statement {
    sid    = "MSKDiscovery"
    effect = "Allow"
    actions = [
      "kafka:DescribeClusterOperation",
      "kafka:DescribeClusterOperationV2",
      "kafka:ListClusters",
      "kafka:ListClustersV2",
      "kafka:ListConfigurations",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "MSKClusterLifecycle"
    effect = "Allow"
    actions = [
      "kafka:CreateCluster",
      "kafka:CreateClusterV2",
      "kafka:DescribeCluster",
      "kafka:DescribeClusterV2",
      "kafka:GetBootstrapBrokers",
      "kafka:ListTagsForResource",
      "kafka:TagResource",
      "kafka:UntagResource",
      "kafka:UpdateBrokerCount",
      "kafka:UpdateBrokerStorage",
      "kafka:UpdateBrokerType",
      "kafka:UpdateClusterConfiguration",
      "kafka:UpdateClusterKafkaVersion",
      "kafka:UpdateConnectivity",
      "kafka:UpdateMonitoring",
      "kafka:UpdateSecurity",
      "kafka:UpdateStorage",
    ]
    resources = local.msk_cluster_arns
  }

  statement {
    sid    = "MSKConfigurationLifecycle"
    effect = "Allow"
    actions = [
      "kafka:CreateConfiguration",
      "kafka:DeleteConfiguration",
      "kafka:DescribeConfiguration",
      "kafka:DescribeConfigurationRevision",
      "kafka:ListConfigurationRevisions",
      "kafka:UpdateConfiguration",
    ]
    resources = local.msk_config_arns
  }

  statement {
    sid       = "MSKDestroy"
    effect    = "Allow"
    actions   = ["kafka:DeleteCluster"]
    resources = local.msk_cluster_arns

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Project"
      values   = [local.project_prefix]
    }
  }

  # IaC-4: explicit verbs instead of kinesisanalytics:*Application*, scoped to
  # this project's application name pattern; deletion requires the project tag.
  #trivy:ignore:AVD-AWS-0057
  statement {
    sid       = "FlinkDiscovery"
    effect    = "Allow"
    actions   = ["kinesisanalytics:ListApplications"]
    resources = ["*"]
  }

  statement {
    sid    = "FlinkApplicationLifecycle"
    effect = "Allow"
    actions = [
      "kinesisanalytics:CreateApplication",
      "kinesisanalytics:DescribeApplication",
      "kinesisanalytics:DescribeApplicationVersion",
      "kinesisanalytics:ListApplicationVersions",
      "kinesisanalytics:ListTagsForResource",
      "kinesisanalytics:StartApplication",
      "kinesisanalytics:StopApplication",
      "kinesisanalytics:TagResource",
      "kinesisanalytics:UntagResource",
      "kinesisanalytics:UpdateApplication",
    ]
    resources = local.flink_app_arns
  }

  statement {
    sid       = "FlinkDestroy"
    effect    = "Allow"
    actions   = ["kinesisanalytics:DeleteApplication"]
    resources = local.flink_app_arns

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Project"
      values   = [local.project_prefix]
    }
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
    resources = local.alarm_arns
  }

  # Workspace ids are generated at create time, so grafana verbs stay on "*";
  # workspace deletion is gated on the project tag below.
  #trivy:ignore:AVD-AWS-0057
  statement {
    sid    = "GrafanaWorkspaces"
    effect = "Allow"
    actions = [
      "grafana:CreateWorkspace",
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

  #trivy:ignore:AVD-AWS-0057
  statement {
    sid       = "GrafanaDestroy"
    effect    = "Allow"
    actions   = ["grafana:DeleteWorkspace"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Project"
      values   = [local.project_prefix]
    }
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

  # Key ids are generated at create time, so key-scoped verbs use key/* within
  # this account and region; alias verbs are pinned to the project prefix and
  # key deletion is gated on the project tag.
  #trivy:ignore:AVD-AWS-0057
  statement {
    sid       = "KMSKeyCreate"
    effect    = "Allow"
    actions   = ["kms:CreateKey"]
    resources = ["*"]
  }

  #trivy:ignore:AVD-AWS-0057
  statement {
    sid    = "KMSKeyLifecycle"
    effect = "Allow"
    actions = [
      "kms:DescribeKey",
      "kms:EnableKeyRotation",
      "kms:GetKeyPolicy",
      "kms:GetKeyRotationStatus",
      "kms:ListResourceTags",
      "kms:TagResource",
      "kms:UntagResource",
    ]
    resources = local.kms_key_arns
  }

  #trivy:ignore:AVD-AWS-0057
  statement {
    sid    = "KMSAliasLifecycle"
    effect = "Allow"
    actions = [
      "kms:CreateAlias",
      "kms:DeleteAlias",
      "kms:UpdateAlias",
    ]
    resources = concat(local.kms_alias_arns, local.kms_key_arns)
  }

  #trivy:ignore:AVD-AWS-0057
  statement {
    sid    = "KMSDestroy"
    effect = "Allow"
    actions = [
      "kms:DisableKey",
      "kms:ScheduleKeyDeletion",
    ]
    resources = local.kms_key_arns

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Project"
      values   = [local.project_prefix]
    }
  }
}

# Permissions boundary shared by the deploy role and the service roles it
# manages (IaC-2). It is a ceiling, not a grant — effective permissions are the
# intersection with each role's identity policy — so per-service wildcards here
# are intentional. The load-bearing part is what iam: allows exclude (no role
# mutation on the deploy role's own name pattern) plus the explicit denies:
# even a compromised deploy role cannot detach the boundary, rewrite it, or
# escalate itself. The two suppressed checks flag the ceiling's s3:* action
# (resource-pinned to project buckets) and PassRole on the service-role name
# patterns — both deliberate here.
#trivy:ignore:AVD-AWS-0342
#trivy:ignore:AVD-AWS-0345
data "aws_iam_policy_document" "permissions_boundary" {
  #trivy:ignore:AVD-AWS-0057
  statement {
    sid    = "ProjectServicesCeiling"
    effect = "Allow"
    actions = [
      "cloudwatch:*",
      "dynamodb:*",
      "ec2:*",
      "grafana:*",
      "kafka-cluster:*",
      "kafka:*",
      "kinesisanalytics:*",
      "kms:*",
      "organizations:DescribeOrganization",
      "sso:*",
    ]
    resources = ["*"]
  }

  # Action wildcard is the point of a ceiling; the resource list is pinned to
  # project-prefixed buckets, so this cannot reach the account's other buckets.
  #trivy:ignore:AVD-AWS-0345
  statement {
    sid       = "ProjectBucketsCeiling"
    effect    = "Allow"
    actions   = ["s3:*"]
    resources = local.project_bucket_arns
  }

  #trivy:ignore:AVD-AWS-0057
  statement {
    sid    = "IamReadCeiling"
    effect = "Allow"
    actions = [
      "iam:Get*",
      "iam:List*",
    ]
    resources = ["*"]
  }

  # PassRole is limited to the project's service-role name patterns; the "*"
  # in them is the environment suffix, not an open wildcard.
  #trivy:ignore:AVD-AWS-0342
  statement {
    sid       = "IamPassRoleCeiling"
    effect    = "Allow"
    actions   = ["iam:PassRole"]
    resources = local.service_role_arns
  }

  #trivy:ignore:AVD-AWS-0057
  statement {
    sid       = "IamServiceLinkedRoleCeiling"
    effect    = "Allow"
    actions   = ["iam:CreateServiceLinkedRole"]
    resources = ["*"]
  }

  statement {
    sid    = "IamServiceRoleMutationCeiling"
    effect = "Allow"
    actions = [
      "iam:AttachRolePolicy",
      "iam:CreateRole",
      "iam:DeleteRole",
      "iam:DeleteRolePolicy",
      "iam:DetachRolePolicy",
      "iam:PutRolePolicy",
      "iam:TagRole",
      "iam:UntagRole",
      "iam:UpdateAssumeRolePolicy",
    ]
    resources = local.service_role_arns
  }

  statement {
    sid    = "IamOidcProviderCeiling"
    effect = "Allow"
    actions = [
      "iam:AddClientIDToOpenIDConnectProvider",
      "iam:CreateOpenIDConnectProvider",
      "iam:DeleteOpenIDConnectProvider",
      "iam:RemoveClientIDFromOpenIDConnectProvider",
      "iam:TagOpenIDConnectProvider",
      "iam:UntagOpenIDConnectProvider",
      "iam:UpdateOpenIDConnectProviderThumbprint",
    ]
    resources = [local.oidc_provider_arn]
  }

  statement {
    sid    = "IamBoundaryPolicyCreateCeiling"
    effect = "Allow"
    actions = [
      "iam:CreatePolicy",
      "iam:TagPolicy",
      "iam:UntagPolicy",
    ]
    resources = [local.boundary_policy_arn]
  }

  statement {
    sid    = "DenyBoundaryDetach"
    effect = "Deny"
    actions = [
      "iam:DeleteRolePermissionsBoundary",
      "iam:PutRolePermissionsBoundary",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "DenyBoundaryPolicyMutation"
    effect = "Deny"
    actions = [
      "iam:CreatePolicyVersion",
      "iam:DeletePolicy",
      "iam:DeletePolicyVersion",
      "iam:SetDefaultPolicyVersion",
    ]
    resources = [local.boundary_policy_arn]
  }
}

resource "aws_iam_policy" "permissions_boundary" {
  name   = local.boundary_policy_name
  policy = data.aws_iam_policy_document.permissions_boundary.json
}

resource "aws_iam_openid_connect_provider" "github_actions" {
  url             = local.oidc_url
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [local.oidc_thumbprint]
}

resource "aws_iam_role" "github_actions" {
  name                 = var.role_name
  assume_role_policy   = data.aws_iam_policy_document.assume_role.json
  permissions_boundary = aws_iam_policy.permissions_boundary.arn
}

resource "aws_iam_role_policy" "terraform" {
  name   = "${var.role_name}-terraform"
  role   = aws_iam_role.github_actions.id
  policy = data.aws_iam_policy_document.terraform.json
}
