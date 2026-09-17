# Private RDS PostgreSQL. Credentials are never generated or stored by
# Terraform: manage_master_user_password = true delegates master password
# creation/rotation entirely to RDS + Secrets Manager (AWS-managed secret,
# created and populated outside Terraform's own state/plan diff) — this is
# the current AWS-recommended mechanism and the only way this module can
# honestly claim "no credentials in Terraform state."

resource "aws_kms_key" "rds" {
  description             = "${var.name_prefix} RDS storage + managed-secret encryption"
  deletion_window_in_days = 7
  enable_key_rotation     = true
  tags                    = merge(var.tags, { Name = "${var.name_prefix}-rds-kms" })
}

resource "aws_db_subnet_group" "this" {
  name       = "${var.name_prefix}-rds"
  subnet_ids = var.private_data_subnet_ids
  tags       = merge(var.tags, { Name = "${var.name_prefix}-rds" })
}

resource "aws_security_group" "rds" {
  name_prefix = "${var.name_prefix}-rds-"
  description = "AgentABI RDS Postgres — ingress only from the EKS cluster's node/pod security group."
  vpc_id      = var.vpc_id
  tags        = merge(var.tags, { Name = "${var.name_prefix}-rds" })

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_ingress_rule" "rds_from_eks" {
  for_each = toset(var.allowed_security_group_ids)

  security_group_id            = aws_security_group.rds.id
  referenced_security_group_id = each.value
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "rds_all" {
  security_group_id = aws_security_group.rds.id
  ip_protocol        = "-1"
  cidr_ipv4          = "0.0.0.0/0"
}

resource "aws_db_instance" "this" {
  identifier     = "${var.name_prefix}-postgres"
  engine         = "postgres"
  engine_version = var.engine_version
  instance_class = var.instance_class

  allocated_storage     = var.allocated_storage_gb
  max_allocated_storage = var.max_allocated_storage_gb
  storage_type           = "gp3"
  storage_encrypted      = true
  kms_key_id              = aws_kms_key.rds.arn

  db_name  = var.database_name
  username = var.master_username

  manage_master_user_password   = true
  master_user_secret_kms_key_id = aws_kms_key.rds.arn

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible     = false
  multi_az                = var.multi_az

  backup_retention_period = var.backup_retention_days
  copy_tags_to_snapshot   = true

  deletion_protection       = var.deletion_protection
  skip_final_snapshot       = var.skip_final_snapshot
  final_snapshot_identifier = var.skip_final_snapshot ? null : "${var.name_prefix}-postgres-final"

  auto_minor_version_upgrade = true

  tags = merge(var.tags, { Name = "${var.name_prefix}-postgres" })
}
