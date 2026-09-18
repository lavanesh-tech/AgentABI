# EKS control plane + one managed node group. No Kubernetes-object
# resources here (no kubernetes/helm provider) — Phase 18 owns everything
# that runs *inside* the cluster (AgentABI workloads, Neo4j, the AWS Load
# Balancer Controller, cluster-autoscaler, etc). This module's job ends at
# "a cluster and nodes exist, with the IAM/OIDC plumbing Phase 18 needs."

# --- KMS key for EKS secrets envelope encryption --------------------------

resource "aws_kms_key" "eks" {
  description             = "${var.name_prefix} EKS secrets envelope encryption"
  deletion_window_in_days = 7
  enable_key_rotation     = true
  tags                    = merge(var.tags, { Name = "${var.name_prefix}-eks-kms" })
}

resource "aws_kms_alias" "eks" {
  name          = "alias/${var.name_prefix}-eks"
  target_key_id = aws_kms_key.eks.key_id
}

# --- Cluster IAM role -------------------------------------------------------

resource "aws_iam_role" "cluster" {
  name = "${var.name_prefix}-eks-cluster"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "eks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "cluster_policy" {
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

# --- Cluster security group (additional to the one EKS manages itself) ---
# Used as the ingress source for anything that must only be reachable from
# pods running on this cluster's nodes (RDS, ElastiCache, MSK).

resource "aws_security_group" "cluster_additional" {
  name_prefix = "${var.name_prefix}-eks-extra-"
  description = "Additional SG attached to the EKS cluster for cross-service ingress rules (RDS/Redis/MSK reference this as their allowed source)."
  vpc_id      = var.vpc_id
  tags        = merge(var.tags, { Name = "${var.name_prefix}-eks-extra" })

  lifecycle {
    create_before_destroy = true
  }
}


resource "aws_cloudwatch_log_group" "cluster" {
  name              = "/aws/eks/${var.name_prefix}/cluster"
  retention_in_days = var.cluster_log_retention_days
  tags              = var.tags
}

resource "aws_eks_cluster" "this" {
  name     = "${var.name_prefix}-eks"
  role_arn = aws_iam_role.cluster.arn
  version  = var.cluster_version

  vpc_config {
    subnet_ids              = concat(var.private_subnet_ids, var.public_subnet_ids)
    security_group_ids      = [aws_security_group.cluster_additional.id]
    endpoint_private_access = true
    endpoint_public_access  = var.cluster_endpoint_public_access
    public_access_cidrs     = var.cluster_endpoint_public_access_cidrs
  }

  encryption_config {
    provider {
      key_arn = aws_kms_key.eks.arn
    }
    resources = ["secrets"]
  }

  # API_AND_CONFIG_MAP (rather than the legacy CONFIG_MAP-only mode) turns
  # on EKS Access Entries — the current AWS-recommended way to grant
  # cluster RBAC to an IAM principal (aws_eks_access_entry +
  # aws_eks_access_policy_association, both plain AWS-provider resources).
  # Phase 18 uses this so the GitHub Actions deploy role (see the
  # github-oidc module) can be bound to `system:masters`-equivalent
  # deploy permissions without a Kubernetes/Helm Terraform provider or an
  # aws-auth ConfigMap edit. CONFIG_MAP stays enabled alongside it so any
  # legacy aws-auth-based mapping keeps working too.
  access_config {
    authentication_mode = "API_AND_CONFIG_MAP"
  }

  enabled_cluster_log_types = var.enabled_cluster_log_types

  depends_on = [
    aws_iam_role_policy_attachment.cluster_policy,
    aws_cloudwatch_log_group.cluster,
  ]

  tags = var.tags
}

# --- OIDC provider for IRSA (IAM Roles for Service Accounts) --------------
# Required so Phase 18 workloads (AWS Load Balancer Controller, EBS CSI
# driver, cluster-autoscaler, AgentABI API/worker pods reading Secrets
# Manager) get scoped AWS credentials via a Kubernetes service account,
# never broad node-level IAM permissions.

data "tls_certificate" "eks_oidc" {
  url = aws_eks_cluster.this.identity[0].oidc[0].issuer
}

resource "aws_iam_openid_connect_provider" "eks" {
  url             = aws_eks_cluster.this.identity[0].oidc[0].issuer
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.eks_oidc.certificates[0].sha1_fingerprint]
  tags            = var.tags
}

# --- Node group IAM role ----------------------------------------------------

resource "aws_iam_role" "node" {
  name = "${var.name_prefix}-eks-node"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "node_worker" {
  role       = aws_iam_role.node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"
}

resource "aws_iam_role_policy_attachment" "node_cni" {
  role       = aws_iam_role.node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
}

resource "aws_iam_role_policy_attachment" "node_ecr_read" {
  role       = aws_iam_role.node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

resource "aws_eks_node_group" "default" {
  cluster_name    = aws_eks_cluster.this.name
  node_group_name = "${var.name_prefix}-default"
  node_role_arn   = aws_iam_role.node.arn
  subnet_ids      = var.private_subnet_ids

  instance_types = var.node_instance_types
  capacity_type  = var.node_capacity_type
  disk_size      = var.node_disk_size_gb

  scaling_config {
    desired_size = var.node_desired_size
    min_size     = var.node_min_size
    max_size     = var.node_max_size
  }

  update_config {
    max_unavailable = 1
  }

  labels = {
    "agentabi.io/node-pool" = "default"
  }

  depends_on = [
    aws_iam_role_policy_attachment.node_worker,
    aws_iam_role_policy_attachment.node_cni,
    aws_iam_role_policy_attachment.node_ecr_read,
  ]

  tags = var.tags

  lifecycle {
    ignore_changes = [scaling_config[0].desired_size] # let cluster-autoscaler (Phase 18) own this after first apply
  }
}
