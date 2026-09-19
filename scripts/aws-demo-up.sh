#!/usr/bin/env bash

set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

AWS_PROFILE_NAME="${AWS_PROFILE:-agentabi-cli-user}"
AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_ACCOUNT_ID="719429929317"
CLUSTER="agentabi-dev-eks"
NAMESPACE="agentabi"
EKS_ROLE_ARN="arn:aws:iam::719429929317:role/agentabi-dev-eks-admin"

unset AWS_ACCESS_KEY_ID
unset AWS_SECRET_ACCESS_KEY
unset AWS_SESSION_TOKEN
unset AWS_SECURITY_TOKEN
unset AWS_CREDENTIAL_EXPIRATION

export AWS_PROFILE="$AWS_PROFILE_NAME"
export AWS_REGION
export AWS_DEFAULT_REGION="$AWS_REGION"

echo "=== AgentABI AWS Demo Up ==="
echo

echo "1. Connecting kubectl to EKS..."

aws eks update-kubeconfig \
  --name "$CLUSTER" \
  --region "$AWS_REGION" \
  --role-arn "$EKS_ROLE_ARN"

echo
echo "2. Resolving image tag..."

if [ -n "${IMAGE_TAG:-}" ]; then
  TAG="$IMAGE_TAG"
else
  CURRENT_IMAGE="$(kubectl get deployment agentabi-api \
    -n "$NAMESPACE" \
    -o jsonpath='{.spec.template.spec.containers[0].image}' \
    2>/dev/null || true)"

  if [ -n "$CURRENT_IMAGE" ] && [[ "$CURRENT_IMAGE" == *:* ]]; then
    TAG="${CURRENT_IMAGE##*:}"
  else
    TAG="$(git rev-parse --short=12 HEAD)"
  fi
fi

echo "Using image tag: $TAG"

echo
echo "3. Deploying/restoring AgentABI workloads..."

helm upgrade --install agentabi \
  deploy/helm/agentabi \
  --namespace "$NAMESPACE" \
  --create-namespace \
  --values deploy/helm/agentabi/values-aws-dev.yaml \
  --set image.registry="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com" \
  --set image.tag="$TAG" \
  --rollback-on-failure \
  --wait \
  --timeout 15m

echo
echo "4. Verifying workloads..."

kubectl rollout status \
  deployment/agentabi-api \
  -n "$NAMESPACE" \
  --timeout=300s

kubectl rollout status \
  deployment/agentabi-worker \
  -n "$NAMESPACE" \
  --timeout=300s

kubectl rollout status \
  deployment/agentabi-frontend \
  -n "$NAMESPACE" \
  --timeout=300s

kubectl rollout status \
  statefulset/agentabi-kafka \
  -n "$NAMESPACE" \
  --timeout=600s

kubectl rollout status \
  statefulset/agentabi-neo4j \
  -n "$NAMESPACE" \
  --timeout=600s

echo
echo "5. Verifying API readiness..."

kubectl port-forward \
  -n "$NAMESPACE" \
  service/agentabi-api \
  18000:80 >/tmp/agentabi-up-portforward.log 2>&1 &

PF_PID=$!

cleanup() {
  kill "$PF_PID" 2>/dev/null || true
  wait "$PF_PID" 2>/dev/null || true
}
trap cleanup EXIT

sleep 5

READY="$(curl -fsS \
  --connect-timeout 5 \
  --max-time 15 \
  http://127.0.0.1:18000/api/v1/ready)"

echo "$READY"

echo "$READY" | grep -q '"database":true'
echo "$READY" | grep -q '"graph":true'
echo "$READY" | grep -q '"kafka":true'

echo
echo "======================================"
echo "AGENTABI AWS DEMO IS READY"
echo "======================================"
