output "vpc_id" {
  value = aws_vpc.this.id
}

output "vpc_cidr_block" {
  value = aws_vpc.this.cidr_block
}

output "public_subnet_ids" {
  value = aws_subnet.public[*].id
}

output "private_app_subnet_ids" {
  value = aws_subnet.private_app[*].id
}

output "private_data_subnet_ids" {
  value = aws_subnet.private_data[*].id
}

output "nat_gateway_ids" {
  value = aws_nat_gateway.this[*].id
}

output "nat_gateway_count" {
  value       = local.nat_gateway_count
  description = "Actual number of NAT Gateways created — useful for cost-awareness in plan output review."
}
