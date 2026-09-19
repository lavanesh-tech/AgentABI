variable "project_id" {
  description = "GCP project used for the AgentABI recruiter demo."
  type        = string
  default     = "agentabi-demo-2026"
}

variable "region" {
  description = "Primary GCP deployment region."
  type        = string
  default     = "us-east1"
}

variable "environment" {
  type    = string
  default = "demo"
}

locals {
  name_prefix = "agentabi-${var.environment}"

  labels = {
    project     = "agentabi"
    environment = var.environment
    managed_by  = "terraform"
  }
}
