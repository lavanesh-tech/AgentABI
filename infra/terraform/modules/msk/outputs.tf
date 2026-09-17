output "deployment_mode" {
  value = var.deployment_mode
}

# one(resource.this[*].attr), not resource.this[0].attr — safe regardless
# of which deployment_mode's resource actually has count = 1, with no
# risk of an "index out of range" on the mode that has count = 0 (see the
# same pattern/comment in modules/dns/main.tf).

output "bootstrap_brokers_iam" {
  description = "IAM-auth bootstrap broker string. Populated for whichever deployment_mode is active."
  value = coalesce(
    one(aws_msk_serverless_cluster.this[*].bootstrap_brokers_sasl_iam),
    one(aws_msk_cluster.this[*].bootstrap_brokers_sasl_iam),
  )
}

output "cluster_arn" {
  value = coalesce(
    one(aws_msk_serverless_cluster.this[*].arn),
    one(aws_msk_cluster.this[*].arn),
  )
}

output "security_group_id" {
  value = aws_security_group.msk.id
}
