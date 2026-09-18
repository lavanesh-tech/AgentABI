variable "name_prefix" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "private_data_subnet_ids" {
  type = list(string)
}

variable "allowed_security_group_ids" {
  type = list(string)
}

variable "engine" {
  description = "redis or valkey (Valkey is the open-source Redis successor AWS now ships as a first-class ElastiCache engine)."
  type        = string
  default     = "valkey"

  validation {
    condition     = contains(["redis", "valkey"], var.engine)
    error_message = "engine must be \"redis\" or \"valkey\"."
  }
}

variable "engine_version" {
  type    = string
  default = "7.2"
}

variable "node_type" {
  type    = string
  default = "cache.t4g.micro"
}

variable "automatic_failover_enabled" {
  description = "true = a replica + automatic failover (production posture). false (default) = single node, cheaper, no HA for a demo."
  type        = bool
  default     = false
}

variable "num_cache_replicas" {
  description = "Number of replica nodes when automatic_failover_enabled is true. Ignored (0) otherwise."
  type        = number
  default     = 1
}

variable "enable_auth_token" {
  description = <<-EOT
    ElastiCache has no AWS-managed-secret equivalent to RDS's
    manage_master_user_password — an AUTH token must be supplied
    explicitly, which this module refuses to generate itself (that would
    put a plaintext credential in Terraform state). Left false by default:
    the demo relies on network isolation alone (private subnets, security
    group restricted to the EKS cluster's SG, no public endpoint). Set
    true only if you also provide auth_token_secret_arn pointing at a
    Secrets Manager secret you populated out-of-band.
  EOT
  type        = bool
  default     = false
}

variable "auth_token_secret_arn" {
  description = "Secrets Manager secret ARN holding a pre-populated AUTH token. Required if enable_auth_token is true."
  type        = string
  default     = null
}

variable "tags" {
  type    = map(string)
  default = {}
}
