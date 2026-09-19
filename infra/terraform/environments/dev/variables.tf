variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "project" {
  type    = string
  default = "AgentABI"
}

variable "environment" {
  type    = string
  default = "dev"
}

variable "azs" {
  description = "At least 2 AZs in aws_region. us-east-1a/b are the conservative default; override to match your chosen region."
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
}

variable "vpc_cidr" {
  type    = string
  default = "10.42.0.0/16"
}

# --- Cost-control toggles (see infra/terraform/README.md) -----------------

variable "single_nat_gateway" {
  description = "true (default, cost-conscious demo) = 1 NAT Gateway total. false (production-style) = 1 per AZ."
  type        = bool
  default     = true
}

variable "eks_cluster_version" {
  type    = string
  default = "1.36"
}

variable "eks_node_instance_types" {
  type    = list(string)
  default = ["c7i-flex.large"]
}

variable "eks_node_capacity_type" {
  type    = string
  default = "ON_DEMAND"
}

variable "eks_node_desired_size" {
  type    = number
  default = 2
}

variable "eks_node_min_size" {
  type    = number
  default = 1
}

variable "eks_node_max_size" {
  type    = number
  default = 4
}

variable "eks_cluster_endpoint_public_access" {
  description = "Whether the EKS Kubernetes API is publicly reachable. Secure default is false."
  type        = bool
  default     = false
}

variable "eks_cluster_endpoint_public_access_cidrs" {
  description = "CIDRs allowed when EKS public API access is explicitly enabled."
  type        = list(string)
  default     = []
}

variable "rds_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "rds_allocated_storage_gb" {
  type    = number
  default = 20
}

variable "rds_multi_az" {
  type    = bool
  default = false
}

variable "rds_skip_final_snapshot" {
  description = "true (default) = fully disposable demo DB. false = preserve data via final snapshot on destroy — see modules/rds's variable docs."
  type        = bool
  default     = true
}

variable "rds_deletion_protection" {
  type    = bool
  default = false
}

variable "redis_engine" {
  type    = string
  default = "valkey"
}

variable "redis_node_type" {
  type    = string
  default = "cache.t4g.micro"
}

variable "redis_automatic_failover_enabled" {
  type    = bool
  default = false
}


variable "domain_name" {
  description = "Leave empty to skip Route53/ACM — the deployment is fully valid and usable without a custom domain."
  type        = string
  default     = ""
}

variable "create_hosted_zone" {
  type    = bool
  default = false
}

# --- Phase 18: GitHub Actions CD authentication (see infra/terraform/modules/github-oidc) ---

variable "github_actions_oidc_enabled" {
  description = "Create the GitHub Actions OIDC provider/deploy role. Leave false until this repository is pushed to GitHub — see docs/DECISIONS.md's Phase 18 ADR."
  type        = bool
  default     = false
}

variable "github_org" {
  description = "GitHub organization/username. Only meaningful once github_actions_oidc_enabled = true. Never set to a placeholder value."
  type        = string
  default     = ""
}

variable "github_repository" {
  description = "GitHub repository name (without the org/ prefix). Only meaningful once github_actions_oidc_enabled = true."
  type        = string
  default     = ""
}

variable "github_actions_allowed_refs" {
  description = "Git refs allowed to assume the CD deploy role, e.g. [\"refs/heads/main\"]."
  type        = list(string)
  default     = ["refs/heads/main"]
}

variable "github_actions_allowed_environments" {
  description = "GitHub Environments (e.g. [\"demo\"]) allowed to assume the CD deploy role, in addition to github_actions_allowed_refs."
  type        = list(string)
  default     = ["demo"]
}

locals {
  name_prefix = "${lower(var.project)}-${var.environment}"

  common_tags = {
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}
