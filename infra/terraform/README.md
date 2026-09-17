# AgentABI — Terraform AWS Infrastructure (Phase 17)

Infrastructure-as-code for AgentABI's AWS deployment target. **This is
infrastructure preparation only** — no AWS resources have been created by
writing this code, and no `terraform apply` has been run against AWS as
part of Phase 17. Actual Kubernetes application deployment (AgentABI
API/worker/frontend, Neo4j) is Phase 18, not this phase.

## Why this exists (see also ADR-086 in docs/DECISIONS.md)

AgentABI is a recruiter/portfolio project. The AWS environment is
provisioned on demand for a demo/interview and destroyed or scaled down
afterward — it does not run 24/7. Every design choice below is made with
that lifecycle in mind: reproducible, disposable where appropriate,
cost-conscious, but still genuinely production-architected. Nothing here
is a toy — EKS, RDS, ElastiCache and MSK are real managed services wired
together the way a production deployment would be; the *lifecycle* around
them (start for a demo, tear down after) is what's tuned for cost, not the
architecture itself.

## Architecture

```
Internet
   |
Route53 (optional) / ACM (optional)
   |
AWS Load Balancer Controller -> ALB           [Phase 18 deploys the controller + Ingress]
   |
Amazon EKS (private worker nodes, public API endpoint by default for demo access)
   |
   +-- AgentABI Frontend / API / Worker pods    [Phase 18]
   +-- Neo4j (EBS-backed StatefulSet)           [Phase 18]
   |
   +-- Amazon RDS PostgreSQL       (private data subnets)
   +-- ElastiCache (Redis/Valkey)  (private data subnets)
   +-- Amazon MSK                  (private data subnets)
   +-- AWS Secrets Manager         (empty containers; values populated out-of-band)
   +-- ECR                         (agentabi-api / agentabi-worker / agentabi-frontend)
   +-- CloudWatch                  (EKS control-plane logs; app-level OTel/Prometheus per docs/ARCHITECTURE.md)
```

## Module responsibilities

| Module | Creates |
|---|---|
| `modules/networking` | VPC, public/private-app/private-data subnets across N AZs, IGW, configurable NAT (1 shared or 1/AZ), route tables, locked-down default SG |
| `modules/eks` | EKS cluster (KMS-encrypted secrets), OIDC provider for IRSA, one managed node group, cluster + node IAM roles, CloudWatch log group |
| `modules/iam` | IRSA roles: AWS Load Balancer Controller, EBS CSI driver, cluster-autoscaler, AgentABI app workload (scoped ECR pull + Secrets Manager read), optional external-dns |
| `modules/ecr` | 3 repositories, image scanning on push, lifecycle policies |
| `modules/rds` | Private PostgreSQL, AWS-managed master password (Secrets Manager), configurable sizing/Multi-AZ/snapshot behavior |
| `modules/redis` | Private ElastiCache (Redis or Valkey) replication group |
| `modules/msk` | Private MSK — serverless (default) or provisioned, selectable |
| `modules/secrets` | Empty Secrets Manager containers for app secrets (no values) |
| `modules/dns` | Optional Route53 hosted zone + ACM certificate, fully skippable |

`environments/dev` wires all of the above together with cost-conscious
defaults. `bootstrap/` is a separate, tiny root module for the remote
state backend (see below) — never applied as part of `dev`.

## Network topology & security model

Three subnet tiers per AZ: **public** (ALB, NAT Gateways only),
**private-app** (EKS worker nodes — no public IPs, no direct internet
route except via NAT), **private-data** (RDS/ElastiCache/MSK — no NAT
route needed at all, since these services never initiate outbound internet
traffic). RDS, ElastiCache and MSK security groups all allow ingress only
from the EKS cluster's additional security group — nothing is publicly
reachable, and the VPC's default security group is explicitly locked to
deny-all.

### Networking cost trade-off

NAT Gateway is billed per-hour-provisioned regardless of traffic, plus
data processing — one of the few "always costs money while it exists"
resources here. `single_nat_gateway = true` (the `dev` default) provisions
exactly one NAT Gateway for the whole VPC: cheapest, but if that AZ has an
outage, private-subnet egress is briefly unavailable — acceptable for a
demo environment that's up for a few hours. `single_nat_gateway = false`
provisions one per AZ (production posture, no cross-AZ egress dependency,
proportionally more NAT cost). See `terraform.tfvars.example` for both.

## IAM: IRSA, not node-wide permissions

Every AWS-facing workload gets its own IAM role, assumable only by its own
Kubernetes ServiceAccount via the cluster's OIDC provider (IRSA) — never a
broad node-instance role. `modules/iam` prepares roles for the AWS Load
Balancer Controller, the EBS CSI driver, cluster-autoscaler, and AgentABI's
own API/worker pods (scoped to *only* AgentABI's ECR repos and Secrets
Manager secrets — no wildcard resource access, no `AdministratorAccess`
anywhere). Phase 18 annotates each ServiceAccount with the corresponding
`eks.amazonaws.com/role-arn` output.

## GitHub Actions → AWS (OIDC)

`modules/github-oidc` (Phase 18) prepares the IAM side of CD: a GitHub
Actions OIDC identity provider and a `github-actions-deploy` IAM role that
`.github/workflows/deploy.yml` assumes via `aws-actions/configure-aws-credentials`'s
OIDC support. No `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` are ever
stored as GitHub secrets — every deploy run exchanges GitHub's own
short-lived OIDC token for temporary AWS credentials scoped to this one
role.

The module is disabled by default (`github_actions_oidc_enabled = false`)
because this repository has not been pushed to GitHub yet — GitHub push is
deliberately the project's last step, after security review (see
docs/DECISIONS.md's Phase 18 ADR). There is no real `github_org`/
`github_repository` to federate against yet, so nothing here is applied
until that changes. Once the repository is pushed:

1. Set `github_actions_oidc_enabled = true`, `github_org`, and
   `github_repository` in `terraform.tfvars` (real values — never
   placeholders).
2. Review/narrow `github_actions_allowed_refs` (default
   `["refs/heads/main"]`) and `github_actions_allowed_environments`
   (default `["demo"]`) — the trust policy only accepts an OIDC token
   whose subject matches one of these exactly (`StringLike`, never a
   wildcard `repo:org/*`).
3. `terraform apply`, then set the resulting `github_actions_deploy_role_arn`
   output as the `AWS_DEPLOY_ROLE_ARN` GitHub repository **variable**
   (not secret — an IAM role ARN isn't sensitive) alongside
   `AWS_REGION`, `EKS_CLUSTER_NAME`, `ECR_REGISTRY`, and
   `NEXT_PUBLIC_AGENTABI_API_URL` — see deploy.yml's header comment for
   the full prerequisite list.
4. Create a GitHub Environment named `demo` with required reviewers, so
   deploy.yml's `environment: demo` pauses for a human approval before
   anything touches AWS.

The role's permissions are narrow: push to AgentABI's three ECR
repositories, `eks:DescribeCluster` (needed for
`aws eks update-kubeconfig`), and cluster RBAC scoped to the `agentabi`
namespace only, granted via an EKS Access Entry
(`aws_eks_access_entry` + `aws_eks_access_policy_association`,
`AmazonEKSEditPolicy` — not cluster-admin, not the legacy aws-auth
ConfigMap). `modules/eks` sets `authentication_mode = API_AND_CONFIG_MAP`
so Access Entries work without a Kubernetes/Helm Terraform provider.

## Secrets strategy

Terraform never contains, generates, or stores an application secret
value:

- **RDS master password**: `manage_master_user_password = true` — AWS
  creates and rotates it in Secrets Manager directly; Terraform only
  references the resulting secret ARN.
- **JWT signing key, OpenAI API key, GitHub OAuth/App credentials**:
  `modules/secrets` creates empty `aws_secretsmanager_secret` containers
  only. Populate real values after `apply`, out-of-band:
  ```bash
  aws secretsmanager put-secret-value \
    --secret-id agentabi-dev/openai-api-key \
    --secret-string '<value>'
  ```
  Never put these in `terraform.tfvars`, never add an
  `aws_secretsmanager_secret_version` resource for them.
- **ElastiCache AUTH token**: disabled by default (`enable_auth_token =
  false`) — the demo relies on network isolation (private subnet, SG
  scoped to the EKS cluster) rather than generating a token Terraform
  would have to hold in state. Can be enabled with a token supplied via a
  pre-populated Secrets Manager secret if needed.

Local `.env` secrets used for docker-compose development are never copied
into Terraform.

## Remote state strategy

Local state is the default — `terraform init` / `plan` / `validate` all
work with zero AWS access, satisfying "local validation must still be
possible with backend disabled."

Remote state (S3 + DynamoDB lock table) is opt-in via `bootstrap/`, a
separate root module that must be applied once, by itself, with local
state — this avoids the circular dependency of a backend that depends on
infrastructure managed through that same backend:

```bash
cd infra/terraform/bootstrap
terraform init
terraform apply -var="bucket_suffix=<something-unique-e.g.-your-account-id>"
# note the bucket_name / lock_table_name outputs
```

Then uncomment and fill in the `backend "s3" {}` block in
`environments/dev/versions.tf` and run `terraform init -migrate-state`.

Neither this apply nor any other has been run in Phase 17.

## MSK cost warning

MSK is typically the single most expensive component in this stack.
`msk_deployment_mode = "serverless"` (the `dev` default) avoids paying for
fixed broker instances that sit idle between demos — billed by
cluster-hours/partition-hours/throughput actually used instead.
`"provisioned"` is the classic always-on broker-per-AZ deployment
(production-typical, but bills continuously whether or not anything is
produced/consumed) — kept fully supported so the architecture stays
production-credible; Kafka/MSK is not swapped for a cheaper substitute
technology. No dollar figures are asserted here — see the [MSK pricing
page](https://aws.amazon.com/msk/pricing/) and [AWS Pricing
Calculator](https://calculator.aws/).

## Demo lifecycle

### START / PROVISION
```bash
cd infra/terraform/environments/dev
terraform init
terraform plan
terraform apply
# Phase 18: kubectl/helm-deploy AgentABI + Neo4j onto the new cluster
# populate Secrets Manager values (see "Secrets strategy" above)
# verify: kubectl get pods, hit the ALB/health endpoint
```

### DEMO
Run the recruiter/interview walkthrough; use the existing
OpenTelemetry/Prometheus/Grafana/structured-logging stack (docs/ARCHITECTURE.md)
to show real observability, not screenshots.

### SHUTDOWN / COST CONTROL
Stopping AWS charges is **not** the same as scaling down — most of this
stack has no "stopped, free" state. What can be scaled vs. must be
destroyed:

| Resource | Scale down | Must destroy to stop charges |
|---|---|---|
| EKS node group | `desired_size = 0` stops EC2 compute charges | — |
| EKS control plane | — | yes, bills per-hour regardless of nodes |
| RDS | can stop for up to 7 days (`aws rds stop-db-instance`) | yes, beyond that AWS auto-restarts it |
| ElastiCache | no stop state | yes |
| MSK (serverless) | scales toward zero usage automatically | cluster itself still yes |
| MSK (provisioned) | no stop state | yes |
| NAT Gateway(s) | no stop state | yes |
| ALB (Phase 18) | no stop state | yes |
| EBS volumes / snapshots | — | yes (snapshots persist and bill even after the volume is gone) |
| S3 (state bucket), ECR, Route53 hosted zone | negligible, but not zero | optional — usually fine to leave |

### DESTROY
```bash
# if rds_deletion_protection = true, first: terraform apply -var="rds_deletion_protection=false"
terraform plan -destroy
terraform destroy
```
With `rds_skip_final_snapshot = false`, RDS leaves a final snapshot before
deletion (billed at normal snapshot storage rates until you delete it
too). With the default `true`, all RDS data is deleted permanently.

### RECREATE
```bash
terraform apply
# repopulate Secrets Manager values (they do not survive destroy)
# Phase 18: redeploy AgentABI + Neo4j
# optionally: aws rds restore-db-instance-from-db-snapshot from a preserved final snapshot
```

## Phase 17 / 18 / 19 boundary

Phase 17: VPC, EKS cluster + node group, IAM/IRSA foundations, ECR, RDS,
ElastiCache, MSK, empty Secrets Manager containers, optional DNS/ACM,
remote-state bootstrap module. **No Kubernetes objects, no Helm releases,
no application containers, no Neo4j, no CI/CD.**

Phase 18 (this phase): `.github/workflows/ci.yml` (lint/typecheck/test/
Terraform-validate/security-scan/Docker-build-only, on every push/PR) and
`.github/workflows/deploy.yml` (manual `workflow_dispatch` CD foundation);
`modules/github-oidc` (disabled by default — see above); the
`deploy/helm/agentabi` Helm chart (API, worker, frontend Deployments,
Neo4j StatefulSet, a `SecretProviderClass`, and a migration Job that runs
as a Helm pre-upgrade hook). **Still no real AWS deployment, no
`terraform apply` against real AWS, no image pushed to ECR, no repository
push to GitHub.**

Phase 19 (not started): actually `terraform apply` this configuration;
flip `github_actions_oidc_enabled = true` with real org/repo; install the
AWS Load Balancer Controller, cluster-autoscaler, EBS CSI driver, and
Secrets Store CSI Driver (AWS provider) cluster add-ons using the IAM
roles Phase 17 already created; populate real Secrets Manager values; run
`deploy.yml` for the first time.

## Validation

```bash
cd infra/terraform/environments/dev
terraform fmt -check -recursive ..
terraform init -backend=false
terraform validate
tflint   # if installed
```

See the Phase 17/18 completion reports in docs/ROADMAP.md for what was
actually run and what could not be run in the authoring sandbox (no
`terraform` binary available there — see docs/DECISIONS.md ADR-086/ADR-087).
