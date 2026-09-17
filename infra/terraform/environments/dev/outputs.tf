output "vpc_id" {
  value = module.networking.vpc_id
}

output "nat_gateway_count" {
  value = module.networking.nat_gateway_count
}

output "eks_cluster_name" {
  value = module.eks.cluster_name
}

output "eks_cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "eks_oidc_provider_arn" {
  value = module.eks.oidc_provider_arn
}

output "ecr_repository_urls" {
  value = module.ecr.repository_urls
}

output "rds_endpoint" {
  value = module.rds.endpoint
}

output "rds_master_user_secret_arn" {
  description = "Secrets Manager ARN of the RDS-managed master password — retrieve with `aws secretsmanager get-secret-value`, never stored in Terraform state as plaintext."
  value       = module.rds.master_user_secret_arn
}

output "redis_primary_endpoint" {
  value = module.redis.primary_endpoint
}

output "msk_deployment_mode" {
  value = module.msk.deployment_mode
}

output "msk_bootstrap_brokers_iam" {
  value = module.msk.bootstrap_brokers_iam
}

output "secrets_manager_secret_arns" {
  description = "Empty secret containers awaiting out-of-band value population — see infra/terraform/README.md."
  value       = module.secrets.secret_arns
}

output "iam_role_arns" {
  value = {
    lb_controller      = module.iam.lb_controller_role_arn
    ebs_csi            = module.iam.ebs_csi_role_arn
    cluster_autoscaler = module.iam.cluster_autoscaler_role_arn
    app_workload       = module.iam.app_workload_role_arn
    external_dns       = module.iam.external_dns_role_arn
  }
}

output "dns_enabled" {
  value = module.dns.enabled
}

output "acm_certificate_arn" {
  value = module.dns.certificate_arn
}
