# AgentABI dev/demo environment. Infrastructure only — no Kubernetes
# workloads, no Neo4j, no AgentABI application deployment. That is Phase
# 18. See infra/terraform/README.md for the full architecture writeup and
# demo lifecycle (start / demo / shutdown / destroy / recreate).

module "networking" {
  source = "../../modules/networking"

  name_prefix        = local.name_prefix
  vpc_cidr           = var.vpc_cidr
  azs                = var.azs
  single_nat_gateway = var.single_nat_gateway
  tags               = local.common_tags
}

module "eks" {
  source = "../../modules/eks"

  name_prefix        = local.name_prefix
  cluster_version    = var.eks_cluster_version
  vpc_id             = module.networking.vpc_id
  private_subnet_ids = module.networking.private_app_subnet_ids
  public_subnet_ids  = module.networking.public_subnet_ids

  cluster_endpoint_public_access_cidrs = var.eks_cluster_endpoint_public_access_cidrs

  node_instance_types = var.eks_node_instance_types
  node_capacity_type  = var.eks_node_capacity_type
  node_desired_size   = var.eks_node_desired_size
  node_min_size       = var.eks_node_min_size
  node_max_size       = var.eks_node_max_size

  tags = local.common_tags
}

module "ecr" {
  source = "../../modules/ecr"

  tags = local.common_tags
}

module "secrets" {
  source = "../../modules/secrets"

  name_prefix = local.name_prefix
  tags        = local.common_tags
}

module "iam" {
  source = "../../modules/iam"

  name_prefix       = local.name_prefix
  oidc_provider_arn = module.eks.oidc_provider_arn
  oidc_provider_url = module.eks.oidc_provider_url

  ecr_repository_arns         = values(module.ecr.repository_arns)
  secrets_manager_secret_arns = values(module.secrets.secret_arns)

  enable_external_dns_role = module.dns.enabled
  hosted_zone_arn          = module.dns.hosted_zone_arn

  tags = local.common_tags
}

module "rds" {
  source = "../../modules/rds"

  name_prefix                = local.name_prefix
  vpc_id                     = module.networking.vpc_id
  private_data_subnet_ids    = module.networking.private_data_subnet_ids
  allowed_security_group_ids = [module.eks.additional_security_group_id]

  instance_class       = var.rds_instance_class
  allocated_storage_gb = var.rds_allocated_storage_gb
  multi_az             = var.rds_multi_az
  skip_final_snapshot  = var.rds_skip_final_snapshot
  deletion_protection  = var.rds_deletion_protection

  tags = local.common_tags
}

module "redis" {
  source = "../../modules/redis"

  name_prefix                = local.name_prefix
  vpc_id                     = module.networking.vpc_id
  private_data_subnet_ids    = module.networking.private_data_subnet_ids
  allowed_security_group_ids = [module.eks.additional_security_group_id]

  engine                     = var.redis_engine
  node_type                  = var.redis_node_type
  automatic_failover_enabled = var.redis_automatic_failover_enabled

  tags = local.common_tags
}

module "msk" {
  source = "../../modules/msk"

  name_prefix                = local.name_prefix
  vpc_id                     = module.networking.vpc_id
  private_data_subnet_ids    = module.networking.private_data_subnet_ids
  allowed_security_group_ids = [module.eks.additional_security_group_id]

  deployment_mode = var.msk_deployment_mode

  tags = local.common_tags
}

module "dns" {
  source = "../../modules/dns"

  name_prefix        = local.name_prefix
  domain_name        = var.domain_name
  create_hosted_zone = var.create_hosted_zone

  tags = local.common_tags
}

# Phase 18: GitHub Actions -> AWS OIDC federation for the CD workflow.
# Disabled by default — see infra/terraform/modules/github-oidc's
# variables.tf. Flip github_actions_oidc_enabled to true, and set
# github_org/github_repository, once this repository is actually pushed
# to GitHub (deliberately the project's last step).
module "github_oidc" {
  source = "../../modules/github-oidc"

  enabled           = var.github_actions_oidc_enabled
  name_prefix       = local.name_prefix
  github_org        = var.github_org
  github_repository = var.github_repository

  allowed_ref_patterns = var.github_actions_allowed_refs
  allowed_environments = var.github_actions_allowed_environments
  ecr_repository_arns  = values(module.ecr.repository_arns)
  eks_cluster_arn      = module.eks.cluster_arn
  eks_cluster_name     = module.eks.cluster_name

  tags = local.common_tags
}
