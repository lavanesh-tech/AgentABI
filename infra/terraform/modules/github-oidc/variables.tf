variable "enabled" {
  description = <<-EOT
    Create the GitHub Actions OIDC provider and deploy role. Defaults to
    false: this repository has not been pushed to GitHub yet (per the
    project's phase ordering — GitHub push is deliberately the last step,
    after security review), so github_org/github_repo cannot be set to a
    real value yet, and there is nothing meaningful to federate against.
    Flip to true once the repository is pushed, with real github_org and
    github_repository values.
  EOT
  type        = bool
  default     = false
}

variable "name_prefix" {
  type = string
}

variable "github_org" {
  description = "GitHub organization or username that owns the repository. Required (and validated) when enabled = true. Left blank otherwise — never a placeholder/fake value."
  type        = string
  default     = ""
}

variable "github_repository" {
  description = "GitHub repository name (without the org/ prefix). Required (and validated) when enabled = true."
  type        = string
  default     = ""
}

variable "allowed_ref_patterns" {
  description = <<-EOT
    Git refs (branch/tag) allowed to assume the deploy role, e.g.
    ["refs/heads/main"]. Each becomes a `repo:<org>/<repo>:ref:<pattern>`
    subject in the trust policy. Keep this narrow — this role can push
    images to ECR and modify EKS workloads.
  EOT
  type        = list(string)
  default     = ["refs/heads/main"]
}

variable "allowed_environments" {
  description = <<-EOT
    GitHub Environments (e.g. ["demo"]) allowed to assume the deploy role
    via `repo:<org>/<repo>:environment:<name>` subjects, in addition to
    (or instead of) allowed_ref_patterns. Use a GitHub Environment with
    required reviewers to gate the manual recruiter-demo deploy behind an
    explicit approval. Empty by default — no environment-scoped trust
    until one is configured in GitHub and named here.
  EOT
  type        = list(string)
  default     = []
}

variable "ecr_repository_arns" {
  description = "ECR repository ARNs the deploy role may push images to."
  type        = list(string)
  default     = []
}

variable "eks_cluster_arn" {
  description = "EKS cluster ARN the deploy role may describe/update workloads on. Required when enabled = true."
  type        = string
  default     = ""
}

variable "eks_cluster_name" {
  description = "EKS cluster name, used to scope the aws_eks_access_entry that grants this role cluster RBAC."
  type        = string
  default     = ""
}

variable "tags" {
  type    = map(string)
  default = {}
}
