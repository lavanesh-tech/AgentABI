terraform {
  required_version = ">= 1.7.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Deliberately local state. This is the one piece of infrastructure that
  # cannot bootstrap its own remote backend without a circular dependency —
  # apply it once with local state, then point environments/dev's backend
  # block at its outputs. See infra/terraform/README.md "Remote state
  # strategy".
}

provider "aws" {
  region = var.aws_region
}
