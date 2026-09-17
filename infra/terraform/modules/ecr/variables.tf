variable "repository_names" {
  type    = list(string)
  default = ["agentabi-api", "agentabi-worker", "agentabi-frontend"]
}

variable "image_tag_mutability" {
  type    = string
  default = "IMMUTABLE"
}

variable "untagged_image_expiry_days" {
  description = "Lifecycle policy: expire untagged images older than this many days."
  type        = number
  default     = 7
}

variable "max_tagged_images_to_keep" {
  description = "Lifecycle policy: keep only the N most recent tagged images per repository, so demo images do not accumulate indefinitely."
  type        = number
  default     = 20
}

variable "tags" {
  type    = map(string)
  default = {}
}
