resource "aws_elasticache_subnet_group" "this" {
  name       = "${var.name_prefix}-cache"
  subnet_ids = var.private_data_subnet_ids
  tags       = var.tags
}

resource "aws_security_group" "redis" {
  name_prefix = "${var.name_prefix}-cache-"
  description = "AgentABI ElastiCache — ingress only from the EKS cluster's node/pod security group. Never publicly reachable."
  vpc_id      = var.vpc_id
  tags        = merge(var.tags, { Name = "${var.name_prefix}-cache" })

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_ingress_rule" "redis_from_eks" {
  for_each = toset(var.allowed_security_group_ids)

  security_group_id            = aws_security_group.redis.id
  referenced_security_group_id = each.value
  from_port                    = 6379
  to_port                      = 6379
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "redis_all" {
  security_group_id = aws_security_group.redis.id
  ip_protocol        = "-1"
  cidr_ipv4          = "0.0.0.0/0"
}

data "aws_secretsmanager_secret_version" "auth_token" {
  count     = var.enable_auth_token ? 1 : 0
  secret_id = var.auth_token_secret_arn
}

resource "aws_elasticache_replication_group" "this" {
  replication_group_id = "${var.name_prefix}-cache"
  description           = "AgentABI cache/broker (${var.engine})"

  engine         = var.engine
  engine_version = var.engine_version
  node_type      = var.node_type

  num_cache_clusters         = var.automatic_failover_enabled ? 1 + var.num_cache_replicas : 1
  automatic_failover_enabled = var.automatic_failover_enabled
  multi_az_enabled           = var.automatic_failover_enabled

  subnet_group_name = aws_elasticache_subnet_group.this.name
  security_group_ids = [aws_security_group.redis.id]

  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  # one(...[*]...), not ...[0]..., so this stays valid even when the data
  # source has count = 0 (enable_auth_token = false) — see the pattern
  # note in modules/dns/main.tf.
  auth_token = one(data.aws_secretsmanager_secret_version.auth_token[*].secret_string)

  auto_minor_version_upgrade = true

  tags = merge(var.tags, { Name = "${var.name_prefix}-cache" })
}
