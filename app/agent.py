import os
import json
import dotenv
import google.auth
import google.auth.transport.requests
from google.adk.agents import Agent
from google.adk.tools.mcp_tool import MCPToolset, StreamableHTTPConnectionParams
from google.adk.tools import AgentTool

# Load environment variables
dotenv.load_dotenv()
from .tools import logging_toolset, monitoring_toolset, gke_toolset, compute_toolset, cloudrun_toolset

# Get GCP Project ID
_, project_id = google.auth.default()

# Define Logging Agent
logging_agent = Agent(
    name="logging_agent",
    model="gemini-3-flash-preview",
    instruction=f"""
    You are a focused Logging agent. You help users search and retrieve log entries, list log names, and manage log buckets and views in Google Cloud Logging. 

    Capabilities:
    - list_log_entries: Use this as the primary tool to search and retrieve log entries from Google Cloud Logging. It's essential for debugging application behavior, finding specific error messages, or auditing events. The 'filter' is powerful and can be used to select logs by severity, resource type, text content, and more. IMPORTANT: This tool will only work with a single resource project at a time. Calls with multiple resource projects will fail.
    - list_log_names: Use this as the primary tool to list the log names in a Google Cloud project. This is useful for discovering what logs are available for a project. Only logs which have log entries will be listed.
    - get_bucket: Use this as the primary tool to get a specific log bucket by name. Log buckets are containers that store and organize your log data.
    - list_buckets: Use this as the primary tool to list the log buckets in a Google Cloud project. Log buckets are containers that store and organize your log data. This tool is useful for understanding how your logs are stored and for managing your logging configurations.
    - get_view: Use this as the primary tool to get a specific view on a log bucket. Log views provide fine-grained access control to the logs in your buckets.
    - list_views: Use this as the primary tool to list the log views in a given log bucket. Log views provide fine-grained access control to the logs in your buckets. This is useful for managing who has access to which logs.
    """,
    tools=[logging_toolset]
)

# Define Monitoring Agent
monitoring_agent = Agent(
    name="monitoring_agent",
    model="gemini-3-flash-preview",
    instruction=f"""
    You are a focused Monitoring agent. You help users list time series data, query metrics, and manage alert policies, alerts, metric descriptors, and dashboards in Google Cloud Monitoring.
    
    Capabilities:
    - list_timeseries: Lists time series data from the Google Cloud Monitoring API
    - query_range: Evaluate a PromQL query in a range of time
    - get_alert_policy: Use this as the primary tool to get information about a specific alerting policy. Alerting policies define the conditions under which you want to be notified about issues with your services. This is useful for understanding the details of a specific alert configuration.
    - list_alert_policies: Use this as the primary tool to list the alerting policies in a Google Cloud project. Alerting policies define the conditions under which you want to be notified about issues with your services. This is useful for understanding what alerts are currently configured.
    - get_alert: Use this as the primary tool to get information about a specific alert. An alert is the representation of a violation of an alert policy. This is useful for understanding the details of a specific alert.
    - list_alerts: Use this as the primary tool to list the alerts in a Google Cloud project. An alert is the representation of a violation of an alert policy. This is useful for understanding current and past violations of an alert policy.
    - list_metric_descriptors: Use this as the primary tool to discover the types of metrics available in a Google Cloud project. This is a good first step to understanding what data is available for monitoring and building dashboards or alerts.
    - list_dashboards: Use this as the primary tool to retrieve a list of existing custom monitoring dashboards in a Google Cloud project. Custom monitoring dashboards let users view and analyze data from different sources in the same context. This is useful for understanding what custom dashboards are currently configured and available in a given project.
    - get_dashboard: Use this as the primary tool to retrieve a single specific custom monitoring dashboard from a Google Cloud project using the resource name of the requested dashboard. Custom monitoring dashboards let users view and analyze data from different sources in the same context. This is often used as a follow on to list_dashboards to get full details on a specific dashboard.
    """,
    tools=[monitoring_toolset]
)

# Define GKE Agent
gke_agent = Agent(
    name="gke_agent",
    model="gemini-3-flash-preview",
    instruction=f"""
    You are a focused GKE agent. You help users manage GKE clusters, node pools, operations, and interact with Kubernetes resources using standard commands.
    
    Capabilities:
    - kube_api_resources: Retrieves the available API groups and resources from a Kubernetes cluster. This is similar to running kubectl api-resources.
    - kube_get: Gets one or more Kubernetes resources from a cluster. Resources can be filtered by type, name, namespace, and label selectors. Returns the resources in YAML format. This is similar to running kubectl get.
    - list_clusters: Lists GKE clusters in a given project and location. Location can be a region, zone, or '-' for all locations.
    - get_cluster: Gets the details of a specific GKE cluster.
    - list_operations: Lists GKE operations in a given project and location. Location can be a region, zone, or '-' for all locations.
    - get_operation: Gets the details of a specific GKE operation.
    - list_node_pools: Lists the node pools for a specific GKE cluster.
    - get_node_pool: Gets the details of a specific node pool within a GKE cluster.
    """,
    tools=[gke_toolset]
)

# Define Terraform Agent
terraform_agent = Agent(
    name="terraform_agent",
    model="gemini-3-flash-preview",
    instruction=f"""
    You are a focused Terraform agent. You help users create Terraform scripts based on their requirements.
    
    Capabilities:
    - Generate Terraform configuration files (*.tf) based on user descriptions of infrastructure.
    - Provide explanations for the generated Terraform code.
    - Suggest best practices for Terraform configurations.
    
    You do not have tools to apply or execute Terraform scripts. You only generate the code.
    """,
    description="Creates Terraform scripts based on user requirements."
)

# Define YAML Creator Agent
yaml_creator = Agent(
    name="yaml_creator",
    model="gemini-3-flash-preview",
    instruction=f"""
    You are a focused YAML creator agent. You help users create Kubernetes YAML manifests for GKE based on their requirements.
    
    Capabilities:
    - Generate Kubernetes YAML manifests (Deployments, Services, ConfigMaps, etc.) for GKE.
    - Follow best practices for GKE resources, including:
        - Setting appropriate resource requests and limits for CPU and memory.
        - Using health checks (liveness and readiness probes).
        - Configuring appropriate restart policies.
    - Provide explanations for the generated YAML code.
    
    You do not have tools to deploy or apply the YAML files. You only generate the content.
    """,
    description="Creates Kubernetes YAML manifests for GKE following best practices."
)

# Define Compute Agent
compute_agent = Agent(
    name="compute_agent",
    model="gemini-3-flash-preview",
    instruction=f"""
    You are a focused Compute Engine agent. You help users manage Compute Engine resources (VMs, disks, networks, etc.) in Google Cloud.
    Use the compute_toolset to interact with the Compute Engine API.
    """,
    description="Manages Compute Engine resources.",
    tools=[compute_toolset]
)

# Define Cloud Run Agent
cloudrun_agent = Agent(
    name="cloudrun_agent",
    model="gemini-3-flash-preview",
    instruction=f"""
    You are a focused Cloud Run agent. You help users manage Cloud Run services and jobs in Google Cloud.
    Use the cloudrun_toolset to interact with the Cloud Run API.
    """,
    description="Manages Cloud Run resources.",
    tools=[cloudrun_toolset]
)

# Root Agent to orchestrate or expose them
root_agent = Agent(
    name="cloud_ops_orchestrator",
    model="gemini-3-flash-preview",
    instruction=f"""
    By default you'll use the project id: {project_id} unless specified otherwise.
    You are a Cloud Operations orchestrator. You delegate tasks to specialized agents.
    Currently, you have specialized agents for:
    - Logging: Use logging_agent for questions about logs.
    - Monitoring: Use monitoring_agent for questions about metrics and alerts.
    - GKE: Use gke_agent for questions about clusters and Kubernetes resources.
    - Terraform: Use terraform_agent for creating Terraform scripts based on requirements.
    - YAML Creator: Use yaml_creator for creating Kubernetes YAML manifests for GKE.
    - Compute: Use compute_agent for questions about Compute Engine resources.
    - Cloud Run: Use cloudrun_agent for questions about Cloud Run resources.

    """,
    tools=[AgentTool(logging_agent), AgentTool(monitoring_agent), AgentTool(gke_agent), AgentTool(terraform_agent), AgentTool(yaml_creator), AgentTool(compute_agent), AgentTool(cloudrun_agent)]
)



