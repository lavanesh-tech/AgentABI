# IRSA (IAM Roles for Service Accounts) foundations. Every role here is
# assumable ONLY by a specific Kubernetes ServiceAccount via the cluster's
# OIDC provider — no node-wide IAM permissions, no wildcard access.
# Phase 18 annotates the corresponding ServiceAccount with
# `eks.amazonaws.com/role-arn: <output>` to bind it.

locals {
  oidc_sub_key = "${var.oidc_provider_url}:sub"
  oidc_aud_key = "${var.oidc_provider_url}:aud"
}

# --- Generic IRSA trust-policy helper (one per role, inlined below) -------

data "aws_iam_policy_document" "lb_controller_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = local.oidc_sub_key
      values   = ["system:serviceaccount:kube-system:aws-load-balancer-controller"]
    }
    condition {
      test     = "StringEquals"
      variable = local.oidc_aud_key
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lb_controller" {
  name               = "${var.name_prefix}-irsa-lb-controller"
  assume_role_policy = data.aws_iam_policy_document.lb_controller_trust.json
  tags               = var.tags
}

# Sourced from the upstream AWS Load Balancer Controller IAM policy
# (eks/aws-load-balancer-controller project). Diff against the latest
# published version before Phase 18 install — AWS revises it periodically.
resource "aws_iam_policy" "lb_controller" {
  name   = "${var.name_prefix}-lb-controller"
  policy = file("${path.module}/files/aws-load-balancer-controller-policy.json")
  tags   = var.tags
}

resource "aws_iam_role_policy_attachment" "lb_controller" {
  role       = aws_iam_role.lb_controller.name
  policy_arn = aws_iam_policy.lb_controller.arn
}

# --- EBS CSI driver (persistent volumes for Neo4j / any stateful pod) -----

data "aws_iam_policy_document" "ebs_csi_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = local.oidc_sub_key
      values   = ["system:serviceaccount:kube-system:ebs-csi-controller-sa"]
    }
    condition {
      test     = "StringEquals"
      variable = local.oidc_aud_key
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ebs_csi" {
  name               = "${var.name_prefix}-irsa-ebs-csi"
  assume_role_policy = data.aws_iam_policy_document.ebs_csi_trust.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "ebs_csi" {
  role       = aws_iam_role.ebs_csi.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
}

# --- cluster-autoscaler -----------------------------------------------------

data "aws_iam_policy_document" "cluster_autoscaler_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = local.oidc_sub_key
      values   = ["system:serviceaccount:kube-system:cluster-autoscaler"]
    }
    condition {
      test     = "StringEquals"
      variable = local.oidc_aud_key
      values   = ["sts.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "cluster_autoscaler" {
  statement {
    effect = "Allow"
    actions = [
      "autoscaling:DescribeAutoScalingGroups",
      "autoscaling:DescribeAutoScalingInstances",
      "autoscaling:DescribeLaunchConfigurations",
      "autoscaling:DescribeTags",
      "ec2:DescribeLaunchTemplateVersions",
      "eks:DescribeNodegroup",
    ]
    resources = ["*"]
  }
  statement {
    effect = "Allow"
    actions = [
      "autoscaling:SetDesiredCapacity",
      "autoscaling:TerminateInstanceInAutoScalingGroup",
      "autoscaling:UpdateAutoScalingGroup",
    ]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/k8s.io/cluster-autoscaler/enabled"
      values   = ["true"]
    }
  }
}

resource "aws_iam_role" "cluster_autoscaler" {
  name               = "${var.name_prefix}-irsa-cluster-autoscaler"
  assume_role_policy = data.aws_iam_policy_document.cluster_autoscaler_trust.json
  tags               = var.tags
}

resource "aws_iam_policy" "cluster_autoscaler" {
  name   = "${var.name_prefix}-cluster-autoscaler"
  policy = data.aws_iam_policy_document.cluster_autoscaler.json
  tags   = var.tags
}

resource "aws_iam_role_policy_attachment" "cluster_autoscaler" {
  role       = aws_iam_role.cluster_autoscaler.name
  policy_arn = aws_iam_policy.cluster_autoscaler.arn
}

# --- AgentABI application workload role (API + worker pods) ---------------
# Least privilege: read-only ECR pull scoped to AgentABI's own repos, and
# read-only Secrets Manager access scoped to AgentABI's own secrets. No
# wildcard resource access, no write permissions.

data "aws_iam_policy_document" "app_workload_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = local.oidc_sub_key
      values = [
        for sa in var.app_service_account_names :
        "system:serviceaccount:${var.app_namespace}:${sa}"
      ]
    }
    condition {
      test     = "StringEquals"
      variable = local.oidc_aud_key
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "app_workload" {
  name               = "${var.name_prefix}-irsa-app-workload"
  assume_role_policy = data.aws_iam_policy_document.app_workload_trust.json
  tags               = var.tags
}

data "aws_iam_policy_document" "app_ecr_read" {
  count = length(var.ecr_repository_arns) > 0 ? 1 : 0

  statement {
    effect    = "Allow"
    actions   = ["ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage", "ecr:BatchCheckLayerAvailability"]
    resources = var.ecr_repository_arns
  }
  statement {
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"] # GetAuthorizationToken is account-scoped only; AWS does not support resource-level restriction for this action.
  }
}

resource "aws_iam_policy" "app_ecr_read" {
  count  = length(var.ecr_repository_arns) > 0 ? 1 : 0
  name   = "${var.name_prefix}-app-ecr-read"
  policy = data.aws_iam_policy_document.app_ecr_read[0].json
  tags   = var.tags
}

resource "aws_iam_role_policy_attachment" "app_ecr_read" {
  count      = length(var.ecr_repository_arns) > 0 ? 1 : 0
  role       = aws_iam_role.app_workload.name
  policy_arn = aws_iam_policy.app_ecr_read[0].arn
}

data "aws_iam_policy_document" "app_secrets_read" {
  count = length(var.secrets_manager_secret_arns) > 0 ? 1 : 0

  statement {
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = var.secrets_manager_secret_arns
  }
}

resource "aws_iam_policy" "app_secrets_read" {
  count  = length(var.secrets_manager_secret_arns) > 0 ? 1 : 0
  name   = "${var.name_prefix}-app-secrets-read"
  policy = data.aws_iam_policy_document.app_secrets_read[0].json
  tags   = var.tags
}

resource "aws_iam_role_policy_attachment" "app_secrets_read" {
  count      = length(var.secrets_manager_secret_arns) > 0 ? 1 : 0
  role       = aws_iam_role.app_workload.name
  policy_arn = aws_iam_policy.app_secrets_read[0].arn
}


# --- AgentABI KMS decrypt --------------------------------------------------

data "aws_iam_policy_document" "app_kms_decrypt" {
  count = length(var.kms_decrypt_key_arns) > 0 ? 1 : 0

  statement {
    effect    = "Allow"
    actions   = ["kms:Decrypt"]
    resources = var.kms_decrypt_key_arns
  }
}

resource "aws_iam_policy" "app_kms_decrypt" {
  count  = length(var.kms_decrypt_key_arns) > 0 ? 1 : 0
  name   = "${var.name_prefix}-app-kms-decrypt"
  policy = data.aws_iam_policy_document.app_kms_decrypt[0].json
  tags   = var.tags
}

resource "aws_iam_role_policy_attachment" "app_kms_decrypt" {
  count      = length(var.kms_decrypt_key_arns) > 0 ? 1 : 0
  role       = aws_iam_role.app_workload.name
  policy_arn = aws_iam_policy.app_kms_decrypt[0].arn
}

# --- external-dns (optional, only meaningful with the dns module) ---------

data "aws_iam_policy_document" "external_dns_trust" {
  count = var.enable_external_dns_role ? 1 : 0

  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = local.oidc_sub_key
      values   = ["system:serviceaccount:kube-system:external-dns"]
    }
    condition {
      test     = "StringEquals"
      variable = local.oidc_aud_key
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "external_dns" {
  count              = var.enable_external_dns_role ? 1 : 0
  name               = "${var.name_prefix}-irsa-external-dns"
  assume_role_policy = data.aws_iam_policy_document.external_dns_trust[0].json
  tags               = var.tags
}

data "aws_iam_policy_document" "external_dns" {
  count = var.enable_external_dns_role ? 1 : 0

  statement {
    effect    = "Allow"
    actions   = ["route53:ChangeResourceRecordSets"]
    resources = [var.hosted_zone_arn]
  }
  statement {
    effect    = "Allow"
    actions   = ["route53:ListHostedZones", "route53:ListResourceRecordSets"]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "external_dns" {
  count  = var.enable_external_dns_role ? 1 : 0
  name   = "${var.name_prefix}-external-dns"
  policy = data.aws_iam_policy_document.external_dns[0].json
  tags   = var.tags
}

resource "aws_iam_role_policy_attachment" "external_dns" {
  count      = var.enable_external_dns_role ? 1 : 0
  role       = aws_iam_role.external_dns[0].name
  policy_arn = aws_iam_policy.external_dns[0].arn
}
