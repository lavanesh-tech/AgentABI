output "secret_arns" {
  value = { for name, s in aws_secretsmanager_secret.this : name => s.arn }
}

output "secret_names" {
  value = { for name, s in aws_secretsmanager_secret.this : name => s.name }
}
