variable "name_prefix" {
  type = string
}

variable "domain_name" {
  description = "Custom domain for AgentABI, e.g. agentabi.example.com. Leave empty (default) to skip Route53/ACM entirely — the rest of the infrastructure is fully usable without a domain (Phase 18 exposes the ALB's own DNS name)."
  type        = string
  default     = ""
}

variable "create_hosted_zone" {
  description = "true: Route53 creates and owns the hosted zone for domain_name (you point your registrar's NS records at the output name_servers). false: look up an existing hosted zone by domain_name instead of creating one."
  type        = bool
  default     = false
}

variable "tags" {
  type    = map(string)
  default = {}
}
