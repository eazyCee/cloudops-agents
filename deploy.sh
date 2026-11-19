#!/usr/bin/env bash
# ==============================================================================
# One-Command Deployment Script for Google Cloud FinOps + CloudOps ADK Agent
# ==============================================================================
# Usage:
#   ./deploy.sh                                 # Deploy to Cloud Run (readonly mode)
#   ./deploy.sh --project MY_PROJ --region us-central1 --mode readwrite
#   ./deploy.sh --project MY_PROJ --billing-account 01ABCD-234567-89EFGH --iap
#   ./deploy.sh local                           # Run locally on http://localhost:8000
#   ./deploy.sh teardown --project MY_PROJ      # Delete the Cloud Run service
#   ./deploy.sh --dry-run                       # Preview all gcloud commands first
# ==============================================================================

set -euo pipefail

COMMAND="cloud-run"
PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-}"
REGION="${GOOGLE_CLOUD_REGION:-us-central1}"
LOCATION="${GOOGLE_CLOUD_LOCATION:-global}"
SERVICE_NAME="${SERVICE_NAME:-cloudops}"
SA_NAME="${SA_NAME:-cloudops-finops-agent-sa}"
MODEL_NAME="${GEMINI_MODEL:-gemini-2.5-flash}"
MODE="${AGENT_EXECUTION_MODE:-readonly}"
BILLING_ACCOUNT_ID="${BILLING_ACCOUNT_ID:-}"
USE_IAP="false"
ALLOW_UNAUTH="false"
DRY_RUN="false"

# Parse optional positional subcommand first
if [[ $# -gt 0 && "${1:-}" != --* ]]; then
  case "$1" in
    cloud-run|local|teardown|help)
      COMMAND="$1"
      shift
      ;;
  esac
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)          PROJECT_ID="$2"; shift 2 ;;
    --region)           REGION="$2"; shift 2 ;;
    --location)         LOCATION="$2"; shift 2 ;;
    --service-name)     SERVICE_NAME="$2"; shift 2 ;;
    --model)            MODEL_NAME="$2"; shift 2 ;;
    --mode)             MODE="$2"; shift 2 ;;
    --billing-account)  BILLING_ACCOUNT_ID="$2"; shift 2 ;;
    --iap)              USE_IAP="true"; shift ;;
    --allow-unauthenticated) ALLOW_UNAUTH="true"; shift ;;
    --dry-run)          DRY_RUN="true"; shift ;;
    -h|--help)          COMMAND="help"; shift ;;
    *)
      echo "Unknown option: $1"
      echo "Run './deploy.sh --help' for usage."
      exit 1
      ;;
  esac
done

print_help() {
  cat <<'EOF'
Google Cloud FinOps + CloudOps ADK Agent — Simplified Customer Deployer

Commands:
  cloud-run (default)   Enable APIs, provision least-privilege SA + IAM, and deploy to Cloud Run
  local                 Create local Python venv and launch ADK Web UI on http://localhost:8000
  teardown              Delete the deployed Cloud Run service

Options:
  --project ID          Target GCP Project ID (defaults to active gcloud config project)
  --region REGION       Cloud Run region (default: us-central1)
  --location LOC        Vertex AI Gemini endpoint location (default: global)
  --service-name NAME   Cloud Run service name (default: cloudops)
  --model MODEL         Gemini model name (default: gemini-2.5-flash)
  --mode MODE           'readonly' (default, safe inspection + IaC) or 'readwrite' (allows remediation)
  --billing-account ID  Optional Billing Account ID (enables CUD & negotiated pricing lookups)
  --iap                 Enable Identity-Aware Proxy (IAP) on Cloud Run for browser SSO
  --allow-unauthenticated Allow public unauthenticated access (demos only; default is private)
  --dry-run             Print every command without executing changes
EOF
}

if [[ "$COMMAND" == "help" ]]; then
  print_help
  exit 0
fi

if [[ "$MODE" != "readonly" && "$MODE" != "readwrite" ]]; then
  echo "Error: --mode must be 'readonly' or 'readwrite' (got: $MODE)"
  exit 1
fi

run_cmd() {
  if [[ "$DRY_RUN" == "true" ]]; then
    printf '[DRY-RUN] '
    printf '%q ' "$@"
    printf '\n'
  else
    "$@"
  fi
}

run_cmd_quiet() {
  if [[ "$DRY_RUN" == "true" ]]; then
    printf '[DRY-RUN] '
    printf '%q ' "$@"
    printf '\n'
  else
    "$@" >/dev/null
  fi
}

require_gcloud() {
  if ! command -v gcloud >/dev/null 2>&1; then
    echo "Error: 'gcloud' CLI is not installed. Install Google Cloud SDK first."
    exit 1
  fi
  if [[ -z "$PROJECT_ID" ]]; then
    PROJECT_ID="$(gcloud config get-value project 2>/dev/null || true)"
  fi
  if [[ -z "$PROJECT_ID" || "$PROJECT_ID" == "(unset)" ]]; then
    echo "Error: No GCP project configured. Pass --project YOUR_PROJECT_ID or run 'gcloud config set project YOUR_PROJECT_ID'."
    exit 1
  fi
}

# ==============================================================================
# LOCAL RUN MODE
# ==============================================================================
if [[ "$COMMAND" == "local" ]]; then
  require_gcloud
  echo "==> Setting up local Python environment for project: $PROJECT_ID"
  PYTHON_BIN="$(command -v python3 || command -v python)"
  if [[ ! -d ".venv" ]]; then
    run_cmd "$PYTHON_BIN" -m venv .venv
  fi
  run_cmd .venv/bin/pip install --upgrade pip -q
  run_cmd .venv/bin/pip install -r requirements.txt -q

  if [[ ! -f "app/.env" && ! -f ".env" ]]; then
    echo "==> Generating local .env (mode=$MODE, model=$MODEL_NAME)"
    if [[ "$DRY_RUN" == "false" ]]; then
      cat > .env <<EOF
GOOGLE_GENAI_USE_VERTEXAI=True
GOOGLE_CLOUD_PROJECT=${PROJECT_ID}
GOOGLE_CLOUD_LOCATION=${LOCATION}
GEMINI_MODEL=${MODEL_NAME}
AGENT_EXECUTION_MODE=${MODE}
BILLING_ACCOUNT_ID=${BILLING_ACCOUNT_ID}
EOF
    fi
  fi

  echo "==> Checking Application Default Credentials (ADC)..."
  if [[ "$DRY_RUN" == "false" ]] && ! gcloud auth application-default print-access-token >/dev/null 2>&1; then
    echo "ADC not found. Running 'gcloud auth application-default login'..."
    gcloud auth application-default login
  fi

  echo ""
  echo "==> Starting ADK Web UI locally at http://127.0.0.1:8000 (Ctrl+C to stop)"
  run_cmd .venv/bin/adk web --host 127.0.0.1 --port 8000 .
  exit 0
fi

# ==============================================================================
# TEARDOWN MODE
# ==============================================================================
if [[ "$COMMAND" == "teardown" ]]; then
  require_gcloud
  echo "==> Deleting Cloud Run service '$SERVICE_NAME' in $PROJECT_ID ($REGION)..."
  run_cmd gcloud run services delete "$SERVICE_NAME" \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --quiet
  echo "Done. Service account '${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com' was preserved."
  exit 0
fi

# ==============================================================================
# CLOUD RUN ONE-COMMAND DEPLOYMENT
# ==============================================================================
require_gcloud
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "=================================================================="
echo " Deploying Google Cloud FinOps + CloudOps ADK Agent to Cloud Run"
echo "=================================================================="
echo " Project:         $PROJECT_ID"
echo " Region:          $REGION"
echo " Service Name:    $SERVICE_NAME"
echo " Service Account: $SA_EMAIL"
echo " Gemini Model:    $MODEL_NAME (Vertex AI location: $LOCATION)"
echo " Safety Mode:     $MODE"
echo " Billing Acct:    ${BILLING_ACCOUNT_ID:-<none - project scope only>}"
echo " IAP Enabled:     $USE_IAP"
echo "=================================================================="

echo ""
echo "[1/4] Enabling required Google Cloud APIs (also enables Remote MCP endpoints)..."
APIS=(
  aiplatform.googleapis.com
  run.googleapis.com
  cloudbuild.googleapis.com
  artifactregistry.googleapis.com
  recommender.googleapis.com
  cloudbilling.googleapis.com
  monitoring.googleapis.com
  logging.googleapis.com
  compute.googleapis.com
  container.googleapis.com
  bigquery.googleapis.com
)
run_cmd gcloud services enable "${APIS[@]}" --project="$PROJECT_ID"

echo ""
echo "[2/4] Creating dedicated least-privilege runtime Service Account..."
if [[ "$DRY_RUN" == "true" ]]; then
  run_cmd gcloud iam service-accounts create "$SA_NAME" \
    --project="$PROJECT_ID" \
    --display-name="CloudOps & FinOps ADK Agent"
elif ! gcloud iam service-accounts describe "$SA_EMAIL" --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$SA_NAME" \
    --project="$PROJECT_ID" \
    --display-name="CloudOps & FinOps ADK Agent"
else
  echo "Service account already exists: $SA_EMAIL"
fi

echo ""
echo "[3/4] Binding least-privilege IAM roles (mode=$MODE)..."
READONLY_ROLES=(
  roles/aiplatform.user
  roles/recommender.viewer
  roles/monitoring.viewer
  roles/logging.viewer
  roles/compute.viewer
  roles/container.viewer
  roles/run.viewer
  roles/bigquery.dataViewer
  roles/bigquery.jobUser
)

READWRITE_EXTRA_ROLES=(
  roles/recommender.computeAdmin
  roles/recommender.cloudsqlAdmin
  roles/recommender.runAdmin
  roles/compute.instanceAdmin.v1
  roles/container.developer
  roles/run.developer
)

ROLES_TO_BIND=("${READONLY_ROLES[@]}")
if [[ "$MODE" == "readwrite" ]]; then
  ROLES_TO_BIND+=("${READWRITE_EXTRA_ROLES[@]}")
fi

for role in "${ROLES_TO_BIND[@]}"; do
  echo "  -> Granting $role"
  run_cmd_quiet gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="$role" \
    --condition=None \
    --quiet
done

if [[ -n "$BILLING_ACCOUNT_ID" ]]; then
  echo "  -> Granting Billing & CUD Viewer roles on Billing Account: $BILLING_ACCOUNT_ID"
  for brole in roles/billing.viewer roles/recommender.billingAccountCudViewer; do
    run_cmd_quiet gcloud billing accounts add-iam-policy-binding "$BILLING_ACCOUNT_ID" \
      --member="serviceAccount:${SA_EMAIL}" \
      --role="$brole" \
      --quiet || echo "  (Warning: Could not bind $brole on billing account; ask a Billing Account Admin to grant it.)"
  done
fi

echo ""
echo "[4/4] Building & deploying container to Cloud Run..."
ENV_VARS="GOOGLE_GENAI_USE_VERTEXAI=True,GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=${LOCATION},GEMINI_MODEL=${MODEL_NAME},AGENT_EXECUTION_MODE=${MODE}"
if [[ -n "$BILLING_ACCOUNT_ID" ]]; then
  ENV_VARS="${ENV_VARS},BILLING_ACCOUNT_ID=${BILLING_ACCOUNT_ID}"
fi

DEPLOY_ARGS=(
  gcloud run deploy "$SERVICE_NAME"
  --source .
  --project="$PROJECT_ID"
  --region="$REGION"
  --service-account="$SA_EMAIL"
  --port=8080
  --memory=2Gi
  --cpu=1
  --concurrency=8
  --min-instances=0
  --max-instances=5
  --timeout=300
  --set-env-vars="$ENV_VARS"
)

if [[ "$ALLOW_UNAUTH" == "true" ]]; then
  DEPLOY_ARGS+=(--allow-unauthenticated)
else
  DEPLOY_ARGS+=(--no-allow-unauthenticated)
fi

if [[ "$USE_IAP" == "true" ]]; then
  DEPLOY_ARGS+=(--iap)
fi

run_cmd "${DEPLOY_ARGS[@]}"

echo ""
echo "=================================================================="
echo " Deployment Complete!"
echo "=================================================================="
if [[ "$USE_IAP" == "true" ]]; then
  echo "Open your Cloud Run URL in the browser (protected by Identity-Aware Proxy)."
  echo "Ensure authorized users have 'IAP-secured Web App User' on the service."
elif [[ "$ALLOW_UNAUTH" == "true" ]]; then
  echo "Open your Cloud Run service URL directly in the browser."
else
  echo "Your Cloud Run service is private (--no-allow-unauthenticated)."
  echo "To open the ADK Web UI securely in your browser right now, run:"
  echo ""
  echo "  gcloud run services proxy ${SERVICE_NAME} --project=${PROJECT_ID} --region=${REGION} --port=8080"
  echo ""
  echo "Then open: http://localhost:8080"
fi
echo "=================================================================="
