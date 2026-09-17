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
  description = "Expose the Kubernetes API endpoint publicly. Needed for a portfolio/demo environment operated from a laptop without VPN/bastion access; restrict with cluster_endpoint_public_access_cidrs rather than disabling entirely if possible."
  type        = bool
  default     = true
}

variable "cluster_endpoint_public_access_cidrs" {
  description = "CIDRs allowed to reach the public Kubernetes API endpoint when cluster_endpoint_public_access is true. Defaults to open (0.0.0.0/0) for demo convenience — tighten to your own IP/CIDR for anything beyond a short-lived demo."
  type        = list(string)
  default     = ["0.0.0.0/0"]
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
  default = ["t3.medium"]
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
