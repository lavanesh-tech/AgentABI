output "enabled" {
  value = var.enabled
}

output "deploy_role_arn" {
  description = "ARN to configure as the AWS_DEPLOY_ROLE_ARN GitHub Actions variable. Null until enabled = true with real org/repo values."
  value       = one(aws_iam_role.deploy[*].arn)
}

output "oidc_provider_arn" {
  value = one(aws_iam_openid_connect_provider.github_actions[*].arn)
}
