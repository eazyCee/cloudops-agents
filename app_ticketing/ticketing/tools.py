import os
import json
import sys
from google.cloud import bigquery
from google.adk.tools import ToolContext

# Add parent directory to path to allow imports from app
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.tools import load_mcp_tools, get_project_id

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

# Path to config file in app directory
config_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "../app/mcp_config.json"))
mcp_toolsets = load_mcp_tools(config_file)

# Expose toolsets for the agent
logging_toolset = mcp_toolsets.get("logging")
monitoring_toolset = mcp_toolsets.get("monitoring")
gke_toolset = mcp_toolsets.get("gke")
compute_toolset = mcp_toolsets.get("compute")
cloudrun_toolset = mcp_toolsets.get("cloudrun")
