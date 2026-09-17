output "enabled" {
  value = local.enabled
}

output "hosted_zone_id" {
  value = local.zone_id
}

output "hosted_zone_arn" {
  value = local.zone_arn
}

output "name_servers" {
  # one(resource.this[*].attr), not resource.this[0].attr — see the
  # comment in main.tf: safe on a count = 0 resource, no ternary/index gotcha.
  value = one(aws_route53_zone.this[*].name_servers)
}

output "certificate_arn" {
  value = one(aws_acm_certificate_validation.this[*].certificate_arn)
}
