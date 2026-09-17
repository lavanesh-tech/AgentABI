resource "aws_secretsmanager_secret" "this" {
  for_each = toset(var.secret_names)

  name                    = "${var.name_prefix}/${each.value}"
  description             = "AgentABI ${each.value} — value populated outside Terraform. Never set via terraform.tfvars or aws_secretsmanager_secret_version."
  recovery_window_in_days = var.recovery_window_in_days

  tags = merge(var.tags, { Name = "${var.name_prefix}-${each.value}" })
}
