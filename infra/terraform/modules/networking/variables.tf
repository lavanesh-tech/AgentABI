variable "name_prefix" {
  description = "Prefix for resource names, e.g. agentabi-dev."
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.42.0.0/16"
}

variable "azs" {
  description = "Availability zones to spread subnets across. 2 is the minimum for EKS/RDS Multi-AZ eligibility; 3 is production-typical."
  type        = list(string)

  validation {
    condition     = length(var.azs) >= 2
    error_message = "At least 2 availability zones are required (EKS and RDS both expect multi-AZ subnet placement)."
  }
}

variable "public_subnet_newbits" {
  description = "Additional bits (cidrsubnet newbits) for public subnets, carved from vpc_cidr."
  type        = number
  default     = 4
}

variable "private_app_subnet_newbits" {
  description = "Additional bits for private application (EKS node) subnets."
  type        = number
  default     = 4
}

variable "private_data_subnet_newbits" {
  description = "Additional bits for private data (RDS/ElastiCache/MSK) subnets."
  type        = number
  default     = 4
}

variable "single_nat_gateway" {
  description = <<-EOT
    Cost-vs-availability switch. true (default): provision exactly ONE NAT
    Gateway for the whole VPC — cheapest option, single point of failure for
    egress if that AZ has an outage. This is the recommended default for a
    recruiter/demo environment that is provisioned on demand and destroyed
    afterward. false: provision one NAT Gateway PER availability zone
    (production-style, no cross-AZ egress dependency, but N times the NAT
    Gateway hourly + data processing cost). See infra/terraform/README.md
    "Networking cost trade-off" for details.
  EOT
  type        = bool
  default     = true
}

variable "enable_nat_gateway" {
  description = <<-EOT
    Whether to create any NAT Gateway at all. Disabling this removes all
    egress from private subnets (no outbound internet for EKS nodes to pull
    images, call AWS APIs via public endpoints, etc.) unless VPC endpoints
    are used instead. Kept as an explicit off-switch for cost-sensitive
    static review of the plan; not recommended for an environment that
    intends to actually run workloads.
  EOT
  type        = bool
  default     = true
}

variable "tags" {
  description = "Common tags applied to every resource this module creates."
  type        = map(string)
  default     = {}
}
