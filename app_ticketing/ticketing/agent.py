import os
import json
import dotenv
from google.adk.agents import Agent
from google.adk.tools import AgentTool
from google.adk.a2a.utils.agent_to_a2a import to_a2a

# Load environment variables
dotenv.load_dotenv()

from .tools import fetch_pending_tickets, logging_toolset, monitoring_toolset, gke_toolset, compute_toolset, cloudrun_toolset, get_project_id

project_id = get_project_id()

root_agent = Agent(
    name="ticket_processing_agent",
    model="gemini-3-flash-preview",
    instruction=f"""
    You are a Ticket Processing agent. You are responsible for fetching tickets from BigQuery and creating Terraform scripts to accommodate those tickets.
    
    By default you'll use the project id: {project_id} unless specified otherwise.
    
    Capabilities:
    1. Fetch pending tickets using the `fetch_pending_tickets` tool.
    2. Analyze the ticket details (type, description, payload).
    3. Generate a Terraform script to fulfill the request (e.g., create a firewall rule or load balancer).
    4. Suggest the Terraform script to the user.
    5. If the user wants to execute the ticket directly (without Terraform), you can use the available MCP tools (Compute, GKE, Cloud Run, etc.) to perform the actions.
    
    Workflow:
    - Start by fetching pending tickets if the user asks to process tickets or check for new tickets.
    - For each ticket, generate the corresponding Terraform code and present it as a suggestion.
    - Wait for user confirmation or further instructions.
    """,
    tools=[fetch_pending_tickets, logging_toolset, monitoring_toolset, gke_toolset, compute_toolset, cloudrun_toolset]
)


a2a_app = to_a2a(root_agent, port=8001)