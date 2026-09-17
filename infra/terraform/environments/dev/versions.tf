terraform {
  required_version = ">= 1.7.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }

  # Remote state is opt-in and deliberately NOT configured here by default
  # so `terraform init -backend=false` / a plain local-state `terraform
  # init` always works without any AWS access or prior bootstrap step.
  #
  # To use the S3 + DynamoDB remote state backend documented in
  # infra/terraform/README.md ("Remote state strategy"):
  #   1. Apply infra/terraform/bootstrap/ once (creates the S3 bucket +
  #      DynamoDB lock table — this is the ONLY thing ever applied with
  #      local state).
  #   2. Uncomment the backend block below and fill in the bucket/table
  #      names from that bootstrap's outputs.
  #   3. Run `terraform init -migrate-state`.
  #
  # backend "s3" {
  #   bucket         = "REPLACE-WITH-BOOTSTRAP-OUTPUT-bucket_name"
  #   key            = "agentabi/dev/terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "REPLACE-WITH-BOOTSTRAP-OUTPUT-lock_table_name"
  #   encrypt        = true
  # }
}
