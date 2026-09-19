variable "name_prefix" {
  type = string
}

variable "oidc_provider_arn" {
  description = "EKS OIDC provider ARN (from the eks module) — required for IRSA trust policies."
  type        = string
}

variable "oidc_provider_url" {
  description = "EKS OIDC provider URL without the https:// prefix (from the eks module)."
  type        = string
}

variable "ecr_repository_arns" {
  description = "ECR repository ARNs the AgentABI workload role may pull from."
  type        = list(string)
  default     = []
}

variable "secrets_manager_secret_arns" {
  description = "Secrets Manager secret ARNs the AgentABI workload role may read."
  type        = list(string)
  default     = []
}

variable "app_namespace" {
  description = "Kubernetes namespace Phase 18 will deploy AgentABI into — scopes the IRSA trust policy's service account subject."
  type        = string
  default     = "agentabi"
}

variable "app_service_account_names" {
  description = "Kubernetes ServiceAccount names (within app_namespace) allowed to assume the app workload role."
  type        = list(string)
  default     = ["agentabi-api", "agentabi-worker"]
}

variable "enable_external_dns_role" {
  description = "Create an IRSA role for external-dns. Only meaningful when the dns module is also enabled."
  type        = bool
  default     = false
}

variable "hosted_zone_arn" {
  description = "Route53 hosted zone ARN external-dns is permitted to manage records in. Required if enable_external_dns_role is true."
  type        = string
  default     = null
}

variable "tags" {
  type    = map(string)
  default = {}
}

variable "kms_decrypt_key_arns" {
  description = "KMS key ARNs the AgentABI workload role may use for decrypt operations."
  type        = list(string)
  default     = []
}
