import os
import json
import dotenv
import google.auth
import google.auth.transport.requests
from google.adk.agents import Agent
from google.adk.tools import AgentTool
from google.adk.a2a.utils.agent_to_a2a import to_a2a

# Load environment variables
dotenv.load_dotenv()

from .tools import fetch_pending_tickets, resolve_ticket, update_ticket_recommendation, logging_toolset, monitoring_toolset, gke_toolset, compute_toolset, cloudrun_toolset, networkmanagement_toolset

_, project_id = google.auth.default()

root_agent = Agent(
    name="ticket_processing_agent",
    model="gemini-3-flash-preview",
    instruction=f"""
    You are a Ticket Processing agent. You are responsible for fetching tickets from BigQuery and creating Terraform scripts to accommodate those tickets.
    
    By default you'll use the project id: {project_id} unless specified otherwise.
    
    Capabilities:
    1. Fetch pending tickets using the `fetch_pending_tickets` tool.
    2. Analyze the ticket details (type, description, payload).
    3. Check the current environment's condition before making recommendations, using available MCP tools (Compute, GKE, Network Management, etc.).
    4. Generate a recommendation (commands or steps) and store it in the ticket using `update_ticket_recommendation`.
    5. Generate a Terraform script to fulfill the request (e.g., create a firewall rule or load balancer).
    6. Suggest the Terraform script or recommendation to the user.
    7. If the user wants to execute the ticket directly (without Terraform), you can use the available MCP tools (Compute, GKE, Cloud Run, Network Management, etc.) to perform the actions.
    8. Resolve tickets by updating their status to 'resolved' using the `resolve_ticket` tool after fulfillment.
    
    Workflow:
    - Start by fetching pending tickets if the user asks to process tickets or check for new tickets.
    - For each ticket, check the environment conditions relevant to the request.
    - Generate recommended commands or actions and save them using `update_ticket_recommendation`.
    - Generate corresponding Terraform code if applicable and present it as a suggestion.
    - Wait for user confirmation or further instructions.
    - After a ticket is fulfilled, use `resolve_ticket` to update its status.
    """,
    tools=[fetch_pending_tickets, resolve_ticket, update_ticket_recommendation, logging_toolset, monitoring_toolset, gke_toolset, compute_toolset, cloudrun_toolset, networkmanagement_toolset]
)


a2a_app = to_a2a(root_agent, port=8001)