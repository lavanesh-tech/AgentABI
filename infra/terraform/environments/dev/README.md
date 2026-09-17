# AgentABI — `dev` environment

Quick reference. Full architecture, security, cost, and lifecycle
documentation lives in [`infra/terraform/README.md`](../../README.md) —
read that first.

## Local validation (no AWS access required)

```bash
cd infra/terraform/environments/dev
terraform fmt -check -recursive ..
terraform init -backend=false
terraform validate
```

## Plan / apply (requires AWS credentials)

```bash
cp terraform.tfvars.example terraform.tfvars   # edit as needed
terraform init            # local state by default; see ../../README.md to switch to S3
terraform plan
terraform apply
```

## Destroy

```bash
terraform plan -destroy
terraform destroy
```

If `rds_deletion_protection = true` or `rds_skip_final_snapshot = false`,
read [`infra/terraform/README.md`](../../README.md)'s "Demo lifecycle —
DESTROY" section before destroying.

This environment creates infrastructure only. No AgentABI Kubernetes
workloads, no Neo4j — that is Phase 18.
