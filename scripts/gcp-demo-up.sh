#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

PROJECT_ID="agentabi-demo-2026"
REGION="us-east1"
CLUSTER="agentabi-demo-gke"
NAMESPACE="agentabi"
SQL_INSTANCE="agentabi-demo-postgres"
REGISTRY="${REGION}-docker.pkg.dev/${PROJECT_ID}/agentabi"
IMAGE_TAG="${IMAGE_TAG:-demo-current}"
TF_DIR="infra/terraform/gcp/environments/demo"
PUBLIC_IP="8.233.188.40"

echo "=== AgentABI Demo Up ==="

echo
echo "1. Starting Cloud SQL..."

gcloud sql instances patch "$SQL_INSTANCE" \
  --project "$PROJECT_ID" \
  --activation-policy=ALWAYS \
  --quiet

echo
echo "2. Recreating/repairing Terraform-managed infrastructure..."

terraform -chdir="$TF_DIR" init -input=false

terraform -chdir="$TF_DIR" apply \
  -auto-approve \
  -input=false

echo
echo "3. Connecting kubectl to GKE..."

gcloud container clusters get-credentials "$CLUSTER" \
  --region "$REGION" \
  --project "$PROJECT_ID"

POSTGRES_HOST="$(
  terraform -chdir="$TF_DIR" output -raw cloud_sql_private_ip
)"

if [ -z "$POSTGRES_HOST" ]; then
  echo "ERROR: Cloud SQL private IP is empty."
  exit 1
fi

echo
echo "4. Creating namespace..."

kubectl create namespace "$NAMESPACE" \
  --dry-run=client \
  -o yaml | kubectl apply -f -

echo
echo "5. Restoring runtime secrets from Secret Manager..."

OPENAI_API_KEY="$(
  gcloud secrets versions access latest \
    --secret=agentabi-demo-openai-api-key \
    --project="$PROJECT_ID"
)"

JWT_SECRET="$(
  gcloud secrets versions access latest \
    --secret=agentabi-demo-jwt-signing-key \
    --project="$PROJECT_ID"
)"

GITHUB_OAUTH_CLIENT_ID="$(
  gcloud secrets versions access latest \
    --secret=agentabi-demo-github-oauth-client-id \
    --project="$PROJECT_ID"
)"

GITHUB_OAUTH_CLIENT_SECRET="$(
  gcloud secrets versions access latest \
    --secret=agentabi-demo-github-oauth-client-secret \
    --project="$PROJECT_ID"
)"

POSTGRES_PASSWORD="$(
  gcloud secrets versions access latest \
    --secret=agentabi-demo-postgres-password \
    --project="$PROJECT_ID"
)"

NEO4J_PASSWORD="$(
  gcloud secrets versions access latest \
    --secret=agentabi-demo-neo4j-password \
    --project="$PROJECT_ID"
)"

kubectl -n "$NAMESPACE" create secret generic agentabi-secrets \
  --from-literal=OPENAI_API_KEY="$OPENAI_API_KEY" \
  --from-literal=JWT_SECRET="$JWT_SECRET" \
  --from-literal=POSTGRES_USER=agentabi \
  --from-literal=POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
  --from-literal=NEO4J_PASSWORD="$NEO4J_PASSWORD" \
  --from-literal=NEO4J_AUTH="neo4j/${NEO4J_PASSWORD}" \
  --from-literal=GITHUB_OAUTH_CLIENT_ID="$GITHUB_OAUTH_CLIENT_ID" \
  --from-literal=GITHUB_OAUTH_CLIENT_SECRET="$GITHUB_OAUTH_CLIENT_SECRET" \
  --dry-run=client \
  -o yaml | kubectl apply -f -

unset OPENAI_API_KEY
unset JWT_SECRET
unset GITHUB_OAUTH_CLIENT_ID
unset GITHUB_OAUTH_CLIENT_SECRET
unset POSTGRES_PASSWORD
unset NEO4J_PASSWORD

echo
echo "6. Deploying AgentABI..."

helm upgrade --install agentabi \
  deploy/helm/agentabi \
  --namespace "$NAMESPACE" \
  --values deploy/helm/agentabi/values-gcp.yaml \
  --set image.registry="$REGISTRY" \
  --set image.tag="$IMAGE_TAG" \
  --set gcp.postgresHost="$POSTGRES_HOST" \
  --set ingress.enabled=true \
  --wait \
  --timeout 20m

echo
echo "7. Verifying workloads..."

kubectl -n "$NAMESPACE" rollout status \
  deployment/agentabi-api \
  --timeout=600s

kubectl -n "$NAMESPACE" rollout status \
  deployment/agentabi-frontend \
  --timeout=600s

kubectl -n "$NAMESPACE" rollout status \
  deployment/agentabi-worker \
  --timeout=600s

kubectl -n "$NAMESPACE" get pods

echo
echo "8. Waiting for public load balancer..."

READY=0

for i in $(seq 1 60); do
  CODE="$(
    curl -s \
      -o /tmp/agentabi-ready.json \
      -w '%{http_code}' \
      --connect-timeout 5 \
      --max-time 15 \
      "http://${PUBLIC_IP}/api/v1/ready" || true
  )"

  echo "Attempt $i/60: HTTP $CODE"

  if [ "$CODE" = "200" ]; then
    READY=1
    break
  fi

  sleep 10
done

if [ "$READY" -ne 1 ]; then
  echo "ERROR: public demo did not become ready."
  exit 1
fi

cat /tmp/agentabi-ready.json
echo

echo
echo "======================================"
echo "AGENTABI DEMO IS LIVE"
echo "http://${PUBLIC_IP}/"
echo "======================================"
