"""Google Cloud FinOps Hub & Recommender API helper tools.

Complements the read-only Recommender MCP server (`https://recommender.googleapis.com/mcp`)
by providing:
1. A verified catalog of all 16 official FinOps Hub Cost Recommender IDs.
2. Multi-recommender pre-action scanning (`check_resource_recommendations`) across
   Compute Engine, GKE, Cloud SQL, Cloud Run, and CUD recommenders.
3. Closed-loop state synchronization (`mark_recommendation_claimed` and
   `mark_recommendation_succeeded`) against `recommender.googleapis.com/v1` so
   FinOps Hub reflects realized savings after an approved remediation action.
"""

from __future__ import annotations

import os
import threading
from typing import Any

import google.auth
import google.auth.transport.requests
import requests

RECOMMENDER_API_BASE = "https://recommender.googleapis.com/v1"

# Official FinOps Hub backing cost recommenders
FINOPS_HUB_RECOMMENDERS: list[dict[str, str]] = [
    {
        "service": "compute",
        "name": "VM Machine Type Recommender",
        "recommender_id": "google.compute.instance.MachineTypeRecommender",
        "scope": "zone",
        "category": "RIGHTSIZE",
        "description": "Right-size overprovisioned or underprovisioned Compute Engine VMs.",
    },
    {
        "service": "compute",
        "name": "MIG Machine Type Recommender",
        "recommender_id": "google.compute.instanceGroupManager.MachineTypeRecommender",
        "scope": "region_or_zone",
        "category": "RIGHTSIZE",
        "description": "Right-size Managed Instance Group (MIG) machine types.",
    },
    {
        "service": "compute",
        "name": "Idle VM Recommender",
        "recommender_id": "google.compute.instance.IdleResourceRecommender",
        "scope": "zone",
        "category": "IDLE",
        "description": "Stop or delete idle Compute Engine VMs.",
    },
    {
        "service": "compute",
        "name": "Idle Persistent Disk Recommender",
        "recommender_id": "google.compute.disk.IdleResourceRecommender",
        "scope": "zone_or_region",
        "category": "IDLE",
        "description": "Snapshot and delete unattached or idle persistent disks.",
    },
    {
        "service": "compute",
        "name": "Idle IP Address Recommender",
        "recommender_id": "google.compute.address.IdleResourceRecommender",
        "scope": "region",
        "category": "IDLE",
        "description": "Release unused static external IP addresses.",
    },
    {
        "service": "compute",
        "name": "Idle Custom Image Recommender",
        "recommender_id": "google.compute.image.IdleResourceRecommender",
        "scope": "global",
        "category": "IDLE",
        "description": "Delete unused custom VM images.",
    },
    {
        "service": "compute",
        "name": "Idle Reservations Recommender",
        "recommender_id": "google.compute.IdleResourceRecommender",
        "scope": "zone",
        "category": "IDLE",
        "description": "Remove unused Compute Engine reservations.",
    },
    {
        "service": "compute",
        "name": "Underutilized Reservations Recommender",
        "recommender_id": "google.compute.RightSizeResourceRecommender",
        "scope": "zone",
        "category": "RIGHTSIZE",
        "description": "Right-size underutilized Compute Engine reservations.",
    },
    {
        "service": "gke",
        "name": "GKE Diagnosis Recommender (Idle & Over/Underprovisioned)",
        "recommender_id": "google.container.DiagnosisRecommender",
        "scope": "region_or_zone",
        "category": "RIGHTSIZE_AND_IDLE",
        "description": "Subtypes: CLUSTER_IDLE, CLUSTER_OVERPROVISIONED, CLUSTER_UNDERPROVISIONED, WORKLOAD_OVERPROVISIONED, WORKLOAD_UNDERPROVISIONED.",
    },
    {
        "service": "cloudsql",
        "name": "Cloud SQL Idle Instance Recommender",
        "recommender_id": "google.cloudsql.instance.IdleRecommender",
        "scope": "region",
        "category": "IDLE",
        "description": "Shut down idle Cloud SQL database instances.",
    },
    {
        "service": "cloudsql",
        "name": "Cloud SQL Overprovisioned Recommender",
        "recommender_id": "google.cloudsql.instance.OverprovisionedRecommender",
        "scope": "region",
        "category": "RIGHTSIZE",
        "description": "Downscale overprovisioned Cloud SQL instances (e.g., left scaled up after peak events).",
    },
    {
        "service": "cloudsql",
        "name": "Cloud SQL Underprovisioned Recommender",
        "recommender_id": "google.cloudsql.instance.UnderprovisionedRecommender",
        "scope": "region",
        "category": "RIGHTSIZE",
        "description": "Scale up underprovisioned Cloud SQL instances (surfaced in Utilization Insights).",
    },
    {
        "service": "cloudrun",
        "name": "Cloud Run Cost / CPU Allocation Recommender",
        "recommender_id": "google.run.service.CostRecommender",
        "scope": "region",
        "category": "OTHER",
        "description": "Optimize Cloud Run CPU allocation and warm-instance cost efficiency.",
    },
    {
        "service": "cud",
        "name": "Spend-Based & Flexible CUD Recommender",
        "recommender_id": "google.cloudbilling.commitment.SpendBasedCommitmentRecommender",
        "scope": "billing_account_global",
        "category": "CUD",
        "description": "Purchase spend-based and Compute Flexible Committed Use Discounts.",
    },
    {
        "service": "cud",
        "name": "Resource-Based CUD Recommender",
        "recommender_id": "google.compute.commitment.UsageCommitmentRecommender",
        "scope": "billing_account_or_project_region",
        "category": "CUD",
        "description": "Purchase resource-based Compute Engine Committed Use Discounts.",
    },
    {
        "service": "project",
        "name": "Unattended Project Recommender",
        "recommender_id": "google.resourcemanager.projectUtilization.Recommender",
        "scope": "global",
        "category": "IDLE",
        "description": "Reclaim or remove abandoned/unattended GCP projects.",
    },
]

_AUTH_LOCK = threading.Lock()
_CACHED_CREDENTIALS = None
_CACHED_PROJECT_ID: str | None = None


def get_fresh_gcp_headers(quota_project: str | None = None) -> tuple[dict[str, str], str]:
    """Return auto-refreshed GCP OAuth Bearer headers and resolved project ID."""
    global _CACHED_CREDENTIALS, _CACHED_PROJECT_ID
    with _AUTH_LOCK:
        if _CACHED_CREDENTIALS is None:
            _CACHED_CREDENTIALS, detected_project = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            _CACHED_PROJECT_ID = (
                os.environ.get("TARGET_GCP_PROJECT")
                or os.environ.get("GOOGLE_CLOUD_PROJECT")
                or detected_project
                or ""
            )

        if not _CACHED_CREDENTIALS.valid or _CACHED_CREDENTIALS.expired:
            _CACHED_CREDENTIALS.refresh(google.auth.transport.requests.Request())

        project_id = (
            quota_project
            or os.environ.get("TARGET_GCP_PROJECT")
            or os.environ.get("GOOGLE_CLOUD_PROJECT")
            or _CACHED_PROJECT_ID
            or ""
        )
        headers = {
            "Authorization": f"Bearer {_CACHED_CREDENTIALS.token}",
            "Content-Type": "application/json",
        }
        if project_id:
            headers["x-goog-user-project"] = project_id
        return headers, project_id


def list_finops_recommender_catalog(service_filter: str = "ALL") -> dict[str, Any]:
    """List verified Google Cloud FinOps Hub Cost Recommender IDs and required API scopes.

    Args:
        service_filter: Filter by service ('ALL', 'compute', 'gke', 'cloudsql', 'cloudrun', 'cud', 'project').

    Returns:
        Dictionary with matching FinOps Hub recommender IDs and scope guidance.
    """
    sf = (service_filter or "ALL").strip().lower()
    recs = [
        r for r in FINOPS_HUB_RECOMMENDERS if sf == "all" or r["service"] == sf
    ]
    return {
        "service_filter": service_filter,
        "count": len(recs),
        "recommenders": recs,
        "note": (
            "Zone-scoped recommenders (like VM MachineTypeRecommender) need a zone such as 'us-central1-a'; "
            "region-scoped recommenders (like Cloud SQL or Cloud Run) need a region such as 'us-central1'; "
            "billing-account CUD recommenders use parent 'billingAccounts/{BILLING_ACCOUNT_ID}/locations/global'."
        ),
    }


def _extract_monthly_savings(rec: dict[str, Any]) -> dict[str, Any]:
    """Extract estimated monthly cost savings from a Recommender API recommendation."""
    impact = rec.get("primaryImpact", {})
    cost_proj = impact.get("costProjection", {})
    cost = cost_proj.get("cost", {})
    if not cost:
        return {}
    units = int(cost.get("units", 0))
    nanos = int(cost.get("nanos", 0))
    amount = round(units + nanos / 1e9, 2)
    return {
        "currency": cost.get("currencyCode", "USD"),
        "cost_delta": amount,
        "estimated_monthly_savings": round(-amount, 2) if amount < 0 else 0.0,
        "duration": cost_proj.get("duration", ""),
    }


def check_resource_recommendations(
    project_id: str = "",
    location: str = "us-central1-a",
    service: str = "all",
    billing_account_id: str = "",
) -> dict[str, Any]:
    """Query live FinOps Hub recommendations from `recommender.googleapis.com/v1` before taking actions.

    Checks active recommendations across Compute Engine, GKE, Cloud SQL, Cloud Run,
    and (if `billing_account_id` is provided) Committed Use Discounts (CUDs).

    Args:
        project_id: Target GCP project ID. Defaults to the agent's active project.
        location: GCP zone (e.g. 'us-central1-a') or region (e.g. 'us-central1').
            If a zone is passed, both the zone and derived region are queried automatically.
        service: Service scope to scan ('all', 'compute', 'gke', 'cloudsql', 'cloudrun', 'cud', 'project').
        billing_account_id: Optional Cloud Billing Account ID (e.g. '01ABCD-234567-89EFGH')
            to include Spend-Based and Resource-Based CUD recommendations.

    Returns:
        Structured summary of active FinOps Hub recommendations, estimated savings,
        resource names, etags (for markClaimed/markSucceeded), and any per-recommender errors.
    """
    headers, default_project = get_fresh_gcp_headers(project_id or None)
    target_project = project_id or default_project
    if not target_project:
        return {"error": "No project_id provided and GOOGLE_CLOUD_PROJECT is not set."}

    loc = (location or "us-central1-a").strip()
    parts = loc.split("-")
    is_zone = len(parts) == 3 and len(parts[-1]) == 1
    region = "-".join(parts[:2]) if is_zone else loc

    svc = (service or "all").strip().lower()
    targets: list[tuple[str, str]] = []

    if svc in ("all", "compute"):
        if is_zone:
            targets.extend([
                (f"projects/{target_project}/locations/{loc}", "google.compute.instance.MachineTypeRecommender"),
                (f"projects/{target_project}/locations/{loc}", "google.compute.instance.IdleResourceRecommender"),
                (f"projects/{target_project}/locations/{loc}", "google.compute.disk.IdleResourceRecommender"),
                (f"projects/{target_project}/locations/{loc}", "google.compute.instanceGroupManager.MachineTypeRecommender"),
                (f"projects/{target_project}/locations/{loc}", "google.compute.IdleResourceRecommender"),
                (f"projects/{target_project}/locations/{loc}", "google.compute.RightSizeResourceRecommender"),
            ])
        targets.extend([
            (f"projects/{target_project}/locations/{region}", "google.compute.instanceGroupManager.MachineTypeRecommender"),
            (f"projects/{target_project}/locations/{region}", "google.compute.address.IdleResourceRecommender"),
            (f"projects/{target_project}/locations/global", "google.compute.image.IdleResourceRecommender"),
        ])

    if svc in ("all", "gke"):
        targets.append((f"projects/{target_project}/locations/{region}", "google.container.DiagnosisRecommender"))
        if is_zone:
            targets.append((f"projects/{target_project}/locations/{loc}", "google.container.DiagnosisRecommender"))

    if svc in ("all", "cloudsql"):
        targets.extend([
            (f"projects/{target_project}/locations/{region}", "google.cloudsql.instance.IdleRecommender"),
            (f"projects/{target_project}/locations/{region}", "google.cloudsql.instance.OverprovisionedRecommender"),
            (f"projects/{target_project}/locations/{region}", "google.cloudsql.instance.UnderprovisionedRecommender"),
        ])

    if svc in ("all", "cloudrun"):
        targets.append((f"projects/{target_project}/locations/{region}", "google.run.service.CostRecommender"))

    if svc in ("all", "project"):
        targets.append((f"projects/{target_project}/locations/global", "google.resourcemanager.projectUtilization.Recommender"))

    ba_id = billing_account_id or os.environ.get("BILLING_ACCOUNT_ID", "")
    if svc in ("all", "cud") and ba_id:
        targets.extend([
            (f"billingAccounts/{ba_id}/locations/global", "google.cloudbilling.commitment.SpendBasedCommitmentRecommender"),
            (f"billingAccounts/{ba_id}/locations/{region}", "google.compute.commitment.UsageCommitmentRecommender"),
        ])

    findings: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    seen_targets: set[tuple[str, str]] = set()

    for parent, rec_id in targets:
        if (parent, rec_id) in seen_targets:
            continue
        seen_targets.add((parent, rec_id))

        url = f"{RECOMMENDER_API_BASE}/{parent}/recommenders/{rec_id}/recommendations"
        try:
            resp = requests.get(
                url,
                headers=headers,
                params={"filter": "stateInfo.state=ACTIVE"},
                timeout=12,
            )
            if resp.status_code == 200:
                payload = resp.json()
                for item in payload.get("recommendations", []):
                    findings.append({
                        "name": item.get("name"),
                        "recommender_id": rec_id,
                        "subtype": item.get("recommenderSubtype"),
                        "priority": item.get("priority"),
                        "state": item.get("stateInfo", {}).get("state"),
                        "etag": item.get("etag"),
                        "description": item.get("description"),
                        "cost_impact": _extract_monthly_savings(item),
                        "target_resources": item.get("targetResources", []),
                        "last_refresh_time": item.get("lastRefreshTime"),
                    })
            elif resp.status_code in (403, 404):
                errors.append({
                    "recommender_id": rec_id,
                    "parent": parent,
                    "status": str(resp.status_code),
                    "detail": resp.text[:220],
                })
            else:
                errors.append({
                    "recommender_id": rec_id,
                    "parent": parent,
                    "status": str(resp.status_code),
                    "detail": resp.text[:220],
                })
        except requests.RequestException as exc:
            errors.append({
                "recommender_id": rec_id,
                "parent": parent,
                "status": "NETWORK_ERROR",
                "detail": str(exc),
            })

    total_monthly_savings = round(
        sum(f["cost_impact"].get("estimated_monthly_savings", 0.0) for f in findings), 2
    )

    return {
        "project_id": target_project,
        "location_checked": loc,
        "derived_region": region,
        "service_filter": svc,
        "recommenders_queried": len(seen_targets),
        "active_recommendations_found": len(findings),
        "total_estimated_monthly_savings_usd": total_monthly_savings,
        "recommendations": findings,
        "permission_or_api_notes": errors[:8],
        "guidance": (
            "If active_recommendations_found is 0, remember Active Assist Recommenders require 8-14 days of "
            "utilization history. Also check Cloud Monitoring metrics and Cloud Audit Logs to detect recent "
            "forgotten peak-event scale-ups before taking any action."
        ),
    }


def _update_recommendation_state(
    recommendation_name: str,
    action: str,
    etag: str,
    note: str = "",
) -> dict[str, Any]:
    """Call `:markClaimed` or `:markSucceeded` on `recommender.googleapis.com/v1`."""
    mode = os.environ.get("AGENT_EXECUTION_MODE", "readwrite").strip().lower()
    if mode == "readonly":
        return {
            "status": "BLOCKED_READONLY_MODE",
            "action": action,
            "recommendation_name": recommendation_name,
            "message": (
                "Agent is running in AGENT_EXECUTION_MODE=readonly. "
                "Redeploy with `./deploy.sh --mode readwrite` to allow state updates and resource mutations."
            ),
        }

    headers, _ = get_fresh_gcp_headers()
    url = f"{RECOMMENDER_API_BASE}/{recommendation_name}:{action}"
    body: dict[str, Any] = {"etag": etag}
    if note:
        body["stateMetadata"] = {"agent_note": note, "updated_by": "cloudops_finops_agent"}

    try:
        resp = requests.post(url, headers=headers, json=body, timeout=12)
        if resp.status_code == 200:
            data = resp.json()
            return {
                "status": "OK",
                "action": action,
                "recommendation_name": data.get("name", recommendation_name),
                "new_state": data.get("stateInfo", {}).get("state"),
                "new_etag": data.get("etag"),
            }
        return {
            "status": f"HTTP_{resp.status_code}",
            "action": action,
            "error": resp.text[:400],
        }
    except requests.RequestException as exc:
        return {"status": "NETWORK_ERROR", "action": action, "error": str(exc)}


def mark_recommendation_claimed(
    recommendation_name: str,
    etag: str,
    note: str = "Claimed by CloudOps FinOps Agent prior to remediation",
) -> dict[str, Any]:
    """Claim an active FinOps Hub recommendation (`ACTIVE` -> `CLAIMED`) before applying changes.

    Prevents concurrent engineers or automation jobs from acting on the same finding.
    Save the returned `new_etag` to pass into `mark_recommendation_succeeded`.

    Args:
        recommendation_name: Full resource name returned by `check_resource_recommendations` or `list_recommendations`.
        etag: Current recommendation etag.
        note: Short audit note stored in recommendation stateMetadata.

    Returns:
        Updated recommendation state and `new_etag`.
    """
    return _update_recommendation_state(recommendation_name, "markClaimed", etag, note)


def mark_recommendation_succeeded(
    recommendation_name: str,
    etag: str,
    note: str = "Remediated by CloudOps FinOps Agent with user confirmation",
) -> dict[str, Any]:
    """Mark a claimed FinOps Hub recommendation as `SUCCEEDED` after remediation completes.

    Syncs the applied optimization back into Google Cloud FinOps Hub so realized savings
    and active recommendation counts update accurately.

    Args:
        recommendation_name: Full resource name of the recommendation.
        etag: Latest `new_etag` returned by `mark_recommendation_claimed` (or current etag).
        note: Short audit note stored in recommendation stateMetadata.

    Returns:
        Updated recommendation state confirming `SUCCEEDED`.
    """
    return _update_recommendation_state(recommendation_name, "markSucceeded", etag, note)
