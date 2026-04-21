import os
import json
import base64
from fastapi import FastAPI, Request, HTTPException
import dotenv
import google.auth
from google.cloud import bigquery
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

# Load environment variables
dotenv.load_dotenv()

from .tools import update_ticket_recommendation

_, project_id = google.auth.default()

# Define the Processing Agent
processing_agent = Agent(
    name="ticket_processing_agent",
    model="gemini-3-flash-preview",
    instruction="""
    You are a Ticket Processing Agent. Your job is to analyze a ticket and generate a recommendation or Terraform script to fulfill the request.
    
    You will be given the ticket details in the message.
    Generate a recommendation and use the `update_ticket_recommendation` tool to save it back to the ticket in BigQuery.
    Set the status to 'processed' or 'action_required' based on your analysis.
    """,
    tools=[update_ticket_recommendation]
)

app = FastAPI()
session_service = InMemorySessionService()

@app.post("/webhook/ticket-created")
async def handle_ticket_created(request: Request):
    """Handles Pub/Sub push messages for new tickets."""
    try:
        envelope = await request.json()
        if not envelope:
            raise HTTPException(status_code=400, detail="No JSON payload received")
        
        pubsub_message = envelope.get("message")
        ticket_id = None
        
        if pubsub_message and "data" in pubsub_message:
            # Real Pub/Sub message
            data = base64.b64decode(pubsub_message["data"]).decode("utf-8")
            try:
                payload = json.loads(data)
                ticket_id = payload.get("ticket_id")
            except json.JSONDecodeError:
                ticket_id = data # assume it's just the ID string
        else:
             # Direct trigger (simulation)
             ticket_id = envelope.get("ticket_id")

        if not ticket_id:
            raise HTTPException(status_code=400, detail="No ticket_id found in request")

        # Fetch ticket details from BigQuery
        client = bigquery.Client()
        # Assuming table is 'tickets' in default dataset
        query = f"SELECT ticket_id, project_id, requester, type, status, description, payload FROM `tickets` WHERE ticket_id = '{ticket_id}'"
        query_job = client.query(query)
        results = query_job.result()
        
        ticket = None
        for row in results:
            ticket = {
                "ticket_id": row.ticket_id,
                "project_id": row.project_id,
                "requester": row.requester,
                "type": row.type,
                "status": row.status,
                "description": row.description,
                "payload": json.loads(row.payload) if isinstance(row.payload, str) else row.payload
            }
            break
            
        if not ticket:
             raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found")

        # Run the agent
        await session_service.create_session(app_name="ticketing", user_id="system", session_id=ticket_id)
        runner = Runner(agent=processing_agent, app_name="ticketing", session_service=session_service)
        
        message = f"Please process this ticket: {json.dumps(ticket)}"
        
        async for event in runner.run_async(
            user_id="system", session_id=ticket_id,
            new_message=types.Content(role="user", parts=[types.Part.from_text(text=message)]),
        ):
            if event.is_final_response():
                return {"status": "success", "response": event.content.parts[0].text}

        return {"status": "success", "message": "Agent finished processing."}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
