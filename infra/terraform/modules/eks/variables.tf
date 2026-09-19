variable "name_prefix" {
  type = string
}

variable "cluster_version" {
  description = "Kubernetes version for the EKS control plane."
  type        = string
  default     = "1.30"
}

variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  description = "Subnets for the EKS control plane ENIs and worker nodes (private-app tier)."
  type        = list(string)
}

variable "public_subnet_ids" {
  description = "Public subnets, only used if cluster_endpoint_public_access is true and for internet-facing ALBs provisioned in Phase 18."
  type        = list(string)
}

variable "cluster_endpoint_public_access" {
  description = "Whether to expose the Kubernetes API endpoint publicly. Secure default is private-only; explicitly opt in only when required."
  type        = bool
  default     = false
}

variable "cluster_endpoint_public_access_cidrs" {
  description = "CIDRs allowed to reach the public Kubernetes API endpoint when explicitly enabled."
  type        = list(string)
  default     = []
}

variable "enabled_cluster_log_types" {
  description = "EKS control plane log types shipped to CloudWatch Logs."
  type        = list(string)
  default     = ["api", "audit", "authenticator"]
}

variable "cluster_log_retention_days" {
  type    = number
  default = 14
}

variable "node_instance_types" {
  type    = list(string)
  default = ["c7i-flex.large"]
}

variable "node_capacity_type" {
  description = "ON_DEMAND or SPOT. SPOT is materially cheaper for a disposable demo node group at the cost of possible interruption."
  type        = string
  default     = "ON_DEMAND"

  validation {
    condition     = contains(["ON_DEMAND", "SPOT"], var.node_capacity_type)
    error_message = "node_capacity_type must be ON_DEMAND or SPOT."
  }
}

variable "node_desired_size" {
  type    = number
  default = 2
}

variable "node_min_size" {
  type    = number
  default = 1
}

variable "node_max_size" {
  type    = number
  default = 4
}

variable "node_disk_size_gb" {
  type    = number
  default = 40
}

variable "tags" {
  type    = map(string)
  default = {}
}
