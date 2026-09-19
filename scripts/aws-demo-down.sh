#!/usr/bin/env bash

set -euo pipefail

AWS_PROFILE_NAME="${AWS_PROFILE:-agentabi-cli-user}"
AWS_REGION="${AWS_REGION:-us-east-1}"
CLUSTER="agentabi-dev-eks"
NAMESPACE="agentabi"
EKS_ROLE_ARN="arn:aws:iam::719429929317:role/agentabi-dev-eks-admin"

if [ "${1:-}" != "--yes" ]; then
  echo "This pauses AgentABI Kubernetes workloads."
  echo
  echo "It preserves:"
  echo "  - EKS infrastructure"
  echo "  - RDS PostgreSQL"
  echo "  - ElastiCache/Valkey"
  echo "  - Helm release"
  echo "  - Neo4j PVC"
  echo "  - Kafka PVC"
  echo "  - AWS Secrets Manager secrets"
  echo
  echo "AWS infrastructure may continue to incur charges."
  echo
  echo "Run:"
  echo "  ./scripts/aws-demo-down.sh --yes"
  exit 1
fi

unset AWS_ACCESS_KEY_ID
unset AWS_SECRET_ACCESS_KEY
unset AWS_SESSION_TOKEN
unset AWS_SECURITY_TOKEN
unset AWS_CREDENTIAL_EXPIRATION

export AWS_PROFILE="$AWS_PROFILE_NAME"
export AWS_REGION
export AWS_DEFAULT_REGION="$AWS_REGION"

echo "=== AgentABI AWS Demo Down ==="
echo

echo "1. Connecting kubectl to EKS..."

aws eks update-kubeconfig \
  --name "$CLUSTER" \
  --region "$AWS_REGION" \
  --role-arn "$EKS_ROLE_ARN" >/dev/null

echo
echo "2. Scaling stateless workloads to zero..."

kubectl scale deployment \
  agentabi-api \
  agentabi-worker \
  agentabi-frontend \
  -n "$NAMESPACE" \
  --replicas=0

echo
echo "3. Scaling stateful workloads to zero..."

kubectl scale statefulset \
  agentabi-kafka \
  agentabi-neo4j \
  -n "$NAMESPACE" \
  --replicas=0

echo
echo "4. Waiting for pods to terminate..."

kubectl wait \
  --for=delete \
  pod \
  -n "$NAMESPACE" \
  --all \
  --timeout=180s || true

echo
echo "5. Current workload state..."

kubectl get deployment,statefulset \
  -n "$NAMESPACE"

echo
echo "PVCs remain preserved:"

kubectl get pvc \
  -n "$NAMESPACE"

echo
echo "======================================"
echo "AGENTABI AWS DEMO WORKLOADS ARE PAUSED"
echo "AWS INFRASTRUCTURE REMAINS PROVISIONED"
echo "======================================"
