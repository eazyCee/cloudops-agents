#!/usr/bin/env bash
# ==============================================================================
# One-Command Deployment Script for Google Cloud FinOps + CloudOps ADK Agent
# Supports: Cloud Run, Vertex AI Agent Runtime (+ Gemini Enterprise), and Local
# ==============================================================================
# Usage:
#   ./deploy.sh                                        # Deploy to Cloud Run (readonly mode)
#   ./deploy.sh agent-runtime --project MY_PROJ        # Deploy to Vertex AI Agent Runtime
#   ./deploy.sh agent-runtime --project MY_PROJ --mode readwrite --ge-app-id "projects/.../engines/..."
#   ./deploy.sh publish-ge --ge-app-id "projects/.../engines/..."
#   ./deploy.sh local                                  # Run locally on http://localhost:8000
#   ./deploy.sh teardown --project MY_PROJ             # Delete Cloud Run service (or Agent Runtime)
#   ./deploy.sh --dry-run                              # Preview all commands first
# ==============================================================================

set -euo pipefail

COMMAND="cloud-run"
PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-}"
REGION="${GOOGLE_CLOUD_REGION:-us-central1}"
LOCATION="${GOOGLE_CLOUD_LOCATION:-global}"
SERVICE_NAME="${SERVICE_NAME:-cloudops}"
DISPLAY_NAME="${DISPLAY_NAME:-CloudOps & FinOps Agent}"
AGENT_DESCRIPTION="${AGENT_DESCRIPTION:-Google Cloud FinOps Hub and CloudOps orchestrator. Checks Recommender API, Cloud Billing, Cloud Monitoring, and Cloud Audit Logs before taking action on Compute Engine, GKE, or Cloud Run.}"
SA_NAME="${SA_NAME:-cloudops-finops-agent-sa}"
MODEL_NAME="${GEMINI_MODEL:-gemini-2.5-flash}"
MODE="${AGENT_EXECUTION_MODE:-readonly}"
BILLING_ACCOUNT_ID="${BILLING_ACCOUNT_ID:-}"
AGENT_ENGINE_ID="${AGENT_ENGINE_ID:-}"
AGENT_RUNTIME_ID="${AGENT_RUNTIME_ID:-}"
GE_APP_ID="${GEMINI_ENTERPRISE_APP_ID:-}"
USE_IAP="false"
ALLOW_UNAUTH="false"
DRY_RUN="false"

# Parse optional positional subcommand first
if [[ $# -gt 0 && "${1:-}" != --* ]]; then
  case "$1" in
    cloud-run|agent-runtime|publish-ge|local|teardown|help)
      COMMAND="$1"
      shift
      ;;
  esac
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)               PROJECT_ID="$2"; shift 2 ;;
    --region)                REGION="$2"; shift 2 ;;
    --location)              LOCATION="$2"; shift 2 ;;
    --service-name)          SERVICE_NAME="$2"; shift 2 ;;
    --display-name)          DISPLAY_NAME="$2"; shift 2 ;;
    --description)           AGENT_DESCRIPTION="$2"; shift 2 ;;
    --model)                 MODEL_NAME="$2"; shift 2 ;;
    --mode)                  MODE="$2"; shift 2 ;;
    --billing-account)       BILLING_ACCOUNT_ID="$2"; shift 2 ;;
    --agent-engine-id)       AGENT_ENGINE_ID="$2"; shift 2 ;;
    --agent-runtime-id)      AGENT_RUNTIME_ID="$2"; shift 2 ;;
    --ge-app-id)             GE_APP_ID="$2"; shift 2 ;;
    --iap)                   USE_IAP="true"; shift ;;
    --allow-unauthenticated) ALLOW_UNAUTH="true"; shift ;;
    --dry-run)               DRY_RUN="true"; shift ;;
    -h|--help)               COMMAND="help"; shift ;;
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
  cloud-run (default)   Enable APIs, provision SA + IAM, and deploy ADK Web UI to Cloud Run
  agent-runtime         Enable APIs, provision SA + IAM, and deploy to Vertex AI Agent Runtime
                        (optionally registers directly into a Gemini Enterprise app via --ge-app-id)
  publish-ge            Register a deployed Agent Runtime into a Gemini Enterprise app
  local                 Create local Python venv and launch ADK Web UI on http://localhost:8000
  teardown              Delete the deployed Cloud Run service (or Agent Runtime via --agent-engine-id)

Options:
  --project ID              Target GCP Project ID (defaults to active gcloud config project)
  --region REGION           Deployment region for Cloud Run or Agent Runtime (default: us-central1)
  --location LOC            Vertex AI Gemini model location (default: global)
  --service-name NAME       Cloud Run service name (default: cloudops)
  --display-name NAME       Display name in Agent Runtime & Gemini Enterprise (default: "CloudOps & FinOps Agent")
  --description TEXT        Description shown in Agent Runtime & Gemini Enterprise
  --model MODEL             Gemini model name (default: gemini-2.5-flash)
  --mode MODE               'readonly' (default, safe inspection + IaC) or 'readwrite' (allows remediation)
  --billing-account ID      Optional Billing Account ID (enables CUD & negotiated pricing lookups)
  --agent-engine-id ID      Existing Agent Runtime ID to update in-place (agent-runtime / teardown)
  --agent-runtime-id NAME   Full Agent Runtime resource name (publish-ge; auto-read from deployment_metadata.json)
  --ge-app-id NAME          Gemini Enterprise App resource name (projects/NUM/locations/global/collections/default_collection/engines/ID)
  --iap                     Enable Identity-Aware Proxy (IAP) on Cloud Run for browser SSO
  --allow-unauthenticated   Allow public unauthenticated access on Cloud Run (demos only)
  --dry-run                 Print every command without executing changes
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

ensure_local_venv() {
  local py_bin
  py_bin="$(command -v python3 || command -v python)"
  if [[ ! -d ".venv" ]]; then
    run_cmd "$py_bin" -m venv .venv
  fi
  if [[ "$DRY_RUN" == "false" ]]; then
    if ! .venv/bin/python -c "import google.adk, mcp, requests, aiohttp; from google.adk.dependencies._agentplatform import agentplatform" >/dev/null 2>&1; then
      echo "==> Installing Python dependencies into .venv..."
      .venv/bin/pip install --upgrade pip -q
      .venv/bin/pip install -r requirements.txt -q
    fi
  else
    run_cmd .venv/bin/pip install -r requirements.txt -q
  fi
}

setup_apis_and_iam() {
  local include_agent_engine_sa_impersonation="$1"
  SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

  echo ""
  echo "[1/4] Enabling required Google Cloud APIs (also enables Remote MCP endpoints)..."
  local apis=(
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
    discoveryengine.googleapis.com
  )
  run_cmd gcloud services enable "${apis[@]}" --project="$PROJECT_ID"

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
  local readonly_roles=(
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
  local readwrite_extra_roles=(
    roles/recommender.computeAdmin
    roles/recommender.cloudsqlAdmin
    roles/recommender.runAdmin
    roles/compute.instanceAdmin.v1
    roles/container.developer
    roles/run.developer
  )

  local roles_to_bind=("${readonly_roles[@]}")
  if [[ "$MODE" == "readwrite" ]]; then
    roles_to_bind+=("${readwrite_extra_roles[@]}")
  fi

  for role in "${roles_to_bind[@]}"; do
    echo "  -> Granting $role"
    run_cmd_quiet gcloud projects add-iam-policy-binding "$PROJECT_ID" \
      --member="serviceAccount:${SA_EMAIL}" \
      --role="$role" \
      --condition=None \
      --quiet
  done

  if [[ "$include_agent_engine_sa_impersonation" == "true" ]]; then
    local project_number
    project_number="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)' 2>/dev/null || echo 'PROJECT_NUMBER')"
    local re_sa="service-${project_number}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"
    echo "  -> Authorizing Agent Runtime Service Agent ($re_sa) to run as $SA_EMAIL"
    for sa_role in roles/iam.serviceAccountUser roles/iam.serviceAccountTokenCreator; do
      run_cmd_quiet gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
        --project="$PROJECT_ID" \
        --member="serviceAccount:${re_sa}" \
        --role="$sa_role" \
        --quiet || echo "  (Note: Ensure $re_sa exists; run 'gcloud beta services identity create --service=aiplatform.googleapis.com --project=$PROJECT_ID' if first time.)"
    done
  fi

  if [[ -n "$BILLING_ACCOUNT_ID" ]]; then
    echo "  -> Granting Billing & CUD Viewer roles on Billing Account: $BILLING_ACCOUNT_ID"
    for brole in roles/billing.viewer roles/recommender.billingAccountCudViewer; do
      run_cmd_quiet gcloud billing accounts add-iam-policy-binding "$BILLING_ACCOUNT_ID" \
        --member="serviceAccount:${SA_EMAIL}" \
        --role="$brole" \
        --quiet || echo "  (Warning: Could not bind $brole on billing account; ask a Billing Account Admin to grant it.)"
    done
  fi
}

publish_to_gemini_enterprise() {
  local runtime_id="$1"
  local ge_app="$2"

  if [[ -z "$runtime_id" && -f "deployment_metadata.json" ]]; then
    runtime_id="$(python3 -c "import json; print(json.load(open('deployment_metadata.json')).get('remote_agent_runtime_id',''))" 2>/dev/null || true)"
  fi
  if [[ -z "$runtime_id" ]]; then
    echo "Error: Agent Runtime ID not found. Pass --agent-runtime-id or deploy first via './deploy.sh agent-runtime'."
    exit 1
  fi
  if [[ -z "$ge_app" ]]; then
    echo "Error: Gemini Enterprise App ID is required. Pass --ge-app-id 'projects/NUM/locations/global/collections/default_collection/engines/APP_ID'."
    echo "Tip: List your apps with: agents-cli publish gemini-enterprise --list --project-id $PROJECT_ID"
    exit 1
  fi

  echo ""
  echo "==> Registering Agent Runtime into Gemini Enterprise..."
  echo "    Agent Runtime: $runtime_id"
  echo "    GE App:        $ge_app"
  echo "    Display Name:  $DISPLAY_NAME"

  if command -v agents-cli >/dev/null 2>&1; then
    run_cmd agents-cli publish gemini-enterprise \
      --registration-type adk \
      --agent-runtime-id "$runtime_id" \
      --gemini-enterprise-app-id "$ge_app" \
      --display-name "$DISPLAY_NAME" \
      --description "$AGENT_DESCRIPTION" \
      --tool-description "$AGENT_DESCRIPTION" \
      --project-id "$PROJECT_ID"
  else
    # Fallback via Discovery Engine REST API (no agents-cli required!)
    local endpoint="https://discoveryengine.googleapis.com/v1alpha/${ge_app}/assistants/default_assistant/agents"
    if [[ "$DRY_RUN" == "true" ]]; then
      echo "[DRY-RUN] POST ${endpoint} (adkAgentDefinition.provisionedReasoningEngine.reasoningEngine=${runtime_id})"
      return 0
    fi
    local token
    token="$(gcloud auth application-default print-access-token 2>/dev/null || gcloud auth print-access-token)"
    local payload
    payload="$(python3 - "$DISPLAY_NAME" "$AGENT_DESCRIPTION" "$runtime_id" <<'PYEOF'
import json, sys
print(json.dumps({
    "displayName": sys.argv[1],
    "description": sys.argv[2],
    "adkAgentDefinition": {
        "toolSettings": {"toolDescription": sys.argv[2]},
        "provisionedReasoningEngine": {"reasoningEngine": sys.argv[3]},
    },
}))
PYEOF
)"
    curl -sS -X POST "$endpoint" \
      -H "Authorization: Bearer ${token}" \
      -H "Content-Type: application/json" \
      -H "X-Goog-User-Project: ${PROJECT_ID}" \
      -d "$payload"
    echo ""
  fi
}

# ==============================================================================
# LOCAL RUN MODE
# ==============================================================================
if [[ "$COMMAND" == "local" ]]; then
  require_gcloud
  echo "==> Setting up local Python environment for project: $PROJECT_ID"
  ensure_local_venv

  if [[ ! -f "app/.env" && ! -f ".env" ]]; then
    echo "==> Generating local .env (mode=$MODE, model=$MODEL_NAME, location=$LOCATION)"
    if [[ "$DRY_RUN" == "false" ]]; then
      cat > .env <<EOF
GOOGLE_GENAI_USE_VERTEXAI=True
GOOGLE_CLOUD_PROJECT=${PROJECT_ID}
GOOGLE_CLOUD_LOCATION=${LOCATION}
GEMINI_MODEL=${MODEL_NAME}
GEMINI_LOCATION=${LOCATION}
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
# PUBLISH EXISTING AGENT RUNTIME TO GEMINI ENTERPRISE
# ==============================================================================
if [[ "$COMMAND" == "publish-ge" ]]; then
  require_gcloud
  publish_to_gemini_enterprise "$AGENT_RUNTIME_ID" "$GE_APP_ID"
  exit 0
fi

# ==============================================================================
# TEARDOWN MODE
# ==============================================================================
if [[ "$COMMAND" == "teardown" ]]; then
  require_gcloud
  if [[ -n "$AGENT_ENGINE_ID" ]]; then
    local_res="$AGENT_ENGINE_ID"
    if [[ "$local_res" != projects/* ]]; then
      local_res="projects/${PROJECT_ID}/locations/${REGION}/reasoningEngines/${AGENT_ENGINE_ID}"
    fi
    echo "==> Deleting Agent Runtime '$local_res'..."
    if [[ "$DRY_RUN" == "true" ]]; then
      echo "[DRY-RUN] Delete Agent Runtime: $local_res"
    else
      ensure_local_venv
      .venv/bin/python -c "from google.adk.dependencies._agentplatform import agentplatform; agentplatform.Client(project='${PROJECT_ID}', location='${REGION}').runtimes.delete(name='${local_res}', force=True); print('Deleted:', '${local_res}')"
    fi
  else
    echo "==> Deleting Cloud Run service '$SERVICE_NAME' in $PROJECT_ID ($REGION)..."
    run_cmd gcloud run services delete "$SERVICE_NAME" \
      --project="$PROJECT_ID" \
      --region="$REGION" \
      --quiet
  fi
  echo "Done. Service account '${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com' was preserved."
  exit 0
fi

# ==============================================================================
# VERTEX AI AGENT RUNTIME DEPLOYMENT
# ==============================================================================
if [[ "$COMMAND" == "agent-runtime" ]]; then
  require_gcloud
  SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

  echo "=================================================================="
  echo " Deploying Google Cloud FinOps + CloudOps ADK Agent to Agent Runtime"
  echo "=================================================================="
  echo " Project:         $PROJECT_ID"
  echo " Runtime Region:  $REGION"
  echo " Display Name:    $DISPLAY_NAME"
  echo " Service Account: $SA_EMAIL"
  echo " Gemini Model:    $MODEL_NAME (model location: $LOCATION)"
  echo " Safety Mode:     $MODE"
  echo " Billing Acct:    ${BILLING_ACCOUNT_ID:-<none - project scope only>}"
  echo " Update Engine:   ${AGENT_ENGINE_ID:-<create new instance>}"
  echo " Auto-Publish GE: ${GE_APP_ID:-<none - deploy runtime only>}"
  echo "=================================================================="

  setup_apis_and_iam "true"

  echo ""
  echo "[4/4] Building & deploying container to Vertex AI Agent Runtime..."
  ensure_local_venv

  CONFIG_FILE="$(pwd)/.agent_engine_config.json"
  if [[ "$DRY_RUN" == "false" ]]; then
    python3 - "$CONFIG_FILE" "$PROJECT_ID" "$MODEL_NAME" "$LOCATION" "$MODE" "$BILLING_ACCOUNT_ID" <<'PYEOF'
import json, sys
cfg_path, project_id, model_name, model_loc, mode, billing_id = sys.argv[1:7]
env_vars = {
    "GOOGLE_GENAI_USE_VERTEXAI": "True",
    "TARGET_GCP_PROJECT": project_id,
    "GEMINI_MODEL": model_name,
    "GEMINI_LOCATION": model_loc,
    "AGENT_EXECUTION_MODE": mode,
}
if billing_id:
    env_vars["BILLING_ACCOUNT_ID"] = billing_id
config = {
    "env_vars": env_vars,
    "min_instances": 1,
    "max_instances": 5,
    "container_concurrency": 8,
    "resource_limits": {"cpu": "2", "memory": "4Gi"},
    "python_version": "3.12",
}
with open(cfg_path, "w", encoding="utf-8") as f:
    json.dump(config, f, indent=2)
PYEOF
  fi

  AE_ARGS=(
    .venv/bin/adk deploy agent_engine
    --project="$PROJECT_ID"
    --region="$REGION"
    --display_name="$DISPLAY_NAME"
    --description="$AGENT_DESCRIPTION"
    --service_account="$SA_EMAIL"
    --agent_engine_config_file="$CONFIG_FILE"
  )
  if [[ -n "$AGENT_ENGINE_ID" ]]; then
    AE_ARGS+=(--agent_engine_id="$AGENT_ENGINE_ID")
  fi
  AE_ARGS+=(app)

  if [[ "$DRY_RUN" == "true" ]]; then
    run_cmd "${AE_ARGS[@]}"
    if [[ -n "$GE_APP_ID" ]]; then
      publish_to_gemini_enterprise "projects/${PROJECT_ID}/locations/${REGION}/reasoningEngines/EXAMPLE_ID" "$GE_APP_ID"
    fi
    exit 0
  fi

  DEPLOY_LOG="$(mktemp)"
  set +e
  "${AE_ARGS[@]}" 2>&1 | tee "$DEPLOY_LOG"
  DEPLOY_RC=${PIPESTATUS[0]}
  set -e

  RUNTIME_RESOURCE="$(grep -Eo 'projects/[^[:space:]]+/locations/[^[:space:]]+/reasoningEngines/[0-9]+' "$DEPLOY_LOG" | tail -n 1 || true)"
  rm -f "$DEPLOY_LOG" "$CONFIG_FILE"

  if [[ "$DEPLOY_RC" -ne 0 || -z "$RUNTIME_RESOURCE" ]]; then
    echo "Error: Agent Runtime deployment did not complete cleanly (rc=$DEPLOY_RC)."
    exit "${DEPLOY_RC:-1}"
  fi

  python3 - "$RUNTIME_RESOURCE" <<'PYEOF'
import datetime, json, sys
meta = {
    "remote_agent_runtime_id": sys.argv[1],
    "deployment_target": "agent_runtime",
    "is_a2a": True,
    "agent_directory": "app",
    "deployment_timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
}
with open("deployment_metadata.json", "w", encoding="utf-8") as f:
    json.dump(meta, f, indent=2)
PYEOF

  echo ""
  echo "=================================================================="
  echo " Agent Runtime Deployment Complete!"
  echo "=================================================================="
  echo " Resource Name: $RUNTIME_RESOURCE"
  echo " Metadata File: deployment_metadata.json"
  echo "=================================================================="

  if [[ -n "$GE_APP_ID" ]]; then
    publish_to_gemini_enterprise "$RUNTIME_RESOURCE" "$GE_APP_ID"
  else
    echo ""
    echo "Next step — register this Agent Runtime in Gemini Enterprise:"
    echo "  ./deploy.sh publish-ge --project $PROJECT_ID --ge-app-id projects/PROJECT_NUMBER/locations/global/collections/default_collection/engines/YOUR_GE_APP_ID"
  fi
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

setup_apis_and_iam "false"

echo ""
echo "[4/4] Building & deploying container to Cloud Run..."
ENV_VARS="GOOGLE_GENAI_USE_VERTEXAI=True,GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=${LOCATION},GEMINI_MODEL=${MODEL_NAME},GEMINI_LOCATION=${LOCATION},AGENT_EXECUTION_MODE=${MODE}"
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
