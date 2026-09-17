terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.30, < 6.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }
}
