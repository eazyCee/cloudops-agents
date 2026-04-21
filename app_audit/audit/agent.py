import os
import json
import dotenv
import google.auth
import google.auth.transport.requests
from google.adk.agents import Agent
from google.adk.a2a.utils.agent_to_a2a import to_a2a


_, project_id = google.auth.default()
# Load environment variables
dotenv.load_dotenv()

from .tools import github_toolset, gke_toolset

_, project_id = google.auth.default()

root_agent = Agent(
    name="gke_audit_agent",
    model="gemini-3-flash-preview",
    instruction=f"""
    You are a GKE Audit agent. Your responsibility is to audit the current GKE configuration against a reference stored in GitHub.
    
    By default you'll use the project id: {project_id} unless specified otherwise.
    
    Workflow:
    1. The reference terraform files will be stored in https://github.com/GoogleCloudPlatform/cloud-foundation-fabric.git
    2. Use the `github_toolset` to fetch the reference content (e.g., using `get_file_contents`).
    3. Use the `gke_toolset` to inspect the current state of the GKE cluster (e.g., list clusters, get cluster details, list node pools).
    4. Compare the reference configuration with the live configuration.
    5. Report any discrepancies and recommend the fixes, also align them with best practices.
    
    You have access to `gke_toolset` which provides tools like `list_clusters`, `get_cluster`, `kube_get`, etc.
    You also have access to `github_toolset` which provides tools to interact with GitHub.
    """,
    tools=[github_toolset, gke_toolset]
)

a2a_app = to_a2a(root_agent, port=8001)