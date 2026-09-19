resource "aws_eks_addon" "ebs_csi" {
  cluster_name = module.eks.cluster_name
  addon_name   = "aws-ebs-csi-driver"

  service_account_role_arn = module.iam.ebs_csi_role_arn

  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "PRESERVE"

  tags = {
    Project     = "AgentABI"
    Environment = "dev"
    ManagedBy   = "Terraform"
  }

  depends_on = [
    module.eks,
    module.iam
  ]
}
