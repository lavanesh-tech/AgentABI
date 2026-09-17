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
  description = "Security group IDs permitted to reach Postgres on 5432 (typically the EKS cluster's additional SG)."
  type        = list(string)
}

variable "engine_version" {
  type    = string
  default = "16.4"
}

variable "instance_class" {
  description = "Cost-conscious demo default: db.t4g.micro. Bump for anything beyond a short recruiter demo."
  type        = string
  default     = "db.t4g.micro"
}

variable "allocated_storage_gb" {
  type    = number
  default = 20
}

variable "max_allocated_storage_gb" {
  description = "Ceiling for RDS storage autoscaling. Set equal to allocated_storage_gb to disable autoscaling."
  type        = number
  default     = 100
}

variable "multi_az" {
  description = "Multi-AZ standby. false (default) halves RDS cost for a demo that tolerates single-AZ downtime; true is the production-recommended setting."
  type        = bool
  default     = false
}

variable "backup_retention_days" {
  type    = number
  default = 1
}

variable "database_name" {
  type    = string
  default = "agentabi"
}

variable "master_username" {
  type    = string
  default = "agentabi_admin"
}

variable "skip_final_snapshot" {
  description = <<-EOT
    A. Fully disposable demo database (default, true): `terraform destroy`
       deletes RDS with no final snapshot — fastest/cheapest recreate cycle,
       but ALL data is lost on destroy.
    B. Preserve demo data: set false, and optionally set
       deletion_protection = true too. `terraform destroy` (after disabling
       deletion_protection) creates a final snapshot named
       "<name_prefix>-final-<timestamp via final_snapshot_identifier>"
       before deleting the instance; restoring from it is a separate,
       deliberate `aws rds restore-db-instance-from-db-snapshot` step, not
       automated by this module. See infra/terraform/README.md.
  EOT
  type    = bool
  default = true
}

variable "deletion_protection" {
  description = "AWS-level API guard against accidental deletion. Must be explicitly disabled (via terraform apply) before a destroy can succeed — configurable rather than hardcoded so the demo teardown path isn't permanently blocked."
  type        = bool
  default     = false
}

variable "tags" {
  type    = map(string)
  default = {}
}
