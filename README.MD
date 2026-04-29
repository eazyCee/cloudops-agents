# CloudOps Agents Project

This repository contains a multi-agent system for automating cloud operations. It includes specialized agents for various tasks like ticketing, auditing, and general cloud management.

## Directory Structure

- `app/`: General cloud management agent (CloudOps Orchestrator).
- `app_audit/`: GKE Audit agent.
- `app_ticketing/`: Ticket processing agent.
- `app_simulation/`: (Empty) Planned for simulation.

---

# Cloud Operations Orchestrator (`app`)

The `cloud_ops_orchestrator` is a multi-agent system that delegates tasks to specialized sub-agents for managing various Google Cloud services.

## Sub-Agents

- **`logging_agent`**: Searches and retrieves log entries, manages log buckets and views.
- **`monitoring_agent`**: Queries metrics, manages alert policies, alerts, and dashboards.
- **`gke_agent`**: Manages GKE clusters and operations, and interacts with Kubernetes resources.
- **`terraform_agent`**: Generates Terraform scripts based on user requirements.
- **`yaml_creator`**: Generates Kubernetes YAML manifests for GKE following best practices.
- **`compute_agent`**: Manages Compute Engine resources (VMs, disks, networks).
- **`cloudrun_agent`**: Manages Cloud Run services and jobs.

---

# GKE Audit Agent (`app_audit`)

The `gke_audit_agent` is responsible for auditing live GKE cluster configurations against a reference stored in a GitHub repository.

## Overview

The agent:
1.  Fetches reference Terraform files from GitHub using `github_toolset`.
2.  Inspects the current state of the GKE cluster using `gke_toolset`.
3.  Compares the reference configuration with the live configuration.
4.  Reports discrepancies and recommends fixes aligned with best practices.

---

# Agent Ticketing System (`app_ticketing`)

The ticketing service processes infrastructure requests by reading from a BigQuery table, analyzing the environment, and providing recommendations or executing actions.

## Overview

The `ticket_processing_agent` is designed to:
1.  **Fetch** pending tickets from a BigQuery table.
2.  **Analyze** ticket details (type, description, payload).
3.  **Check** current environment conditions using Google Cloud MCP tools.
4.  **Recommend** commands or actions and store them back in the ticket.
5.  **Generate** Terraform scripts or directly execute tasks to fulfill requests.
6.  **Resolve** tickets by updating their status in BigQuery.

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

---

## Running the Agents

All agents are exposed as A2A services and can be run using `uvicorn` or Docker.

### Example: Running `app_ticketing` Locally

1.  Install dependencies:
    ```bash
    pip install -r app_ticketing/requirements.txt
    ```
2.  Run the agent using `uvicorn` from the `app_ticketing` directory:
    ```bash
    cd app_ticketing
    uvicorn ticketing.agent:a2a_app --host 0.0.0.0 --port 8001
    ```

### Example: Running `app` Locally

1.  Install dependencies:
    ```bash
    pip install -r app/requirements.txt
    ```
2.  Run the agent using `uvicorn` from the `app` directory:
    ```bash
    cd app
    uvicorn cloudops.agent:a2a_app --host 0.0.0.0 --port 8001
    ```

---

## Deployment

To deploy the services to Cloud Run, you can use commands like:

```bash
# For app_ticketing (run from app_ticketing directory)
gcloud run deploy ticketing-agent --source . --region us-central1 --allow-unauthenticated --env-vars-file=.env --port=8001

# For app (run from app directory)
gcloud run deploy a2a-agent --source . --region us-central1 --allow-unauthenticated --env-vars-file=.env --port=8001
```