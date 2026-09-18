#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="agentabi-demo-2026"
REGION="us-east1"
CLUSTER="agentabi-demo-gke"
SQL_INSTANCE="agentabi-demo-postgres"
NAMESPACE="agentabi"

if [ "${1:-}" != "--yes" ]; then
  echo "This shuts down the AgentABI demo."
  echo
  echo "Run:"
  echo "  ./scripts/gcp-demo-down.sh --yes"
  exit 1
fi

echo "=== AgentABI Demo Down ==="

if gcloud container clusters describe "$CLUSTER" \
  --region "$REGION" \
  --project "$PROJECT_ID" >/dev/null 2>&1
then
  echo
  echo "Connecting to GKE..."

  gcloud container clusters get-credentials "$CLUSTER" \
    --region "$REGION" \
    --project "$PROJECT_ID" >/dev/null

  echo
  echo "Removing public Ingress first..."
  kubectl -n "$NAMESPACE" delete ingress agentabi \
    --ignore-not-found \
    --wait=false || true

  echo "Allowing load-balancer cleanup to begin..."
  sleep 30

  echo
  echo "Deleting GKE Autopilot cluster..."
  gcloud container clusters delete "$CLUSTER" \
    --region "$REGION" \
    --project "$PROJECT_ID" \
    --quiet
else
  echo "GKE cluster already absent."
fi

echo
echo "Stopping Cloud SQL while preserving database data..."

gcloud sql instances patch "$SQL_INSTANCE" \
  --project "$PROJECT_ID" \
  --activation-policy=NEVER \
  --quiet

echo
echo "Cloud SQL activation policy:"
gcloud sql instances describe "$SQL_INSTANCE" \
  --project "$PROJECT_ID" \
  --format='value(settings.activationPolicy)'

echo
echo "======================================"
echo "AGENTABI DEMO IS OFF"
echo "======================================"
