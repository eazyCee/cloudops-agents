# Agent Ticketing System

This directory contains the ticketing service for the CloudOps Agents project. It features a specialized agent that processes infrastructure requests by reading from a BigQuery table, analyzing the environment, and providing recommendations or executing actions.

## Overview

The `ticket_processing_agent` is designed to:
1.  **Fetch** pending tickets from a BigQuery table.
2.  **Analyze** ticket details (type, description, payload).
3.  **Check** current environment conditions using Google Cloud MCP tools.
4.  **Recommend** commands or actions and store them back in the ticket.
5.  **Generate** Terraform scripts or directly execute tasks to fulfill requests.
6.  **Resolve** tickets by updating their status in BigQuery.

## Directory Structure

```text
app_ticketing/
├── ticketing/
│   ├── __init__.py
│   ├── agent.py          # Agent definition and instructions
│   ├── tools.py          # BigQuery tools and MCP loaders
│   └── mcp_config.json   # Configuration for GCP MCP servers
├── Dockerfile            # Containerization setup
└── requirements.txt      # Python dependencies
```

## BigQuery Setup

The agent expects a BigQuery table to store and retrieve tickets. Follow these steps to set it up.

### 1. Create Dataset

Use the `bq` command-line tool to create a dataset. Replace `<PROJECT_ID>` and `<DATASET_NAME>` with your values.

```bash
bq mk --dataset_id=<PROJECT_ID>:<DATASET_NAME>
```

### 2. Create Table

You can create the table using SQL or the `bq` CLI.

#### Option A: SQL Creation (Recommended)

Run this SQL query in the BigQuery console or using `bq query`:

```sql
CREATE TABLE `<PROJECT_ID>.<DATASET_NAME>.tickets` (
  ticket_id STRING,
  project_id STRING,
  requester STRING,
  type STRING,
  status STRING,
  description STRING,
  payload JSON,
  recommendation STRING,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### Option B: CLI Creation

```bash
bq mk --table <PROJECT_ID>:<DATASET_NAME>.tickets \
  ticket_id:STRING,project_id:STRING,requester:STRING,type:STRING,status:STRING,description:STRING,payload:JSON,recommendation:STRING,created_at:TIMESTAMP
```

### 3. Permissions

Ensure the service account used by the agent has the following roles:
- `roles/bigquery.dataEditor` on the dataset.
- `roles/bigquery.jobUser` on the project.

## Running the Agent

### Locally

1.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
2.  Run the agent using `uvicorn` from the `app_ticketing` directory:
    ```bash
    uvicorn ticketing.agent:a2a_app --host 0.0.0.0 --port 8001
    ```

### Via Docker

1.  Build the image:
    ```bash
    docker build -t ticketing-agent .
    ```
2.  Run the container:
    ```bash
    docker run -p 8001:8001 ticketing-agent
    ```

## Simulating a Ticket

To simulate a new ticket for the agent to process, you can insert a row into the table:

```sql
INSERT INTO `<PROJECT_ID>.<DATASET_NAME>.tickets` (ticket_id, project_id, requester, type, status, description, payload)
VALUES (
  'TICKET-001',
  '<TARGET_PROJECT_ID>',
  'user@example.com',
  'connectivity_check',
  'pending',
  'Check connectivity from source to destination',
  JSON '{"source": "10.0.0.1", "destination": "10.0.0.2"}'
);
```
