output "lb_controller_role_arn" {
  value = aws_iam_role.lb_controller.arn
}

output "ebs_csi_role_arn" {
  value = aws_iam_role.ebs_csi.arn
}

output "cluster_autoscaler_role_arn" {
  value = aws_iam_role.cluster_autoscaler.arn
}

output "app_workload_role_arn" {
  value = aws_iam_role.app_workload.arn
}

output "external_dns_role_arn" {
  # one(...[*]...), not ...[0]..., so this stays valid when the role has
  # count = 0 (enable_external_dns_role = false).
  value = one(aws_iam_role.external_dns[*].arn)
}
