#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="agentabi-demo-2026"
REGION="us-east1"
CLUSTER="agentabi-demo-gke"
SQL_INSTANCE="agentabi-demo-postgres"
NAMESPACE="agentabi"
PUBLIC_IP="8.233.188.40"

echo "=== AgentABI GCP Demo Status ==="

echo
echo "Cloud SQL activation policy:"
gcloud sql instances describe "$SQL_INSTANCE" \
  --project "$PROJECT_ID" \
  --format='value(settings.activationPolicy)' 2>/dev/null || echo "NOT FOUND"

echo
echo "GKE:"
if gcloud container clusters describe "$CLUSTER" \
  --region "$REGION" \
  --project "$PROJECT_ID" >/dev/null 2>&1
then
  echo "RUNNING"

  gcloud container clusters get-credentials "$CLUSTER" \
    --region "$REGION" \
    --project "$PROJECT_ID" >/dev/null

  echo
  kubectl -n "$NAMESPACE" get pods 2>/dev/null || true

  echo
  echo "Public frontend:"
  curl -s -o /dev/null -w 'HTTP %{http_code}\n' \
    --connect-timeout 5 \
    --max-time 10 \
    "http://${PUBLIC_IP}/" || true

  echo "Public readiness:"
  curl -s -o /dev/null -w 'HTTP %{http_code}\n' \
    --connect-timeout 5 \
    --max-time 10 \
    "http://${PUBLIC_IP}/api/v1/ready" || true
else
  echo "OFFLINE"
fi
