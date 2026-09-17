# GitHub Actions -> AWS authentication via OIDC federation. No long-lived
# AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY are ever stored as GitHub
# secrets: a workflow run exchanges GitHub's own short-lived OIDC token
# for temporary AWS credentials by assuming aws_iam_role.deploy below,
# scoped to a specific repository and ref/environment.
#
# Disabled by default (var.enabled = false) because this repository has
# not been pushed to GitHub yet — see the variable's own description.
# Every resource here is count-gated on var.enabled so this module is a
# safe no-op until that flip happens with real org/repo values.

locals {
  # One IAM OIDC provider per AWS account per issuer — safe to create
  # once here; if an account already has one (e.g. from another
  # project), import it instead of letting this collide.
  github_oidc_issuer_url = "https://token.actions.githubusercontent.com"

  ref_subjects = [
    for ref in var.allowed_ref_patterns :
    "repo:${var.github_org}/${var.github_repository}:ref:${ref}"
  ]
  environment_subjects = [
    for env in var.allowed_environments :
    "repo:${var.github_org}/${var.github_repository}:environment:${env}"
  ]
  allowed_subjects = concat(local.ref_subjects, local.environment_subjects)
}

data "tls_certificate" "github_actions" {
  count = var.enabled ? 1 : 0
  url   = local.github_oidc_issuer_url
}

resource "aws_iam_openid_connect_provider" "github_actions" {
  count = var.enabled ? 1 : 0

  url             = local.github_oidc_issuer_url
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.github_actions[0].certificates[0].sha1_fingerprint]

  tags = var.tags
}

data "aws_iam_policy_document" "deploy_trust" {
  count = var.enabled ? 1 : 0

  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github_actions[0].arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # StringLike (not StringEquals) with an explicit, enumerated subject
    # list — never a wildcard "repo:org/*" — so only the exact
    # branches/environments named in allowed_ref_patterns /
    # allowed_environments can assume this role.
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = local.allowed_subjects
    }
  }
}

resource "aws_iam_role" "deploy" {
  count = var.enabled ? 1 : 0

  name               = "${var.name_prefix}-github-actions-deploy"
  assume_role_policy = data.aws_iam_policy_document.deploy_trust[0].json
  tags               = var.tags

  lifecycle {
    precondition {
      condition     = var.github_org != "" && var.github_repository != ""
      error_message = "github_org and github_repository must both be set (to real values, never placeholders) when enabled = true."
    }
    precondition {
      condition     = length(local.allowed_subjects) > 0
      error_message = "At least one of allowed_ref_patterns or allowed_environments must be non-empty when enabled = true."
    }
  }
}

# --- ECR push --------------------------------------------------------------

data "aws_iam_policy_document" "ecr_push" {
  count = var.enabled && length(var.ecr_repository_arns) > 0 ? 1 : 0

  statement {
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"] # GetAuthorizationToken does not support resource scoping
  }

  statement {
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:PutImage",
    ]
    resources = var.ecr_repository_arns
  }
}

resource "aws_iam_policy" "ecr_push" {
  count  = var.enabled && length(var.ecr_repository_arns) > 0 ? 1 : 0
  name   = "${var.name_prefix}-github-actions-ecr-push"
  policy = data.aws_iam_policy_document.ecr_push[0].json
  tags   = var.tags
}

resource "aws_iam_role_policy_attachment" "ecr_push" {
  count      = var.enabled && length(var.ecr_repository_arns) > 0 ? 1 : 0
  role       = aws_iam_role.deploy[0].name
  policy_arn = aws_iam_policy.ecr_push[0].arn
}

# --- EKS describe (needed for `aws eks update-kubeconfig`) -----------------

data "aws_iam_policy_document" "eks_describe" {
  count = var.enabled && var.eks_cluster_arn != "" ? 1 : 0

  statement {
    effect    = "Allow"
    actions   = ["eks:DescribeCluster"]
    resources = [var.eks_cluster_arn]
  }
}

resource "aws_iam_policy" "eks_describe" {
  count  = var.enabled && var.eks_cluster_arn != "" ? 1 : 0
  name   = "${var.name_prefix}-github-actions-eks-describe"
  policy = data.aws_iam_policy_document.eks_describe[0].json
  tags   = var.tags
}

resource "aws_iam_role_policy_attachment" "eks_describe" {
  count      = var.enabled && var.eks_cluster_arn != "" ? 1 : 0
  role       = aws_iam_role.deploy[0].name
  policy_arn = aws_iam_policy.eks_describe[0].arn
}

# --- EKS cluster RBAC via Access Entries (AWS-recommended mechanism; no ---
# --- aws-auth ConfigMap edit, no Kubernetes/Helm Terraform provider) -------
#
# Grants this role kubectl-equivalent access scoped to the AgentABI
# namespace's workloads via the AWS-managed AmazonEKSEditPolicy access
# policy, not full cluster-admin. Neo4j lives in the same namespace, so
# no separate association is required for it.

resource "aws_eks_access_entry" "deploy" {
  count = var.enabled && var.eks_cluster_name != "" ? 1 : 0

  cluster_name  = var.eks_cluster_name
  principal_arn = aws_iam_role.deploy[0].arn
  type          = "STANDARD"
  tags          = var.tags
}

resource "aws_eks_access_policy_association" "deploy" {
  count = var.enabled && var.eks_cluster_name != "" ? 1 : 0

  cluster_name  = var.eks_cluster_name
  principal_arn = aws_iam_role.deploy[0].arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSEditPolicy"

  access_scope {
    type       = "namespace"
    namespaces = ["agentabi"]
  }
}
