#!/usr/bin/env bash

set -euo pipefail

AWS_PROFILE_NAME="${AWS_PROFILE:-agentabi-cli-user}"
AWS_REGION="${AWS_REGION:-us-east-1}"
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

echo "=== AgentABI AWS Demo Status ==="
echo

echo "EKS cluster:"
STATUS="$(aws eks describe-cluster \
  --name "$CLUSTER" \
  --region "$AWS_REGION" \
  --query 'cluster.status' \
  --output text 2>/dev/null || true)"

if [ -z "$STATUS" ] || [ "$STATUS" = "None" ]; then
  echo "NOT FOUND"
  exit 0
fi

echo "$STATUS"
echo

aws eks update-kubeconfig \
  --name "$CLUSTER" \
  --region "$AWS_REGION" \
  --role-arn "$EKS_ROLE_ARN" >/dev/null

echo "Helm release:"
helm status agentabi -n "$NAMESPACE" 2>/dev/null \
  | sed -n '1,10p' || echo "NOT DEPLOYED"

echo
echo "Pods:"
kubectl get pods -n "$NAMESPACE" 2>/dev/null || true

echo
echo "PVCs:"
kubectl get pvc -n "$NAMESPACE" 2>/dev/null || true

echo
echo "API readiness:"

kubectl port-forward \
  -n "$NAMESPACE" \
  service/agentabi-api \
  18000:80 >/tmp/agentabi-status-portforward.log 2>&1 &

PF_PID=$!

cleanup() {
  kill "$PF_PID" 2>/dev/null || true
  wait "$PF_PID" 2>/dev/null || true
}
trap cleanup EXIT

sleep 3

curl -fsS \
  --connect-timeout 5 \
  --max-time 10 \
  http://127.0.0.1:18000/api/v1/ready \
  || echo "API NOT READY"

echo
