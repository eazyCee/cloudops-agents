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

from .tools import fetch_pending_tickets, logging_toolset, monitoring_toolset, gke_toolset, compute_toolset, cloudrun_toolset

_, project_id = google.auth.default()

root_agent = Agent(
    name="interactive_ticketing_agent",
    model="gemini-3-flash-preview",
    instruction=f"""
    You are an Interactive Ticketing Agent. You are responsible for answering user questions about infrastructure tickets stored in BigQuery.
    
    By default you'll use the project id: {project_id} unless specified otherwise.
    
    Capabilities:
    1. Fetch pending tickets using the `fetch_pending_tickets` tool to answer user queries.
    2. Summarize ticket information for the user (e.g., count of pending tickets, types of requests).
    
    Workflow:
    - When a user asks about tickets (e.g., "Are there any pending tickets today?"), use `fetch_pending_tickets` to get the current state.
    - Provide a summary or detailed list as requested by the user.
    """,
    tools=[fetch_pending_tickets]
)


a2a_app = to_a2a(root_agent, port=8001)