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
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import google.auth
import google.auth.transport.requests
import requests

RECOMMENDER_API_BASE = "https://recommender.googleapis.com/v1"
COMPUTE_API_BASE = "https://compute.googleapis.com/compute/v1"
CONTAINER_API_BASE = "https://container.googleapis.com/v1"
CLOUDRUN_API_BASE = "https://run.googleapis.com/v2"
CLOUDSQL_API_BASE = "https://sqladmin.googleapis.com/v1"

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


def _is_gcp_zone(loc: str) -> bool:
    parts = loc.split("-")
    return len(parts) == 3 and len(parts[-1]) == 1 and parts[-1].isalpha()


def _region_from_zone(zone: str) -> str:
    parts = zone.split("-")
    return "-".join(parts[:2]) if len(parts) >= 2 else zone


def _discover_active_locations(
    target_project: str,
    headers: dict[str, str],
) -> dict[str, Any]:
    """Discover all active GCP zones, regions, and compact resource inventory in parallel."""
    zones: set[str] = set()
    regions: set[str] = set()
    vms: list[dict[str, str]] = []
    disks: list[dict[str, Any]] = []
    unattached_disks: list[dict[str, Any]] = []
    gke_clusters: list[dict[str, str]] = []
    cloudrun_by_region: dict[str, int] = {}
    cloudsql_instances: list[dict[str, str]] = []
    addresses_by_scope: dict[str, int] = {}
    discovery_notes: list[str] = []

    def _get(label: str, url: str) -> tuple[str, dict[str, Any] | None, str | None]:
        try:
            resp = requests.get(url, headers=headers, timeout=12)
            if resp.status_code == 200:
                return label, resp.json(), None
            return label, None, f"{label}: HTTP {resp.status_code}"
        except requests.RequestException as exc:
            return label, None, f"{label}: {exc}"

    probes = [
        ("compute_instances", f"{COMPUTE_API_BASE}/projects/{target_project}/aggregated/instances"),
        ("compute_disks", f"{COMPUTE_API_BASE}/projects/{target_project}/aggregated/disks"),
        ("compute_addresses", f"{COMPUTE_API_BASE}/projects/{target_project}/aggregated/addresses"),
        ("gke_clusters", f"{CONTAINER_API_BASE}/projects/{target_project}/locations/-/clusters"),
        ("cloudrun_services", f"{CLOUDRUN_API_BASE}/projects/{target_project}/locations/-/services"),
        ("cloudsql_instances", f"{CLOUDSQL_API_BASE}/projects/{target_project}/instances"),
    ]

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda p: _get(p[0], p[1]), probes))

    for label, payload, err in results:
        if err:
            discovery_notes.append(err)
            continue
        if not payload:
            continue

        if label == "compute_instances":
            for scope, data in payload.get("items", {}).items():
                items = data.get("instances") or []
                if not items:
                    continue
                if scope.startswith("zones/"):
                    z = scope.split("/", 1)[1]
                    zones.add(z)
                    regions.add(_region_from_zone(z))
                for inst in items:
                    z_name = (inst.get("zone") or "").rsplit("/", 1)[-1]
                    mt = (inst.get("machineType") or "").rsplit("/", 1)[-1]
                    vms.append({
                        "name": inst.get("name", ""),
                        "zone": z_name,
                        "machine_type": mt,
                        "status": inst.get("status", ""),
                    })

        elif label == "compute_disks":
            for scope, data in payload.get("items", {}).items():
                items = data.get("disks") or []
                if not items:
                    continue
                if scope.startswith("zones/"):
                    z = scope.split("/", 1)[1]
                    zones.add(z)
                    regions.add(_region_from_zone(z))
                elif scope.startswith("regions/"):
                    regions.add(scope.split("/", 1)[1])
                for d in items:
                    loc_name = (d.get("zone") or d.get("region") or "").rsplit("/", 1)[-1]
                    attached = bool(d.get("users"))
                    entry = {
                        "name": d.get("name", ""),
                        "location": loc_name,
                        "size_gb": d.get("sizeGb", ""),
                        "type": (d.get("type") or "").rsplit("/", 1)[-1],
                        "attached": attached,
                    }
                    disks.append(entry)
                    if not attached:
                        unattached_disks.append(entry)

        elif label == "compute_addresses":
            for scope, data in payload.get("items", {}).items():
                items = data.get("addresses") or []
                if not items:
                    continue
                addresses_by_scope[scope] = len(items)
                if scope.startswith("regions/"):
                    regions.add(scope.split("/", 1)[1])

        elif label == "gke_clusters":
            for c in payload.get("clusters", []) or []:
                loc = c.get("location", "")
                if _is_gcp_zone(loc):
                    zones.add(loc)
                    regions.add(_region_from_zone(loc))
                elif loc:
                    regions.add(loc)
                gke_clusters.append({
                    "name": c.get("name", ""),
                    "location": loc,
                    "status": c.get("status", ""),
                    "current_node_count": str(c.get("currentNodeCount", "")),
                })

        elif label == "cloudrun_services":
            for s in payload.get("services", []) or []:
                parts = (s.get("name") or "").split("/")
                reg = parts[3] if len(parts) > 3 else ""
                if reg:
                    regions.add(reg)
                    cloudrun_by_region[reg] = cloudrun_by_region.get(reg, 0) + 1

        elif label == "cloudsql_instances":
            for inst in payload.get("items", []) or []:
                reg = inst.get("region", "")
                if reg:
                    regions.add(reg)
                cloudsql_instances.append({
                    "name": inst.get("name", ""),
                    "region": reg,
                    "tier": inst.get("settings", {}).get("tier", ""),
                    "state": inst.get("state", ""),
                })

    return {
        "project_id": target_project,
        "active_zones": sorted(zones),
        "active_regions": sorted(regions),
        "counts": {
            "vms": len(vms),
            "disks": len(disks),
            "unattached_disks": len(unattached_disks),
            "gke_clusters": len(gke_clusters),
            "cloudrun_services": sum(cloudrun_by_region.values()),
            "cloudsql_instances": len(cloudsql_instances),
        },
        "vms": vms[:50],
        "disks": disks[:50],
        "unattached_disks": unattached_disks[:25],
        "gke_clusters": gke_clusters[:25],
        "cloudrun_services_by_region": cloudrun_by_region,
        "cloudsql_instances": cloudsql_instances[:25],
        "static_addresses_by_scope": addresses_by_scope,
        "discovery_notes": discovery_notes,
    }


def discover_project_locations(project_id: str = "") -> dict[str, Any]:
    """Auto-discover all active GCP zones, regions, and resources across a project.

    Use this BEFORE calling zone-scoped Compute Engine MCP tools (`list_instances`,
    `list_disks`) or Recommender MCP tools (`list_recommendations`) when the user does
    not specify a zone or region, because Google Cloud Compute and Recommender APIs
    require exact zone/region names and do not support wildcard `locations/-`.

    Args:
        project_id: Target GCP project ID. Defaults to the agent's active project.

    Returns:
        Sorted `active_zones`, `active_regions`, resource counts, and compact inventory
        of VMs, disks (flagging unattached disks), GKE clusters, Cloud Run services, and Cloud SQL.
    """
    headers, default_project = get_fresh_gcp_headers(project_id or None)
    target_project = project_id or default_project
    if not target_project:
        return {"error": "No project_id provided and GOOGLE_CLOUD_PROJECT is not set."}
    return _discover_active_locations(target_project, headers)


def check_resource_recommendations(
    project_id: str = "",
    location: str = "auto",
    service: str = "all",
    billing_account_id: str = "",
) -> dict[str, Any]:
    """Query live FinOps Hub recommendations from `recommender.googleapis.com/v1` before taking actions.

    Because Google Cloud's Recommender API does not support wildcard `locations/-`, passing
    `location="auto"` (the default) automatically discovers EVERY active zone and region in the
    project (across Compute Engine VMs/disks/IPs, GKE, Cloud Run, and Cloud SQL) and scans all
    applicable FinOps Hub recommenders in parallel.

    Args:
        project_id: Target GCP project ID. Defaults to the agent's active project.
        location: Pass `'auto'` (default) to auto-discover and scan ALL active zones and regions
            in the project, OR pass a specific GCP zone (e.g. `'asia-southeast2-a'`) or region
            (e.g. `'asia-southeast2'`).
        service: Service scope to scan ('all', 'compute', 'gke', 'cloudsql', 'cloudrun', 'cud', 'project').
        billing_account_id: Optional Cloud Billing Account ID (e.g. '01ABCD-234567-89EFGH')
            to include Spend-Based and Resource-Based CUD recommendations.

    Returns:
        Structured summary of scanned zones/regions, active FinOps Hub recommendations,
        estimated monthly savings, resource names, etags (for markClaimed/markSucceeded),
        and any per-recommender errors.
    """
    headers, default_project = get_fresh_gcp_headers(project_id or None)
    target_project = project_id or default_project
    if not target_project:
        return {"error": "No project_id provided and GOOGLE_CLOUD_PROJECT is not set."}

    loc = (location or "auto").strip()
    zones_to_scan: list[str] = []
    regions_to_scan: list[str] = []
    discovered_summary: dict[str, Any] | None = None

    if loc.lower() in ("auto", "all", "*", ""):
        discovery = _discover_active_locations(target_project, headers)
        zones_to_scan = discovery["active_zones"]
        regions_to_scan = discovery["active_regions"]
        discovered_summary = discovery["counts"]
        if not zones_to_scan and not regions_to_scan:
            fallback_region = os.environ.get("GOOGLE_CLOUD_REGION", "us-central1").strip() or "us-central1"
            regions_to_scan = [fallback_region]
            zones_to_scan = [f"{fallback_region}-a"]
    elif loc.lower() == "global":
        pass
    elif _is_gcp_zone(loc):
        zones_to_scan = [loc]
        regions_to_scan = [_region_from_zone(loc)]
    else:
        regions_to_scan = [loc]

    svc = (service or "all").strip().lower()
    targets: list[tuple[str, str]] = []

    if svc in ("all", "compute"):
        for z in zones_to_scan:
            targets.extend([
                (f"projects/{target_project}/locations/{z}", "google.compute.instance.MachineTypeRecommender"),
                (f"projects/{target_project}/locations/{z}", "google.compute.instance.IdleResourceRecommender"),
                (f"projects/{target_project}/locations/{z}", "google.compute.disk.IdleResourceRecommender"),
                (f"projects/{target_project}/locations/{z}", "google.compute.instanceGroupManager.MachineTypeRecommender"),
                (f"projects/{target_project}/locations/{z}", "google.compute.IdleResourceRecommender"),
                (f"projects/{target_project}/locations/{z}", "google.compute.RightSizeResourceRecommender"),
            ])
        for reg in regions_to_scan:
            targets.extend([
                (f"projects/{target_project}/locations/{reg}", "google.compute.instanceGroupManager.MachineTypeRecommender"),
                (f"projects/{target_project}/locations/{reg}", "google.compute.disk.IdleResourceRecommender"),
                (f"projects/{target_project}/locations/{reg}", "google.compute.address.IdleResourceRecommender"),
            ])
        targets.extend([
            (f"projects/{target_project}/locations/global", "google.compute.image.IdleResourceRecommender"),
            (f"projects/{target_project}/locations/global", "google.compute.address.IdleResourceRecommender"),
        ])

    if svc in ("all", "gke"):
        for reg in regions_to_scan:
            targets.append((f"projects/{target_project}/locations/{reg}", "google.container.DiagnosisRecommender"))
        for z in zones_to_scan:
            targets.append((f"projects/{target_project}/locations/{z}", "google.container.DiagnosisRecommender"))

    if svc in ("all", "cloudsql"):
        for reg in regions_to_scan:
            targets.extend([
                (f"projects/{target_project}/locations/{reg}", "google.cloudsql.instance.IdleRecommender"),
                (f"projects/{target_project}/locations/{reg}", "google.cloudsql.instance.OverprovisionedRecommender"),
                (f"projects/{target_project}/locations/{reg}", "google.cloudsql.instance.UnderprovisionedRecommender"),
            ])

    if svc in ("all", "cloudrun"):
        for reg in regions_to_scan:
            targets.append((f"projects/{target_project}/locations/{reg}", "google.run.service.CostRecommender"))

    if svc in ("all", "project"):
        targets.append((f"projects/{target_project}/locations/global", "google.resourcemanager.projectUtilization.Recommender"))

    ba_id = billing_account_id or os.environ.get("BILLING_ACCOUNT_ID", "")
    if svc in ("all", "cud") and ba_id:
        targets.append((f"billingAccounts/{ba_id}/locations/global", "google.cloudbilling.commitment.SpendBasedCommitmentRecommender"))
        for reg in regions_to_scan:
            targets.append((f"billingAccounts/{ba_id}/locations/{reg}", "google.compute.commitment.UsageCommitmentRecommender"))

    unique_targets = list(dict.fromkeys(targets))

    def _query_one(target: tuple[str, str]) -> tuple[list[dict[str, Any]], dict[str, str] | None]:
        parent, rec_id = target
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
                local_findings: list[dict[str, Any]] = []
                for item in payload.get("recommendations", []):
                    local_findings.append({
                        "name": item.get("name"),
                        "location": parent.split("/locations/", 1)[-1],
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
                return local_findings, None
            return [], {
                "recommender_id": rec_id,
                "parent": parent,
                "status": str(resp.status_code),
                "detail": resp.text[:220],
            }
        except requests.RequestException as exc:
            return [], {
                "recommender_id": rec_id,
                "parent": parent,
                "status": "NETWORK_ERROR",
                "detail": str(exc),
            }

    findings: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    max_workers = min(16, max(1, len(unique_targets)))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for local_findings, err in pool.map(_query_one, unique_targets):
            findings.extend(local_findings)
            if err:
                errors.append(err)

    findings.sort(
        key=lambda f: f.get("cost_impact", {}).get("estimated_monthly_savings", 0.0),
        reverse=True,
    )
    total_monthly_savings = round(
        sum(f["cost_impact"].get("estimated_monthly_savings", 0.0) for f in findings), 2
    )

    result: dict[str, Any] = {
        "project_id": target_project,
        "location_mode": loc,
        "zones_scanned": zones_to_scan,
        "regions_scanned": regions_to_scan,
        "global_scanned": True,
        "service_filter": svc,
        "recommenders_queried": len(unique_targets),
        "active_recommendations_found": len(findings),
        "total_estimated_monthly_savings_usd": total_monthly_savings,
        "recommendations": findings,
        "permission_or_api_notes": errors[:8],
        "guidance": (
            "If active_recommendations_found is 0 for a specific workload, remember Active Assist Recommenders "
            "require 8-14 days of continuous utilization history. Correlate with Cloud Monitoring metrics and "
            "Cloud Audit Logs to detect recent forgotten peak-event scale-ups before taking any action."
        ),
    }
    if discovered_summary is not None:
        result["discovered_resource_counts"] = discovered_summary
    return result


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
