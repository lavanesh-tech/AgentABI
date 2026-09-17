# Both MSK deployment modes AWS currently supports through the Terraform
# AWS provider are wired up; exactly one is created based on
# var.deployment_mode. Both authenticate with IAM (SASL/IAM) — no long-lived
# SASL/SCRAM credentials to manage in Terraform.

resource "aws_kms_key" "msk" {
  description             = "${var.name_prefix} MSK encryption at rest"
  deletion_window_in_days = 7
  enable_key_rotation     = true
  tags                    = merge(var.tags, { Name = "${var.name_prefix}-msk-kms" })
}

resource "aws_security_group" "msk" {
  name_prefix = "${var.name_prefix}-msk-"
  description = "AgentABI MSK — ingress only from the EKS cluster's node/pod security group."
  vpc_id      = var.vpc_id
  tags        = merge(var.tags, { Name = "${var.name_prefix}-msk" })

  lifecycle {
    create_before_destroy = true
  }
}

# 9098 = SASL/IAM (both modes). 9094/9092 kept for provisioned mode's TLS
# listener in case a client needs cert-based access instead of IAM.
resource "aws_vpc_security_group_ingress_rule" "msk_iam" {
  for_each = toset(var.allowed_security_group_ids)

  security_group_id            = aws_security_group.msk.id
  referenced_security_group_id = each.value
  from_port                    = 9098
  to_port                      = 9098
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "msk_tls" {
  for_each = var.deployment_mode == "provisioned" ? toset(var.allowed_security_group_ids) : []

  security_group_id            = aws_security_group.msk.id
  referenced_security_group_id = each.value
  from_port                    = 9094
  to_port                      = 9094
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "msk_all" {
  security_group_id = aws_security_group.msk.id
  ip_protocol        = "-1"
  cidr_ipv4          = "0.0.0.0/0"
}

# --- Serverless (cost-conscious default) -----------------------------------

resource "aws_msk_serverless_cluster" "this" {
  count       = var.deployment_mode == "serverless" ? 1 : 0
  cluster_name = "${var.name_prefix}-msk"

  vpc_config {
    subnet_ids         = var.private_data_subnet_ids
    security_group_ids = [aws_security_group.msk.id]
  }

  client_authentication {
    sasl {
      iam {
        enabled = true
      }
    }
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-msk" })
}

# --- Provisioned (production-style, continuous broker cost) ---------------

resource "aws_msk_cluster" "this" {
  count                  = var.deployment_mode == "provisioned" ? 1 : 0
  cluster_name           = "${var.name_prefix}-msk"
  kafka_version          = var.kafka_version
  number_of_broker_nodes = var.number_of_broker_nodes

  broker_node_group_info {
    instance_type   = var.broker_instance_type
    client_subnets  = var.private_data_subnet_ids
    security_groups = [aws_security_group.msk.id]

    storage_info {
      ebs_storage_info {
        volume_size = var.broker_ebs_volume_size_gb
      }
    }
  }

  encryption_info {
    encryption_at_rest_kms_key_arn = aws_kms_key.msk.arn
    encryption_in_transit {
      client_broker = "TLS"
      in_cluster    = true
    }
  }

  client_authentication {
    sasl {
      iam = true
    }
  }

  enhanced_monitoring = "DEFAULT"

  tags = merge(var.tags, { Name = "${var.name_prefix}-msk" })
}
