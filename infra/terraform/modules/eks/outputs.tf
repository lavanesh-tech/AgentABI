output "cluster_name" {
  value = aws_eks_cluster.this.name
}

output "cluster_arn" {
  value = aws_eks_cluster.this.arn
}

output "cluster_endpoint" {
  value = aws_eks_cluster.this.endpoint
}

output "cluster_certificate_authority_data" {
  value = aws_eks_cluster.this.certificate_authority[0].data
}

output "cluster_version" {
  value = aws_eks_cluster.this.version
}

output "node_role_arn" {
  value = aws_iam_role.node.arn
}

output "additional_security_group_id" {
  description = "Attach this SG (or reference it) as the allowed ingress source on RDS/ElastiCache/MSK security groups."
  value       = aws_security_group.cluster_additional.id
}

output "cluster_security_group_id" {
  description = "EKS-created cluster security group automatically associated with managed node group ENIs."
  value       = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
}

output "oidc_provider_arn" {
  value = aws_iam_openid_connect_provider.eks.arn
}

output "oidc_provider_url" {
  value = replace(aws_iam_openid_connect_provider.eks.url, "https://", "")
}

output "kms_key_arn" {
  value = aws_kms_key.eks.arn
}
