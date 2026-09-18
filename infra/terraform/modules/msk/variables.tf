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

variable "deployment_mode" {
  description = <<-EOT
    COST WARNING: MSK is typically the single most expensive component of
    this stack.

    "serverless" (default): MSK Serverless — no fixed broker instances to
      size or pay for while idle; billed by cluster-hours + partition-hours
      + throughput actually used. Recommended for an environment that is
      provisioned for a demo and destroyed afterward, since there is no
      idle-broker cost to reason about between demos.

    "provisioned": classic MSK with fixed broker instances (kafka_broker_instance_type,
      one broker per AZ x broker count), billed per broker-hour continuously
      whether or not anything is produced/consumed — the production-typical
      choice for a cluster that stays up, but the most expensive option for
      a stop-start demo. Kept fully supported here so the architecture
      remains production-credible, not replaced by a non-Kafka substitute.

    Neither mode's actual dollar cost is estimated here — see AWS's MSK
    pricing page / Pricing Calculator, linked in infra/terraform/README.md.
  EOT
  type        = string
  default     = "serverless"

  validation {
    condition     = contains(["serverless", "provisioned"], var.deployment_mode)
    error_message = "deployment_mode must be \"serverless\" or \"provisioned\"."
  }
}

variable "kafka_version" {
  description = "Only used when deployment_mode = \"provisioned\"."
  type        = string
  default     = "3.7.x"
}

variable "broker_instance_type" {
  description = "Only used when deployment_mode = \"provisioned\"."
  type        = string
  default     = "kafka.t3.small"
}

variable "broker_ebs_volume_size_gb" {
  description = "Only used when deployment_mode = \"provisioned\"."
  type        = number
  default     = 20
}

variable "number_of_broker_nodes" {
  description = "Only used when deployment_mode = \"provisioned\". Must be a multiple of the number of subnets/AZs supplied."
  type        = number
  default     = 2
}

variable "tags" {
  type    = map(string)
  default = {}
}
