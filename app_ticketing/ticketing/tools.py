import os
import json
import sys
import dotenv
import google.auth
import google.auth.transport.requests
from google.cloud import bigquery
from google.adk.tools import ToolContext
from google.adk.tools.mcp_tool import MCPToolset, StreamableHTTPConnectionParams
dotenv.load_dotenv()


def get_gcp_oauth_token():
    """Retrieves a GCP OAuth token."""
    credentials, project_id = google.auth.default(
        scopes=[
            'https://www.googleapis.com/auth/cloud-platform'
            ]
    )
    credentials.refresh(google.auth.transport.requests.Request())
    return credentials.token, project_id

def load_mcp_tools(config_path: str) -> dict:
    """Loads MCP tools based on a configuration file and returns a dict."""
    tools = {}
    if not os.path.exists(config_path):
        print(f"Warning: Config file not found at {config_path}")
        return tools

    try:
        oauth_token, project_id = get_gcp_oauth_token()
        print(project_id)
        HEADERS_WITH_OAUTH = {
            "Authorization": f"Bearer {oauth_token}",
            "x-goog-user-project": project_id
        }

        with open(config_path, 'r') as f:
            config = json.load(f)
            
        for server in config:
            name = server.get("name")
            url = server.get("url")
            auth_type = server.get("auth_type")
            
            if url and not url.startswith("PLACEHOLDER"):
                print(f"Loading MCP server: {name} via HTTP")
                
                headers = {}
                if auth_type == "gcp_oauth":
                    headers = HEADERS_WITH_OAUTH
                
                toolset = MCPToolset(
                    connection_params=StreamableHTTPConnectionParams(
                        url=url,
                        headers=headers,
                        sse_read_timeout=600.0
                    )
                )
                tools[name] = toolset
                print(f"MCP Toolset configured for {name}.")
            else:
                print(f"Skipping {name} due to placeholder URL.")
                    
    except Exception as e:
        print(f"Error loading MCP config: {e}")
        
    return tools

def fetch_pending_tickets() -> dict:
    """Fetches pending tickets from BigQuery.

    Returns:
        dict: A dictionary with status and a list of tickets.
    """
    client = bigquery.Client()
    # Assuming table is 'tickets' in default dataset
    # We should probably make this configurable
    query = """
        SELECT ticket_id, project_id, requester, type, status, description, payload
        FROM `tickets`
        WHERE status = 'pending'
        LIMIT 10
    """
    try:
        query_job = client.query(query)
        results = query_job.result()
        
        tickets = []
        for row in results:
            tickets.append({
                "ticket_id": row.ticket_id,
                "project_id": row.project_id,
                "requester": row.requester,
                "type": row.type,
                "status": row.status,
                "description": row.description,
                "payload": json.loads(row.payload) if isinstance(row.payload, str) else row.payload
            })
        return {"status": "success", "tickets": tickets}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def resolve_ticket(ticket_id: str) -> dict:
    """Updates the status of a ticket to 'resolved' in BigQuery.

    Args:
        ticket_id: The ID of the ticket to resolve.

    Returns:
        dict: A dictionary with status and a message.
    """
    client = bigquery.Client()
    query = """
        UPDATE `tickets`
        SET status = 'resolved'
        WHERE ticket_id = @ticket_id
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("ticket_id", "STRING", ticket_id),
        ]
    )
    try:
        query_job = client.query(query, job_config=job_config)
        query_job.result()
        return {"status": "success", "message": f"Ticket {ticket_id} resolved."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def update_ticket_recommendation(ticket_id: str, recommendation: str) -> dict:
    """Updates the recommendation for a ticket in BigQuery.

    Args:
        ticket_id: The ID of the ticket to update.
        recommendation: The recommended commands to execute.

    Returns:
        dict: A dictionary with status and a message.
    """
    client = bigquery.Client()
    query = """
        UPDATE `tickets`
        SET recommendation = @recommendation
        WHERE ticket_id = @ticket_id
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("recommendation", "STRING", recommendation),
            bigquery.ScalarQueryParameter("ticket_id", "STRING", ticket_id),
        ]
    )
    try:
        query_job = client.query(query, job_config=job_config)
        query_job.result()
        return {"status": "success", "message": f"Ticket {ticket_id} recommendation updated."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# Path to config file in app directory
config_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "mcp_config.json"))
mcp_toolsets = load_mcp_tools(config_file)

# Expose toolsets for the agent
logging_toolset = mcp_toolsets.get("logging")
monitoring_toolset = mcp_toolsets.get("monitoring")
gke_toolset = mcp_toolsets.get("gke")
compute_toolset = mcp_toolsets.get("compute")
cloudrun_toolset = mcp_toolsets.get("cloudrun")
networkmanagement_toolset = mcp_toolsets.get("networkmanagement")
