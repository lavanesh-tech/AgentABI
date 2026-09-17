# Entirely optional: with domain_name = "" (the default), this module
# creates nothing and every output is null. Terraform still validates and
# plans cleanly with no domain configured — no domain name is invented.

locals {
  enabled = var.domain_name != ""
}

resource "aws_route53_zone" "this" {
  count = local.enabled && var.create_hosted_zone ? 1 : 0
  name  = var.domain_name
  tags  = merge(var.tags, { Name = var.domain_name })
}

data "aws_route53_zone" "existing" {
  count = local.enabled && !var.create_hosted_zone ? 1 : 0
  name  = var.domain_name
}

# one(resource.this[*].attr) throughout this module (instead of
# resource.this[0].attr) guards against indexing a count = 0 resource:
# Terraform evaluates both arms of a ternary's resource references when
# building the dependency graph, so a direct `foo.this[0]` errors with
# "index out of range" even on the branch that isn't logically selected
# once foo.this has zero instances. Splatting first (`foo.this[*]`) is
# always safe — an empty list on count = 0 — and one() collapses a
# 0-or-1-element list to null-or-the-element.
locals {
  zone_id = local.enabled ? one(concat(
    aws_route53_zone.this[*].zone_id,
    data.aws_route53_zone.existing[*].zone_id,
  )) : null

  zone_arn = local.enabled ? (
    length(aws_route53_zone.this) > 0
    ? one(aws_route53_zone.this[*].arn)
    : "arn:aws:route53:::hostedzone/${one(data.aws_route53_zone.existing[*].zone_id)}"
  ) : null
}

resource "aws_acm_certificate" "this" {
  count             = local.enabled ? 1 : 0
  domain_name       = var.domain_name
  subject_alternative_names = ["*.${var.domain_name}"]
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }

  tags = merge(var.tags, { Name = var.domain_name })
}

resource "aws_route53_record" "cert_validation" {
  # flatten() over the splat is safe on a count = 0 certificate (empty
  # list in, empty list out) — no [0] indexing, so no ternary/gotcha risk.
  for_each = {
    for dvo in flatten(aws_acm_certificate.this[*].domain_validation_options) : dvo.domain_name => {
      name   = dvo.resource_record_name
      type   = dvo.resource_record_type
      record = dvo.resource_record_value
    }
  }

  zone_id         = local.zone_id
  name            = each.value.name
  type            = each.value.type
  ttl             = 60
  records         = [each.value.record]
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "this" {
  count                   = local.enabled ? 1 : 0
  certificate_arn         = aws_acm_certificate.this[0].arn
  validation_record_fqdns = [for r in aws_route53_record.cert_validation : r.fqdn]
}
