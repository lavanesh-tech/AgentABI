variable "name_prefix" {
  type = string
}

variable "secret_names" {
  description = <<-EOT
    Logical names of secret containers to create. Terraform creates ONLY
    the empty aws_secretsmanager_secret container for each — no
    aws_secretsmanager_secret_version, ever. Values are populated
    out-of-band (console, `aws secretsmanager put-secret-value`, or a
    Phase 18 bootstrap step) after apply. See infra/terraform/README.md
    "Secrets strategy".
  EOT
  type = list(string)
  default = [
    "jwt-signing-key",
    "openai-api-key",
    "github-oauth-client",
    "github-app-credentials",
  ]
}

variable "recovery_window_in_days" {
  description = "0 allows immediate deletion (needed for a fast destroy/recreate demo cycle without waiting out AWS's default 30-day pending-deletion window). Raise for anything where accidental deletion must be recoverable."
  type        = number
  default     = 0
}

variable "tags" {
  type    = map(string)
  default = {}
}
