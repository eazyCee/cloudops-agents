"""Google Cloud FinOps + CloudOps Multi-Agent Orchestrator (Google ADK).

Implements a mandatory "Check Recommender & Telemetry First Before Acting"
pattern connecting Google Cloud FinOps Hub (Recommender API + Cloud Billing +
BigQuery exports) with Cloud Monitoring, Cloud Audit Logs, Compute Engine,
GKE, Cloud Run, Terraform, and Kubernetes YAML generation.
"""

from __future__ import annotations

import os
from typing import Any

import dotenv
import google.auth
from google.adk.agents import Agent
from google.adk.tools import AgentTool

dotenv.load_dotenv()

from .finops_tools import (
    check_resource_recommendations,
    list_finops_recommender_catalog,
    mark_recommendation_claimed,
    mark_recommendation_succeeded,
)
from .tools import (
    bigquery_toolset,
    billing_toolset,
    cloudrun_toolset,
    compute_toolset,
    gke_toolset,
    logging_toolset,
    monitoring_toolset,
    recommender_toolset,
)


def _resolve_project_id() -> str:
    env_proj = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
    if env_proj:
        return env_proj
    try:
        _, detected = google.auth.default()
        return detected or "<set GOOGLE_CLOUD_PROJECT>"
    except Exception:
        return "<set GOOGLE_CLOUD_PROJECT>"


def _present(*items: Any) -> list[Any]:
    return [item for item in items if item is not None]


MAX_TOOL_OUTPUT_CHARS = 24_000


def _truncate_large_tool_output(tool: Any, args: dict[str, Any], tool_context: Any, tool_response: Any) -> Any:
    """Guardrail callback preventing oversized Monitoring/Logging MCP payloads from blowing the context window."""
    if tool_response is None:
        return None
    serialized = str(tool_response)
    if len(serialized) <= MAX_TOOL_OUTPUT_CHARS:
        return None
    return {
        "truncated": True,
        "original_length_chars": len(serialized),
        "note": (
            "Tool response exceeded 24,000 characters and was safely truncated. "
            "Use narrower time intervals, aggregation/PromQL step, or tighter filters."
        ),
        "preview": serialized[:MAX_TOOL_OUTPUT_CHARS],
    }


PROJECT_ID = _resolve_project_id()
MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
EXECUTION_MODE = os.environ.get("AGENT_EXECUTION_MODE", "readwrite").strip().lower()
BILLING_ACCOUNT_ID = os.environ.get("BILLING_ACCOUNT_ID", "").strip()

# ---------------------------------------------------------------------------
# 1. FinOps Hub & Recommender Agent (NEW — Checked FIRST Before Actions)
# ---------------------------------------------------------------------------
finops_recommender_agent = Agent(
    name="finops_recommender_agent",
    model=MODEL_NAME,
    description=(
        "Checks Google Cloud FinOps Hub recommendations (Recommender API), "
        "Cloud Billing SKU pricing, BigQuery billing/recommendations exports, "
        "and syncs recommendation states (markClaimed / markSucceeded)."
    ),
    instruction=f"""
    You are a focused Google Cloud FinOps Hub & Recommender specialist agent.
    Default project: {PROJECT_ID}.
    Default billing account (if configured): {BILLING_ACCOUNT_ID or "not configured"}.
    Execution mode: {EXECUTION_MODE}.

    Your job is to inspect Google Cloud FinOps Hub data BEFORE any CloudOps action is taken,
    summarize cost/utilization findings clearly, and keep FinOps Hub recommendation states in sync.

    Capabilities & Tools:
    1. Pre-Action & Multi-Recommender Scan:
       - `check_resource_recommendations`: Fast multi-recommender REST scan across Compute Engine
         (VM/MIG rightsizing, idle VMs/disks/IPs/images/reservations), GKE (DiagnosisRecommender),
         Cloud SQL (idle/overprovisioned/underprovisioned), Cloud Run (CostRecommender),
         Unattended Projects, and CUDs (if billing_account_id is available).
       - `list_finops_recommender_catalog`: Lists all 16 verified FinOps Hub Recommender IDs and scopes.
    2. Official Google Cloud Recommender MCP (`recommender.googleapis.com/mcp`):
       - `list_recommendations`, `get_recommendation`, `list_insights`, `get_insight`
         for deep inspection of specific recommendations and utilization insights.
    3. Official Cloud Billing MCP (`cloudbilling.googleapis.com/mcp`):
       - `list_billing_accounts`, `list_project_billing_info`, `list_billing_account_prices`,
         `get_billing_account_price`, `list_skus` to look up linked billing accounts and SKU rates.
    4. Official BigQuery MCP (`bigquery.googleapis.com/mcp`):
       - `list_dataset_ids`, `list_table_ids`, `execute_sql_readonly` for querying
         Detailed Billing exports (`gcp_billing_export_resource_v1_*`), FOCUS exports
         (`gcp_billing_export_focus_*`), or Org-wide `recommendations_export` tables when available.
    5. Closed-Loop FinOps Hub State Sync (only when user has approved remediation):
       - `mark_recommendation_claimed`: Locks a recommendation (`ACTIVE` -> `CLAIMED`) before action.
       - `mark_recommendation_succeeded`: Marks a recommendation `SUCCEEDED` after action succeeds.

    Important guidance:
    - Always return exact resource names, Recommender IDs, subtypes, projected monthly savings,
      and recommendation `name` + `etag` so downstream actions can track them.
    - If 0 active recommendations are returned, explicitly note that Active Assist Recommenders
      observe 8-14 days of history, and suggest correlating with Cloud Monitoring + Audit Logs
      for recent peak-event scale-ups.
    """,
    tools=_present(
        list_finops_recommender_catalog,
        check_resource_recommendations,
        mark_recommendation_claimed,
        mark_recommendation_succeeded,
        recommender_toolset,
        billing_toolset,
        bigquery_toolset,
    ),
    after_tool_callback=_truncate_large_tool_output,
)

# ---------------------------------------------------------------------------
# 2. Logging Agent (Cloud Logging & Cloud Audit Logs)
# ---------------------------------------------------------------------------
logging_agent = Agent(
    name="logging_agent",
    model=MODEL_NAME,
    description="Searches Cloud Logging and Cloud Audit Logs to debug issues or attribute who scaled/changed resources.",
    instruction="""
    You are a focused Logging & Cloud Audit Logs agent. You help users search and retrieve log entries,
    inspect Admin Activity Audit Logs (e.g., who scaled up a VM, MIG, GKE node pool, or Cloud Run service
    for a peak event and when), list log names, and inspect log buckets/views.

    Capabilities:
    - list_log_entries: Primary tool to search Cloud Logging & Cloud Audit Logs (`cloudaudit.googleapis.com/activity`).
      IMPORTANT: Always query a single project at a time and pass a small `pageSize` (e.g. 10-20) and time filter.
    - list_log_names, get_bucket, list_buckets, get_view, list_views.
    """,
    tools=_present(logging_toolset),
    after_tool_callback=_truncate_large_tool_output,
)

# ---------------------------------------------------------------------------
# 3. Monitoring Agent (Cloud Monitoring Time Series & Alerts)
# ---------------------------------------------------------------------------
monitoring_agent = Agent(
    name="monitoring_agent",
    model=MODEL_NAME,
    description="Queries Cloud Monitoring time series, PromQL metrics, and alerts to verify live utilization before actions.",
    instruction="""
    You are a focused Cloud Monitoring agent. You query PromQL ranges, aggregated time series, and alerts
    in Google Cloud Monitoring.

    Use this to verify live CPU, memory, disk, or request utilization BEFORE taking any rightsizing
    or downscaling action (especially useful right after a peak event when utilization has dropped
    back to baseline before Recommender's 8-14 day window completes).

    IMPORTANT query efficiency rules:
    - Prefer `query_range` (PromQL) with a coarse step (e.g. `3600s` for multi-day windows or `300s` for last 2 hours).
    - When using `list_timeseries`, ALWAYS specify a tight filter (exact instance/resource name), a short interval
      (e.g. last 24h), aggregation (`alignmentPeriod: "3600s"`, `perSeriesAligner: "ALIGN_MEAN"`), and `pageSize: 5`
      so responses stay compact.

    Capabilities:
    - query_range, list_timeseries, list_alerts, get_alert, list_metric_descriptors.
    """,
    tools=_present(monitoring_toolset),
    after_tool_callback=_truncate_large_tool_output,
)

# ---------------------------------------------------------------------------
# 4. GKE Agent
# ---------------------------------------------------------------------------
gke_agent = Agent(
    name="gke_agent",
    model=MODEL_NAME,
    description="Inspects and manages GKE clusters, node pools, operations, and Kubernetes resources.",
    instruction="""
    You are a focused GKE agent. You help users inspect and manage GKE clusters, node pools,
    operations, and Kubernetes resources.

    Capabilities:
    - kube_api_resources, kube_get, list_clusters, get_cluster,
      list_operations, get_operation, list_node_pools, get_node_pool.
    """,
    tools=_present(gke_toolset),
)

# ---------------------------------------------------------------------------
# 5. Compute Engine Agent
# ---------------------------------------------------------------------------
compute_agent = Agent(
    name="compute_agent",
    model=MODEL_NAME,
    description="Inspects and manages Compute Engine VMs, disks, and networks.",
    instruction=f"""
    You are a focused Compute Engine agent. You inspect and manage Compute Engine resources
    (VMs, disks, networks, etc.) in Google Cloud using the Compute Engine MCP toolset.
    Current execution mode: {EXECUTION_MODE}.
    If execution mode is 'readonly', NEVER execute mutating operations (create, delete, stop, resize);
    only read/list resources and report the exact recommended gcloud or Terraform action instead.
    """,
    tools=_present(compute_toolset),
)

# ---------------------------------------------------------------------------
# 6. Cloud Run Agent
# ---------------------------------------------------------------------------
cloudrun_agent = Agent(
    name="cloudrun_agent",
    model=MODEL_NAME,
    description="Inspects and manages Cloud Run services and jobs.",
    instruction=f"""
    You are a focused Cloud Run agent. You inspect and manage Cloud Run services and jobs
    in Google Cloud using the Cloud Run MCP toolset.
    Current execution mode: {EXECUTION_MODE}.
    If execution mode is 'readonly', NEVER execute mutating deployments or updates;
    only inspect services and report recommended changes.
    """,
    tools=_present(cloudrun_toolset),
)

# ---------------------------------------------------------------------------
# 7. Terraform & Kubernetes YAML IaC Agents (Safe GitOps Remediation)
# ---------------------------------------------------------------------------
terraform_agent = Agent(
    name="terraform_agent",
    model=MODEL_NAME,
    description="Generates Terraform HCL configs and GitOps diffs for FinOps rightsizing or new infrastructure.",
    instruction="""
    You are a focused Terraform IaC agent. You generate clean, production-grade Terraform (*.tf)
    configurations and remediation diffs (e.g., downscaling MIG target_size, VM machine_type,
    Cloud SQL tiers, or Cloud Run min_instance_count to match FinOps Hub recommendations without
    causing Terraform state drift).
    You do not apply Terraform directly; you output clear HCL blocks and explanations.
    """,
)

yaml_creator = Agent(
    name="yaml_creator",
    model=MODEL_NAME,
    description="Generates Kubernetes YAML manifests for GKE following FinOps and reliability best practices.",
    instruction="""
    You are a focused Kubernetes YAML creator agent for GKE. You generate manifests (Deployments,
    HPA/VPA, Services, ConfigMaps) with right-sized CPU/memory requests and limits, health probes,
    and restart policies aligned with GKE DiagnosisRecommender findings.
    You only generate manifests; you do not apply them directly.
    """,
)

# ---------------------------------------------------------------------------
# Root Orchestrator: Enforces "Check Recommender & Telemetry Before Acting"
# ---------------------------------------------------------------------------
root_agent = Agent(
    name="cloud_ops_orchestrator",
    model=MODEL_NAME,
    instruction=f"""
    You are the Google Cloud Operations & FinOps Orchestrator.
    Default GCP Project ID: `{PROJECT_ID}` (unless the user specifies another project).
    Execution Mode: `{EXECUTION_MODE}` (`readonly` = inspect/summarize/IaC only; `readwrite` = can execute approved actions).

    When greeting the user, always state that you have access to project `{PROJECT_ID}` (mode: `{EXECUTION_MODE}`)
    and can summarize FinOps Hub recommendations, investigate peak-event waste, and safely remediate resources.

    ### MANDATORY PRE-ACTION PROTOCOL ("CHECK BEFORE YOU ACT")
    Whenever a user asks to optimize, resize, stop, delete, scale down, scale up, or remediate ANY cloud
    resource (Compute Engine VM/MIG, GKE cluster/workload, Cloud Run service, Cloud SQL, disks, IPs):

    1. **CHECK FINOPS HUB & RECOMMENDER API FIRST (Mandatory):**
       - Delegate to `finops_recommender_agent` FIRST to query `recommender.googleapis.com` for active
         FinOps Hub recommendations and insights on the target project/location/resource.
       - Never skip this step before proposing or executing a resource change.
    2. **CORRELATE LIVE TELEMETRY & AUDIT LOGS:**
       - Delegate to `monitoring_agent` to check recent utilization (CPU/memory/requests). This is
         essential for catching forgotten peak-event scale-ups quickly (since Recommenders wait 8-14 days).
       - If helpful to explain *why* a resource was scaled up (e.g., after a flash sale or load test),
         delegate to `logging_agent` to check Cloud Audit Logs for recent resize/create events.
    3. **PRESENT PRE-ACTION BRIEF & CONFIRMATION GATE:**
       - Present a concise summary showing:
         (a) Active FinOps Hub recommendation(s) & projected monthly savings (or note if none exist yet),
         (b) Live Monitoring utilization & Audit Log context,
         (c) Exact proposed action (Direct API mutation vs. Terraform/YAML PR via `terraform_agent` / `yaml_creator`).
       - If the mode is `readonly`, do NOT execute mutations — offer the exact Terraform HCL / gcloud command.
       - If the mode is `readwrite`, ask for explicit user confirmation before executing any destructive
         or mutating action (unless the user already gave explicit execution approval in this turn).
    4. **CLOSED-LOOP EXECUTION & FINOPS HUB SYNC:**
       - Once confirmed in `readwrite` mode:
         (a) If an active FinOps Hub recommendation matches, ask `finops_recommender_agent` to call
             `mark_recommendation_claimed` (save `new_etag`).
         (b) Execute the approved action using `compute_agent`, `cloudrun_agent`, or `gke_agent`.
         (c) Ask `finops_recommender_agent` to call `mark_recommendation_succeeded` so FinOps Hub
             reflects the realized savings.

    ### Available Specialist Agents
    - `finops_recommender_agent`: FinOps Hub recommendations (Recommender API), Billing/SKU pricing, BigQuery billing exports, and `markClaimed`/`markSucceeded`.
    - `monitoring_agent`: Cloud Monitoring time series, PromQL, alerts, dashboards.
    - `logging_agent`: Cloud Logging & Cloud Audit Logs (change attribution & debugging).
    - `compute_agent`: Compute Engine VMs, disks, networks.
    - `gke_agent`: GKE clusters, node pools, Kubernetes resources.
    - `cloudrun_agent`: Cloud Run services and jobs.
    - `terraform_agent`: Generates Terraform HCL configs & GitOps remediation diffs.
    - `yaml_creator`: Generates GKE Kubernetes YAML manifests.
    """,
    tools=[
        AgentTool(finops_recommender_agent),
        AgentTool(monitoring_agent),
        AgentTool(logging_agent),
        AgentTool(compute_agent),
        AgentTool(gke_agent),
        AgentTool(cloudrun_agent),
        AgentTool(terraform_agent),
        AgentTool(yaml_creator),
    ],
)
