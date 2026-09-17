variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "project" {
  type    = string
  default = "AgentABI"
}

variable "bucket_suffix" {
  description = "S3 bucket names are globally unique across all of AWS — append something identifying (account alias, random suffix) to avoid collisions."
  type        = string
}
