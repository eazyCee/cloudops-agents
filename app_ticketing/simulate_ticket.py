import os
import json
import uuid
import urllib.request
import urllib.parse
from google.cloud import bigquery
import dotenv

# Load environment variables
dotenv.load_dotenv()

def simulate_ticket():
    ticket_id = f"TICKET-{uuid.uuid4().hex[:6].upper()}"
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "your-project-id")
    
    ticket = {
        "ticket_id": ticket_id,
        "project_id": project_id,
        "requester": "user@example.com",
        "type": "firewall_rule",
        "status": "pending",
        "description": "Allow inbound TCP traffic on port 8080 from 10.0.0.0/8",
        "payload": json.dumps({
            "port": 8080,
            "protocol": "TCP",
            "source_range": "10.0.0.0/8",
            "action": "allow"
        })
    }
    
    # 1. Insert into BigQuery
    client = bigquery.Client()
    # Assuming table is 'tickets' in default dataset
    table_id = "tickets"
    
    rows_to_insert = [ticket]
    
    try:
        # insert_rows_json requires full table reference if not using default dataset
        # Let's assume default dataset is set in the environment or client
        errors = client.insert_rows_json(table_id, rows_to_insert)
        if errors == []:
            print(f"Successfully inserted ticket {ticket_id} into BigQuery.")
        else:
            print(f"Errors inserting ticket: {errors}")
            return
    except Exception as e:
        print(f"Exception inserting ticket: {e}")
        print("Please make sure the table 'tickets' exists in the default dataset.")
        return

    # 2. Trigger Agent (direct call for simulation)
    # Assume agent is running on localhost:8002 for processing
    url = "http://localhost:8002/webhook/ticket-created"
    
    data = json.dumps({"ticket_id": ticket_id}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    
    try:
        print(f"Triggering agent at {url}...")
        with urllib.request.urlopen(req) as response:
            res_data = response.read().decode("utf-8")
            print(f"Triggered agent response: {res_data}")
    except Exception as e:
        print(f"Error triggering agent: {e}")
        print("Please make sure the processing agent is running on port 8002.")

if __name__ == "__main__":
    simulate_ticket()
